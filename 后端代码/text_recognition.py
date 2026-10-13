"""Isolated local RapidOCR adapter; never invokes the generation provider."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from fastapi import HTTPException

import config
import store

DEFAULT_PYTHON = Path('D:/image-editor-development/text-ocr-env/Scripts/python.exe')
WORKER = Path(__file__).with_name('text_ocr_worker.py')
_cache = {}


def available():
    return Path(os.getenv('TEXT_OCR_PYTHON', str(DEFAULT_PYTHON))).is_file()


def clear_cache():
    _cache.clear()


def recognize(aid):
    asset = store.asset(aid)
    key = (aid, asset.get('version', 1))
    if key in _cache:
        return {**json.loads(json.dumps(_cache[key])), 'cached': True}
    result = _recognize_uncached(aid)
    _cache[key] = json.loads(json.dumps(result))
    return {**result, 'cached': False}


def _recognize_uncached(aid):
    image = config.DATA / store.asset(aid)['path']
    python = Path(os.getenv('TEXT_OCR_PYTHON', str(DEFAULT_PYTHON)))
    if not python.is_file():
        raise HTTPException(503, '本机真实文字识别环境未安装；未使用假识别结果')
    try:
        process = subprocess.run([str(python), str(WORKER), str(image)], capture_output=True,
                                 text=True, encoding='utf-8', timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, '本机文字识别进程不可用，请稍后重试') from exc
    if process.returncode:
        raise HTTPException(503, '本机文字识别失败，请手动修正或稍后重试')
    try:
        payload = json.loads(next(line for line in reversed(process.stdout.splitlines()) if line.lstrip().startswith('{')))
    except (json.JSONDecodeError, StopIteration) as exc:
        raise HTTPException(503, '文字识别返回无效') from exc
    items = []
    for raw in payload.get('items', [])[:80]:
        text, bbox = str(raw.get('text', '')).strip()[:200], raw.get('bbox')
        if not text or not isinstance(bbox, list) or len(bbox) != 4:
            continue
        key = json.dumps([text, [round(float(v), 5) for v in bbox]], ensure_ascii=False)
        polygon = raw.get('polygon')
        if not (isinstance(polygon, list) and 3 <= len(polygon) <= 12 and all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in p) for p in polygon)):
            polygon = [[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]]]
        items.append({**raw, 'id': hashlib.sha1(key.encode()).hexdigest()[:16], 'text': text, 'polygon': polygon,
                      'needs_review': float(raw.get('confidence', 0)) < .8})
    return {'engine': 'rapidocr', 'items': items}