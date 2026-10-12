"""Process-isolated point-prompt SlimSAM; no fabricated rectangle fallback."""
import atexit
import importlib
import multiprocessing
import threading
import time
from pathlib import Path

from fastapi import HTTPException

import config


def _entry(connection, worker, settings):
    module_name, function_name = worker.split(':', 1)
    getattr(importlib.import_module(module_name), function_name)(connection, settings)


class SamProcessClient:
    def __init__(self, worker='sam_worker:serve', timeout=None):
        self.worker = worker
        self.timeout = timeout if timeout is not None else float(__import__('os').getenv('SEGMENTATION_TIMEOUT_SECONDS', '180'))
        self.lock = threading.Lock()
        self.process = None
        self.connection = None
        self.last_failed_pid = None
        self.context = multiprocessing.get_context('spawn')

    def _settings(self):
        return {'data_dir': str(config.DATA), 'model_dir': str(config.MODEL_DIR), 'device': config.SEGMENTATION_DEVICE}

    def _start(self):
        parent, child = self.context.Pipe()
        process = self.context.Process(target=_entry, args=(child, self.worker, self._settings()), name='slimsam-worker', daemon=True)
        process.start()
        child.close()
        self.connection, self.process = parent, process
        if not parent.poll(30) or parent.recv() != {'ready': True}:
            self._discard()
            raise HTTPException(503, '智能选区进程启动失败，服务其余功能不受影响；请重试选区')

    def _discard(self):
        process, connection = self.process, self.connection
        self.process = self.connection = None
        if process is not None:
            self.last_failed_pid = process.pid
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill(); process.join(timeout=2)
        if connection is not None:
            connection.close()

    def request(self, method, **params):
        with self.lock:
            if self.process is None or not self.process.is_alive():
                self._discard()
                self._start()
            try:
                self.connection.send({'method': method, **params})
                if not self.connection.poll(self.timeout):
                    raise TimeoutError('SAM worker timed out')
                response = self.connection.recv()
            except (EOFError, BrokenPipeError, OSError, TimeoutError):
                self._discard()
                raise HTTPException(503, '智能选区进程异常，服务其余功能不受影响；请重试选区')
            if not response.get('ok'):
                raise HTTPException(int(response.get('status', 500)), response.get('detail', '智能选区失败'))
            return response['result']

    def close(self):
        with self.lock:
            if self.process is not None and self.process.is_alive():
                try:
                    self.connection.send({'method': 'stop'})
                    self.process.join(timeout=2)
                except (EOFError, BrokenPipeError, OSError):
                    pass
            self._discard()


_client = SamProcessClient()
_box_cache = {}
_box_cache_lock = threading.Lock()
_BOX_TTL = 3600
atexit.register(_client.close)


def available():
    return (config.MODEL_DIR / 'model.safetensors').is_file()


def _require_available():
    if not available():
        raise HTTPException(503, '真实分割模型未安装，可手动圈选；请运行下载脚本')


def prepare(aid):
    _require_available()
    return _client.request('prepare', image_id=aid)


def select(aid, x, y):
    _require_available()
    return _client.request('select', image_id=aid, x=x, y=y)


def cache_boxes(aid, objects):
    now = time.time()
    with _box_cache_lock:
        current = _box_cache.get(aid)
        if current and now - current['updated'] < _BOX_TTL:
            return {'objects': current['objects'], 'cached': True}
    masked = []
    for item in objects[:12]:
        try:
            mask = _client.request('box', image_id=aid, box=item['box'])
        except HTTPException:
            continue
        masked.append({**item, 'mask_id': mask['id'], 'bbox': mask['bbox']})
    with _box_cache_lock:
        _box_cache[aid] = {'updated': now, 'objects': masked}
    return {'objects': masked, 'cached': False}


def cached_hit(aid, x, y):
    with _box_cache_lock:
        objects = list((_box_cache.get(aid) or {}).get('objects', []))
    hits = []
    for item in objects:
        x1, y1, x2, y2 = item['box']
        if x1 <= x <= x2 and y1 <= y <= y2:
            try:
                image = __import__('store').image(item['mask_id']).getchannel('A')
                px = min(image.width - 1, int(x * image.width)); py = min(image.height - 1, int(y * image.height))
                if image.getpixel((px, py)):
                    hits.append(item)
            except Exception:
                continue
    return min(hits, key=lambda item: (item['box'][2]-item['box'][0])*(item['box'][3]-item['box'][1]), default=None)


def close():
    _client.close()
