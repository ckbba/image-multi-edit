"""Real point-prompt SlimSAM; no fabricated rectangle fallback."""
import threading
import time
from collections import OrderedDict
import numpy as np
from PIL import Image
from fastapi import HTTPException
import config
import store

lock = threading.Lock()
model = processor = torch = None
embeddings = OrderedDict()
points_cache = OrderedDict()


def available():
    return (config.MODEL_DIR / 'model.safetensors').is_file()


def load():
    global model, processor, torch
    if model is None:
        if not available():
            raise HTTPException(503, '真实分割模型未安装，可手动圈选；请运行下载脚本')
        import torch as pt
        from transformers import SamModel, SamProcessor
        torch = pt
        torch.set_num_threads(4)
        # Keep the Windows service stable by defaulting to CPU. CUDA remains an
        # explicit opt-in after driver stability is verified on the host.
        device = 'cuda' if config.SEGMENTATION_DEVICE == 'cuda' and torch.cuda.is_available() else 'cpu'
        model = SamModel.from_pretrained(str(config.MODEL_DIR), local_files_only=True).to(device).eval()
        processor = SamProcessor.from_pretrained(str(config.MODEL_DIR), local_files_only=True)


def prepare_unlocked(aid):
    load()
    if aid not in embeddings:
        im = store.image(aid).convert('RGB')
        batch = processor(images=im, return_tensors='pt').to(model.device)
        with torch.inference_mode():
            encoded = model.get_image_embeddings(batch['pixel_values'])
        embeddings[aid] = (encoded, batch['original_sizes'], batch['reshaped_input_sizes'])
        while len(embeddings) > 10:
            embeddings.popitem(last=False)
    embeddings.move_to_end(aid)
    return embeddings[aid]


def prepare(aid):
    start = time.perf_counter()
    with lock:
        prepare_unlocked(aid)
    return {'ready': True, 'elapsed_ms': round((time.perf_counter() - start) * 1000, 2), 'device': str(model.device)}


def select(aid, x, y):
    start = time.perf_counter()
    key = (aid, round(x, 3), round(y, 3))
    with lock:
        if key in points_cache:
            return dict(candidates=points_cache[key], elapsed_ms=round((time.perf_counter() - start) * 1000, 2), cached=True)
        meta = store.asset(aid)
        encoded, original, reshaped = prepare_unlocked(aid)
        # SAM's longest-side transform; point is in orientation-normalized original coordinates.
        sx = x * float(reshaped[0, 1]); sy = y * float(reshaped[0, 0])
        with torch.inference_mode():
            out = model(image_embeddings=encoded, input_points=torch.tensor([[[[sx, sy]]]], device=model.device),
                        input_labels=torch.tensor([[[1]]], device=model.device), multimask_output=True)
            masks = processor.image_processor.post_process_masks(out.pred_masks.cpu(), original.cpu(), reshaped.cpu())[0][0]
            scores = out.iou_scores[0, 0].cpu().numpy()
        result = []
        for i in np.argsort(-scores):
            values = masks[int(i)].numpy().astype('uint8') * 255
            if not values[min(meta['height'] - 1, int(y * meta['height'])), min(meta['width'] - 1, int(x * meta['width']))]:
                continue
            if values.any():
                mask = store.mask_asset(Image.fromarray(values), aid, 'slimsam-77-uniform', {'score': float(scores[i])})
                result.append(mask)
        points_cache[key] = result
        while len(points_cache) > 100:
            points_cache.popitem(last=False)
    return dict(candidates=result, elapsed_ms=round((time.perf_counter() - start) * 1000, 2), cached=False)
