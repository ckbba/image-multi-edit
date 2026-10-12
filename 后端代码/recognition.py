"""Bounded background whole-object recognition via Gemini."""
import base64
import io
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from PIL import Image

import config
import store
import segmentation

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='object-recognition')
_lock = threading.Lock()
_entries = {}
TTL_SECONDS = 3600
MAX_OBJECTS = 12


def parse_objects(text, limit=MAX_OBJECTS):
    text = (text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I)
    data = json.loads(text)
    result = []
    seen = set()
    for item in data.get('objects', []):
        label = str(item.get('label', '')).strip()[:40]
        box = item.get('box')
        if isinstance(box, list) and len(box) == 1 and isinstance(box[0], list):
            box = box[0]
        if not label or not isinstance(box, list) or len(box) != 4:
            continue
        try:
            ymin, xmin, ymax, xmax = [max(0, min(1000, float(v))) for v in box]
        except (TypeError, ValueError):
            continue
        if ymax - ymin < 2 or xmax - xmin < 2:
            continue
        normalized = [round(xmin / 1000, 4), round(ymin / 1000, 4), round(xmax / 1000, 4), round(ymax / 1000, 4)]
        key = (label.casefold(), tuple(normalized))
        if key in seen:
            continue
        seen.add(key)
        result.append({'label': label, 'box': normalized})
        if len(result) >= limit:
            break
    return result


def _image_data(aid):
    image = store.image(aid).convert('RGB')
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    output = io.BytesIO(); image.save(output, 'JPEG', quality=85, optimize=True)
    return base64.b64encode(output.getvalue()).decode()


def _gemini(aid):
    prompt = ('Detect every complete visible physical object. Return a short Chinese label and a tight bounding box '
              'covering the whole visible object, including disconnected visible parts such as a chair back, seat, '
              'arms and every visible leg. Do not split one object into parts. Coordinates are integer 0..1000 '
              'as [ymin,xmin,ymax,xmax]. Return only JSON {"objects":[{"label":"椅子","box":[0,0,1000,1000]}]}. '
              f'Max {MAX_OBJECTS} objects.')
    payload = {
        'model': config.GEMINI_MODEL,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + _image_data(aid)}}]}],
        'temperature': 0,
        'max_tokens': 900,
        'response_format': {'type': 'json_object'},
        # cccodex is OpenAI-compatible; this field is forwarded when supported.
        'extra_body': {'generationConfig': {'thinkingConfig': {'thinkingBudget': 0}}},
    }
    start = time.perf_counter()
    with httpx.Client(timeout=httpx.Timeout(config.GEMINI_TIMEOUT, connect=10)) as client:
        response = client.post(config.GEMINI_BASE, headers={'Authorization': 'Bearer ' + config.GEMINI_KEY}, json=payload)
    response.raise_for_status()
    body = response.json()
    objects = parse_objects(body['choices'][0]['message'].get('content'), MAX_OBJECTS)
    return objects, round((time.perf_counter() - start) * 1000, 2), body.get('usage', {})


def _recognize_and_mask(aid):
    objects, gemini_ms, usage = _gemini(aid)
    masked = segmentation.cache_boxes(aid, objects)['objects']
    return {'objects': masked, 'gemini_ms': gemini_ms, 'usage': usage, 'model': config.GEMINI_MODEL}


def run(aid):
    with _lock:
        if _entries.get(aid, {}).get('status') == 'cancelled':
            return public(_entries[aid])
    try:
        result = _recognize_and_mask(aid)
        entry = {'status': 'ready', **result, 'updated': time.time()}
    except Exception:
        entry = {'status': 'failed', 'objects': [], 'updated': time.time()}
    with _lock:
        if _entries.get(aid, {}).get('status') == 'cancelled':
            return public(_entries[aid])
        _entries[aid] = entry
    return entry


def start(aid):
    if not config.GEMINI_KEY or not segmentation.available():
        return {'status': 'unavailable', 'objects': []}
    now = time.time()
    with _lock:
        current = _entries.get(aid)
        if current and now - current.get('updated', now) < TTL_SECONDS:
            return public(current)
        _entries[aid] = {'status': 'pending', 'objects': [], 'updated': now}
    _executor.submit(run, aid)
    return {'status': 'pending', 'objects': []}


def public(entry):
    return {key: entry[key] for key in ('status', 'objects', 'gemini_ms', 'model') if key in entry}


def status(aid):
    with _lock:
        entry = _entries.get(aid)
    return public(entry) if entry else {'status': 'idle', 'objects': []}


def cancel(aid):
    with _lock:
        _entries[aid] = {'status': 'cancelled', 'objects': [], 'updated': time.time()}
    return {'status': 'cancelled', 'objects': []}


def clear():
    with _lock:
        _entries.clear()
