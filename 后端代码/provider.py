"""65535 adapter for ordered mixed reference and native-mask edits."""
import base64
import io
import ipaddress
import json
import os
import socket
import time
from urllib.parse import urlparse

import httpx
import numpy as np
from PIL import Image, ImageDraw
from fastapi import HTTPException
import config
import store

COMPILER_VERSION = 'mixed-input-v5-text-edits'


def preflight(model=None):
    model = model or config.MODEL
    if not config.KEY or model not in store.GENERATION_MODELS:
        raise HTTPException(409, '必须配置指定 Image2.5 渠道密钥和模型 ID；不会替换模型')
    with httpx.Client(timeout=30) as client:
        headers = {'Authorization': 'Bearer ' + config.KEY}
        model_response = client.get(config.BASE + '/v1/models', headers=headers)
        model_response.raise_for_status()
        pricing_response = client.get(config.BASE + '/v1/pricing', headers=headers)
        pricing_response.raise_for_status()
        models = model_response.json()
        prices = pricing_response.json()
    models = models.get('data', models) if isinstance(models, dict) else models
    prices = prices.get('data', prices) if isinstance(prices, dict) else prices
    price = next((p for p in prices if p['id'] == model), None)
    if not any(m['id'] == model for m in models) or not price or 'image' not in price.get('endpoints', []) or not price.get('online'):
        raise HTTPException(409, '当前模型在账户不可用、离线或没有 image 端点')
    return price


def png(im):
    f = io.BytesIO(); im.save(f, format='PNG'); return f.getvalue()


def native_edit_mask(mask_ids, main_image_id):
    """Build an OpenAI-style mask where transparent pixels are editable."""
    base = store.image(main_image_id)
    alpha = np.full((base.height, base.width), 255, dtype=np.uint8)
    for mask_id in mask_ids:
        selected = np.asarray(store.image(mask_id).getchannel('A').resize(base.size, Image.Resampling.NEAREST))
        alpha = np.minimum(alpha, 255 - selected)
    result = Image.new('RGBA', base.size, (0, 0, 0, 255))
    result.putalpha(Image.fromarray(alpha))
    return png(result)


