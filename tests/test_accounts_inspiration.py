import io
import sys
from pathlib import Path

from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import config
import store
from app import app


def register(client, email):
    response = client.post('/api/register', json={'email': email, 'password': 'strong-pass-123'})
    assert response.status_code == 201, response.text
    return response.json()['user']


def png_bytes(color):
    output = io.BytesIO()
    Image.new('RGB', (24, 18), color).save(output, 'PNG')
    return output.getvalue()


def test_guest_can_browse_but_actions_require_account(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'legacy-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    with TestClient(app) as client:
        data = client.get('/api/inspiration').json()
        assert len(data['items']) >= 8
        item = data['items'][0]
        assert client.get(f"/api/inspiration/{item['id']}/image").status_code == 200
        assert client.put(f"/api/inspiration/{item['id']}/favorite", json={'favorite': True}).status_code == 401


def test_registration_login_and_duplicate_email(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'legacy-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    with TestClient(app) as client:
        register(client, 'Maker@Example.com')
        assert client.get('/api/me').json()['user']['email'] == 'maker@example.com'
        client.post('/api/logout')
        assert client.get('/api/me').json()['user'] is None
        assert client.post('/api/login', json={'email': 'maker@example.com', 'password': 'strong-pass-123'}).status_code == 200
        client.post('/api/logout')
        assert client.post('/api/register', json={'email': 'MAKER@example.com', 'password': 'another-pass-123'}).status_code == 409


def test_drive_and_drafts_are_isolated_between_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'legacy-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    with TestClient(app) as first, TestClient(app) as second:
        register(first, 'first@example.com')
        register(second, 'second@example.com')
        upload = first.post('/api/drive/files', files={'file': ('first.png', png_bytes('red'), 'image/png')}).json()
        private_asset = first.post('/api/assets', files={'file': ('private.png', png_bytes('blue'), 'image/png')}).json()
        draft = first.get('/api/drafts/latest').json()
        assert second.get('/api/drive/items').json()['items'] == []
        assert second.get(f"/api/drive/files/{upload['id']}").status_code == 404
        assert second.get(f"/api/assets/{private_asset['id']}").status_code == 404
        assert second.get(f"/api/assets/{private_asset['id']}/meta").status_code == 404
        assert second.post(f"/api/recognition/{private_asset['id']}/start").status_code == 404
        assert second.get(f"/api/drafts/{draft['id']}").status_code == 404


def test_inspiration_favorite_copies_to_drive_and_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'legacy-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    with TestClient(app) as client:
        register(client, 'creator@example.com')
        item = client.get('/api/inspiration').json()['items'][0]
        assert client.post(f"/api/inspiration/{item['id']}/drive").status_code == 200
        assert client.put(f"/api/inspiration/{item['id']}/favorite", json={'favorite': True}).json()['favorite'] is True
        assert client.get('/api/drive/items').json()['items'][0]['name'].endswith('.png')
        result = client.post(f"/api/inspiration/{item['id']}/workspace").json()
        assert result['asset']['id'] in result['draft']['references']
        assert client.get('/api/drafts/latest').json()['references'] == result['draft']['references']


def test_workspace_add_tolerates_existing_assets_without_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'legacy-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    with TestClient(app) as client:
        register(client, 'existing-assets@example.com')
        existing = client.post('/api/assets', files={
            'file': ('existing.png', png_bytes('blue'), 'image/png'),
        }).json()
        draft = client.get('/api/drafts/latest').json()
        draft['references'] = [existing['id']]
        assert client.put(f"/api/drafts/{draft['id']}", json=draft).status_code == 200

        item = client.get('/api/inspiration').json()['items'][0]
        response = client.post(f"/api/inspiration/{item['id']}/workspace")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['draft']['main_image'] is None
        assert result['draft']['references'] == [existing['id'], result['asset']['id']]


def test_likes_are_persistent_idempotent_and_independent_from_favorites(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'MODE', 'simulation')
    with TestClient(app) as client:
        item = client.get('/api/inspiration').json()['items'][0]
        endpoint = f"/api/inspiration/{item['id']}/like"
        base_likes = item['like_count']
        assert item['description'] and 0 <= base_likes <= 60 and not item['liked']
        assert client.put(endpoint, json={'liked': True}).status_code == 401
        register(client, 'like-first@example.com')
        for _ in range(2):
            assert client.put(endpoint, json={'liked': True}).json()['like_count'] == base_likes + 1
        item = client.get('/api/inspiration').json()['items'][0]
        assert item['liked'] and not item['favorite']
        assert client.put(endpoint, json={'liked': 'false'}).status_code == 400
        thumb = client.get(f"/api/inspiration/{item['id']}/image?thumbnail=true")
        assert max(Image.open(io.BytesIO(thumb.content)).size) <= 360
        client.post('/api/logout')
        register(client, 'like-second@example.com')
        item = client.get('/api/inspiration').json()['items'][0]
        assert not item['liked'] and item['like_count'] == base_likes + 1
        assert client.put(endpoint, json={'liked': True}).json()['like_count'] == base_likes + 2
        assert client.put(endpoint, json={'liked': False}).json()['like_count'] == base_likes + 1
        client.post('/api/logout')
        client.post('/api/login', json={'email': 'like-first@example.com', 'password': 'strong-pass-123'})
        assert client.get('/api/inspiration').json()['items'][0]['liked']
        assert client.put(endpoint, json={'liked': False}).json()['like_count'] == base_likes
