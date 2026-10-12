import importlib
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

BACKEND = Path(__file__).resolve().parents[1] / '后端代码'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import config, recognition
    from app import app
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'test-private-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    monkeypatch.setattr(config, 'GEMINI_KEY', '')
    recognition.clear()
    with TestClient(app) as value:
        assert value.post('/api/login', json={'password': config.PASSWORD}).status_code == 200
        yield value


def upload(client, color='blue', size=(120, 80)):
    output = io.BytesIO(); Image.new('RGB', size, color).save(output, 'PNG')
    response = client.post('/api/assets', files={'file': ('fixture.png', output.getvalue(), 'image/png')})
    assert response.status_code == 200
    return response.json()


def mask(client, aid, x=.1, y=.1, w=.2, h=.2):
    response = client.post('/api/masks', json={'image_id': aid, 'points': [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]})
    assert response.status_code == 200
    return response.json()


def test_parse_objects_clamps_deduplicates_and_limits():
    recognition = importlib.import_module('recognition')
    raw = '```json\n' + json.dumps({'objects': [
        {'label': ' 椅子 ', 'box': [-5, 20, 1100, 900]},
        {'label': '沙发', 'box': [[100, 200, 800, 900]]},
        {'label': '椅子', 'box': [0, 20, 1000, 900]},
        {'label': '坏框', 'box': [20, 20, 20, 30]},
        *[{'label': f'物体{i}', 'box': [i, i, i + 20, i + 20]} for i in range(30)],
    ]}, ensure_ascii=False) + '\n```'
    objects = recognition.parse_objects(raw, limit=12)
    assert objects[0] == {'label': '椅子', 'box': [0.02, 0.0, 0.9, 1.0]}
    assert len(objects) == 12
    assert all(0 <= value <= 1 for item in objects for value in item['box'])


def test_box_masks_are_cached_and_pixel_hit_prefers_smallest(tmp_path, monkeypatch):
    import config, store, segmentation
    monkeypatch.setattr(config, 'DATA', tmp_path)
    store.init()
    output = io.BytesIO(); Image.new('RGB', (100, 100), 'white').save(output, 'PNG')
    asset = store.ingest(output.getvalue(), 'chair.png')
    calls = []
    def fake_request(method, **params):
        calls.append((method, params))
        mask = Image.new('L', (100, 100), 0)
        # Return a broad mask then a tighter mask; hit selection should choose tight.
        box = params['box']
        px = tuple(round(v * 100) for v in box)
        from PIL import ImageDraw
        ImageDraw.Draw(mask).rectangle(px, fill=255)
        return store.mask_asset(mask, asset['id'], 'test-box', {'box': box, 'score': .9})
    monkeypatch.setattr(segmentation._client, 'request', fake_request)
    monkeypatch.setattr(segmentation, 'available', lambda: True)
    objects = [
        {'label': '家具', 'box': [.1, .1, .9, .9]},
        {'label': '椅子', 'box': [.2, .2, .8, .8]},
    ]
    first = segmentation.cache_boxes(asset['id'], objects)
    second = segmentation.cache_boxes(asset['id'], objects)
    assert len(calls) == 2
    assert second['cached'] is True
    hit = segmentation.cached_hit(asset['id'], .5, .5)
    assert hit['label'] == '椅子'
    assert hit['mask_id'] == first['objects'][1]['mask_id']


def test_recognition_status_is_nonblocking_and_failure_allows_fallback(tmp_path, monkeypatch):
    import config, store, recognition
    monkeypatch.setattr(config, 'DATA', tmp_path)
    store.init(); recognition.clear()
    output = io.BytesIO(); Image.new('RGB', (80, 60), 'white').save(output, 'PNG')
    asset = store.ingest(output.getvalue(), 'fixture.png')
    monkeypatch.setattr(recognition, '_recognize_and_mask', lambda aid: (_ for _ in ()).throw(RuntimeError('gateway down')))
    recognition.run(asset['id'])
    status = recognition.status(asset['id'])
    assert status['status'] == 'failed'
    assert status['objects'] == []
    assert 'gateway down' not in json.dumps(status)


def test_upload_does_not_start_recognition_without_explicit_opt_in(client, monkeypatch):
    import config, recognition
    started = []
    monkeypatch.setattr(config, 'GEMINI_KEY', 'test-key')
    monkeypatch.setattr(recognition, 'start', lambda aid: started.append(aid) or {'status': 'pending'})
    asset = upload(client)
    assert started == []
    assert client.get('/api/recognition/' + asset['id']).json()['status'] in ('idle', 'pending')


def test_upload_and_current_asset_recognition_require_explicit_opt_in(client, monkeypatch):
    import config, recognition
    started = []
    monkeypatch.setattr(config, 'GEMINI_KEY', 'test-key')
    monkeypatch.setattr(recognition, 'start', lambda aid: started.append(aid) or {'status': 'pending'})
    output = io.BytesIO(); Image.new('RGB', (120, 80), 'blue').save(output, 'PNG')
    response = client.post('/api/assets?pre_recognition=true', files={'file': ('fixture.png', output.getvalue(), 'image/png')})
    assert response.status_code == 200
    aid = response.json()['id']
    assert started == [aid]
    assert client.post('/api/recognition/' + aid + '/start').status_code == 200
    assert started == [aid, aid]


def test_recognition_cancel_prevents_queued_cloud_call(tmp_path, monkeypatch):
    import config, store, recognition
    monkeypatch.setattr(config, 'DATA', tmp_path); monkeypatch.setattr(config, 'GEMINI_KEY', 'test-key')
    monkeypatch.setattr(recognition.segmentation, 'available', lambda: True)
    store.init(); recognition.clear()
    output = io.BytesIO(); Image.new('RGB', (80, 60), 'white').save(output, 'PNG')
    asset = store.ingest(output.getvalue(), 'fixture.png')
    calls = []
    monkeypatch.setattr(recognition, '_recognize_and_mask', lambda aid: calls.append(aid) or {'objects': []})
    monkeypatch.setattr(recognition._executor, 'submit', lambda fn, aid: None)
    recognition.start(asset['id'])
    recognition.cancel(asset['id'])
    recognition.run(asset['id'])
    assert calls == []
    assert recognition.status(asset['id'])['status'] == 'cancelled'


def test_select_returns_cached_whole_object_before_point_sam(client, monkeypatch):
    import segmentation
    asset = upload(client)
    mask_asset = mask(client, asset['id'], .1, .1, .8, .8)
    monkeypatch.setattr(segmentation, 'cached_hit', lambda aid, x, y: {'label': '椅子', 'mask_id': mask_asset['id'], 'box': [.1,.1,.9,.9]})
    monkeypatch.setattr(segmentation, 'select', lambda *args: (_ for _ in ()).throw(AssertionError('point SAM should not run')))
    response = client.post('/api/segmentation/select', json={'image_id': asset['id'], 'x': .5, 'y': .5})
    assert response.status_code == 200
    assert response.json()['recognition_cached'] is True
    assert response.json()['label'] == '椅子'