def compile_request(state, strategy=None):
    model = state.get('generation_model', store.DEFAULT_GENERATION_MODEL)
    if model not in store.GENERATION_MODELS:
        raise HTTPException(400, '请选择受支持的生成模型')
    actual_references = len([m for m in state.get('mappings', []) if m.get('source')]) + len(state.get('full_image_refs', []))
    if actual_references > store.MODEL_REFERENCE_LIMIT:
        raise HTTPException(400, f'当前共 {actual_references} 个实际参考输入，最多 12 个；请删除部分元素操作或整图引用后再生成')
    # Element bindings always use the product's context crop. Whole-image intent is
    # represented separately by explicit full_image_refs, never by a global switch.
    strategy = strategy or 'context-crop'
    if strategy not in ('full', 'context-crop', 'transparent'):
        raise ValueError('Unknown source strategy')
    inputs = [state['main_image']]
    bindings = []
    mask_asset_ids = []
    lines = ['Edit IMAGE 1 as the base photograph. Perform all user-directed edits listed below in ONE final photograph.',
             'Preserve unrelated content unless a user requirement explicitly asks to change it.',
             'Each source belongs ONLY to its listed operation. Adapt source objects naturally to target perspective, lighting and occlusion.',
             'Coordinates below are normalized [0,1] regions in the original images, not API control parameters.',
             'Do not reproduce masks, labels, guide outlines or numbered markings in the final image.']
    for m in state['mappings']:
        src, tgt = m.get('source'), m['target']
        action = m.get('requirement', '').strip()
        if not src:
            target_bbox = store.asset(tgt['mask_id'])['bbox']
            mask_asset_ids.append(tgt.get('edit_region_id', tgt['mask_id']))
            lines.append(f'Operation {m["display_index"]}: edit only the selected IMAGE 1 target region {target_bbox}, '
                         f'near normalized point ({tgt["anchor"]["x"]}, {tgt["anchor"]["y"]}). User requirement: {action}.')
            bindings.append({'kind': 'main-edit', 'mapping_id': m['id'], 'display_index': m['display_index'],
                             'target_bbox': target_bbox, 'target_anchor': dict(tgt['anchor']), 'mask_id': mask_asset_ids[-1]})
            continue
        source_id = src['image_id']
        source_mask = store.asset(src['mask_id'])
        bbox = source_mask['bbox']
        derived = None
        if strategy != 'full':
            im = store.image(source_id).convert('RGBA')
            if strategy == 'transparent':
                im.putalpha(store.image(src['mask_id']).getchannel('A'))
            dx, dy = (bbox[2] - bbox[0]) * .08, (bbox[3] - bbox[1]) * .08
            box = (max(0, int((bbox[0] - dx) * im.width)), max(0, int((bbox[1] - dy) * im.height)),
                   min(im.width, int((bbox[2] + dx) * im.width + 1)), min(im.height, int((bbox[3] + dy) * im.height + 1)))
            derived = store.persist_image(im.crop(box), f'source-{m["display_index"]}.png', 'crop',
                {'image_id': source_id, 'box_pixels': box, 'margin_fraction': .08, 'strategy': strategy, 'strategy_version': 1})
            source_id = derived['id']
        inputs.append(source_id)
        index = len(inputs)
        target_bbox = store.asset(tgt['mask_id'])['bbox']
        lines.append(f'Operation {m["display_index"]}: use the selected object {src.get("label", "")} from IMAGE {index}, '
                     f'source region {bbox if strategy == "full" else "the central selected object in the crop"}, '
                     f'for the edit around IMAGE 1 target region {target_bbox}, '
                     f'with intended location near normalized point ({tgt["anchor"]["x"]}, {tgt["anchor"]["y"]}). '
                     + (f'User requirement: {action}. ' if action else 'Default intent: replace the selected target object with the source object. ')
                     + 'Do not copy the source background unless explicitly requested.')
        bindings.append({'kind':'element','mapping_id': m['id'], 'display_index': m['display_index'], 'input_index': index,
                         'original_id': src['image_id'], 'input_asset_id': source_id, 'crop': derived, 'target_bbox': target_bbox,
                         'target_anchor': dict(tgt['anchor'])})
    for edit in state.get('text_edits', []):
        original, replacement, bbox = edit['original_text'].strip(), edit['replacement'].strip(), edit['bbox']
        lines.append(f'Text edit in IMAGE 1 region {bbox}: replace the exact visible text "{original}" with "{replacement}". '
                     'Match the original typography, perspective, material, lighting and spacing; preserve all other text and pixels as closely as possible.')
        bindings.append({'kind':'text-edit','text_edit_id':edit['id'],'original_text':original,
                         'replacement':replacement,'bbox':bbox, **({'polygon': edit['polygon']} if edit.get('polygon') else {})})
    for reference in state.get('full_image_refs', []):
        inputs.append(reference['image_id']);index=len(inputs)
        purpose=reference.get('purpose', '').strip() or 'use as an overall visual reference'
        lines.append(f'Whole-image reference IMAGE {index} ({reference.get("label", "reference")}): {purpose}. This is a complete-image reference, distinct from any cropped element input from the same source.')
        bindings.append({'kind':'full-image','reference_id':reference['id'],'input_index':index,'original_id':reference['image_id'],'purpose':purpose})
    if state.get('instructions'):
        lines.append('Additional user requirements: ' + state['instructions'])
    return dict(prompt='\n'.join(lines), inputs=inputs, bindings=bindings, mask_asset_ids=mask_asset_ids, strategy=strategy,
                compiler_version=COMPILER_VERSION, model=model, mask_mode='native-openai-alpha' if mask_asset_ids else 'disabled',
                quality=os.getenv('IMAGE25_QUALITY') or None, size='auto', execution='batch-experimental')


