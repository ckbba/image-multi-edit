"""Native SlimSAM implementation loaded only inside the isolated worker."""
import os
import time
from collections import OrderedDict

import numpy as np
from PIL import Image

model = processor = torch = None
embeddings = OrderedDict()
points_cache = OrderedDict()


def load(settings):
    global model, processor, torch
    if model is None:
        import torch as pt
        from transformers import SamModel, SamProcessor
        torch = pt
        torch.set_num_threads(int(os.getenv("SEGMENTATION_CPU_THREADS", "4")))
        device = 'cuda' if settings['device'] == 'cuda' and torch.cuda.is_available() else 'cpu'
        model = SamModel.from_pretrained(settings['model_dir'], local_files_only=True).to(device).eval()
        processor = SamProcessor.from_pretrained(settings['model_dir'], local_files_only=True)


def prepare_unlocked(aid, settings, store):
    load(settings)
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


def prepare(aid, settings, store):
    start = time.perf_counter()
    prepare_unlocked(aid, settings, store)
    return {'ready': True, 'elapsed_ms': round((time.perf_counter() - start) * 1000, 2), 'device': str(model.device)}


def select(aid, x, y, settings, store):
    start = time.perf_counter()
    key = (aid, round(x, 3), round(y, 3))
    if key in points_cache:
        return dict(candidates=points_cache[key], elapsed_ms=round((time.perf_counter() - start) * 1000, 2), cached=True)
    meta = store.asset(aid)
    encoded, original, reshaped = prepare_unlocked(aid, settings, store)
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
            result.append(store.mask_asset(Image.fromarray(values), aid, 'slimsam-77-uniform', {'score': float(scores[i])}))
    points_cache[key] = result
    while len(points_cache) > 100:
        points_cache.popitem(last=False)
    return dict(candidates=result, elapsed_ms=round((time.perf_counter() - start) * 1000, 2), cached=False)


def select_box(aid, box, settings, store):
    start = time.perf_counter()
    encoded, original, reshaped = prepare_unlocked(aid, settings, store)
    width, height = float(reshaped[0, 1]), float(reshaped[0, 0])
    x1, y1, x2, y2 = box
    input_box = torch.tensor([[[x1 * width, y1 * height, x2 * width, y2 * height]]], device=model.device)
    with torch.inference_mode():
        out = model(image_embeddings=encoded, input_boxes=input_box, multimask_output=False)
        mask = processor.image_processor.post_process_masks(out.pred_masks.cpu(), original.cpu(), reshaped.cpu())[0][0][0]
    values = mask.numpy().astype('uint8') * 255
    score = float(out.iou_scores[0, 0, 0].cpu())
    return store.mask_asset(Image.fromarray(values), aid, 'slimsam-77-box',
                            {'score': score, 'box': box, 'elapsed_ms': round((time.perf_counter() - start) * 1000, 2)})


def serve(connection, settings):
    # Imports config/store only in this child. DATA_DIR is also passed explicitly so
    # spawn has exactly the parent's data boundary even when tests monkeypatch config.
    import config
    config.DATA = __import__('pathlib').Path(settings['data_dir'])
    import store
    connection.send({'ready': True})
    while True:
        request = connection.recv()
        if request['method'] == 'stop':
            return
        try:
            if request['method'] == 'prepare':
                result = prepare(request['image_id'], settings, store)
            elif request['method'] == 'select':
                result = select(request['image_id'], request['x'], request['y'], settings, store)
            elif request['method'] == 'box':
                result = select_box(request['image_id'], request['box'], settings, store)
            else:
                raise ValueError('unknown SAM operation')
            connection.send({'ok': True, 'result': result})
        except Exception as exc:
            status = getattr(exc, 'status_code', 500)
            detail = getattr(exc, 'detail', None) or f'{type(exc).__name__}: {exc}'
            connection.send({'ok': False, 'status': status, 'detail': detail})