def call(compiled, native_mask=None):
    data = {'model': compiled['model'], 'prompt': compiled['prompt'], 'size': compiled.get('size', 'auto')}
    if compiled.get('quality'):
        data['quality'] = compiled['quality']
    files = [('image[]', (f'image-{i+1}.png', (config.DATA / store.asset(aid)['path']).read_bytes(), 'image/png'))
             for i, aid in enumerate(compiled['inputs'])]
    if native_mask is not None:
        files.append(('mask', ('mask.png', native_mask, 'image/png')))
    start = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(300, connect=30)) as client:
        response = client.post(config.BASE + '/v1/images/edits', headers={'Authorization': 'Bearer ' + config.KEY}, data=data, files=files)
    elapsed = round(time.monotonic() - start, 3)
    if response.status_code >= 500:
        raise RuntimeError(f'upstream-unknown HTTP {response.status_code}; 是否扣费待核对')
    if response.status_code >= 400:
        raise ValueError(f'HTTP {response.status_code}: {response.text[:500]}')
    payload = response.json()
    outputs = payload.get('data', [])
    if not outputs:
        infos = payload.get('Response', {}).get('AigcImageTask', {}).get('Output', {}).get('FileInfos', [])
        outputs = [{'url': item['FileUrl']} for item in infos]
    if not outputs or not (outputs[0].get('url') or outputs[0].get('b64_json')):
        raise RuntimeError('upstream-unknown 上游返回缺少图像；不得自动重发')
    return dict(outputs=outputs, elapsed_s=elapsed, request_id=response.headers.get('x-request-id') or outputs[0].get('generation_id'),
                usage=payload.get('usage'), cost_usd=payload.get('cost_usd'), calls=1)


def download(url):
    # No arbitrary browser-provided URLs; also protect against a compromised upstream response.
    for _ in range(5):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username:
            raise ValueError('结果地址必须为 HTTPS')
        for info in socket.getaddrinfo(parsed.hostname, 443):
            if not ipaddress.ip_address(info[4][0]).is_global:
                raise ValueError('拒绝内网结果地址')
        with httpx.stream('GET', url, timeout=60) as response:
            if response.is_redirect:
                from urllib.parse import urljoin
                url = urljoin(url, response.headers['location']); continue
            response.raise_for_status()
            if response.headers.get('content-type', '').split(';')[0] not in ('image/png', 'image/jpeg', 'image/webp'):
                raise ValueError('上游返回的不是受支持图像')
            chunks, length = [], 0
            for chunk in response.iter_bytes():
                length += len(chunk)
                if length > 20 * 1024 * 1024:
                    raise ValueError('结果超过 20 MB 保存上限')
                chunks.append(chunk)
            return b''.join(chunks)
    raise ValueError('上游重定向过多')


def save_outputs(jid):
    job = store.job(jid, include_deleted=True)
    result = job['result']
    store.update_job(jid, 'saving', result)
    try:
        saved = list(result.get('assets', []))
        for item in result['outputs'][len(saved):]:
            content = base64.b64decode(item['b64_json'], validate=True) if item.get('b64_json') else download(item['url'])
            meta = store.ingest(content, f'edit-{jid}.png', 'output')
            saved.append(meta['id'])
            result['assets'] = saved
            store.update_job(jid, 'saving', result)
        result.pop('error', None)
        store.update_job(jid, 'succeeded', result)
    except Exception as exc:
        result['error'] = f'结果已生成但保存失败：{type(exc).__name__}；可重试保存，不会再次生图'
        store.update_job(jid, 'save_failed', result)


def execute(jid):
    job = store.job(jid, include_deleted=True)
    if job['status'] != 'queued':
        return
    store.update_job(jid, 'running', {})
    if job['snapshot']['mode'] == 'simulation':
        store.update_job(jid, 'simulated', {'calls': 0, 'cost_usd': 0,
                     'message': '模拟检查完成：仅验证快照和持久化，未调用 Image2.5，没有生成图片。'})
        return
    try:
        compiled = job['snapshot']['compiled']
        native_mask = native_edit_mask(compiled.get('mask_asset_ids', []), job['snapshot']['state']['main_image']) if compiled.get('mask_asset_ids') else None
        result = call(compiled, native_mask) if native_mask is not None else call(compiled)
        # Persist locator before downloading, so retry-save never invokes the model.
        store.update_job(jid, 'saving', result)
        save_outputs(jid)
    except ValueError as exc:
        store.update_job(jid, 'failed', {'error': str(exc), 'cost_usd': None})
    except Exception as exc:
        store.update_job(jid, 'unknown', {'error': f'{type(exc).__name__}：上游状态未知；请核对渠道任务，未自动重试。', 'cost_usd': None})
