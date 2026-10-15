import io
import sys
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import config
import store
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'drive-test-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    with TestClient(app) as value:
        assert value.post('/api/login', json={'password': config.PASSWORD}).status_code == 200
        yield value


def create_folder(client, name, parent_id=None):
    response = client.post('/api/drive/folders', json={'name': name, 'parent_id': parent_id})
    assert response.status_code == 200, response.text
    return response.json()


def upload(client, name='photo.png', content=b'png bytes', parent_id=None):
    response = client.post('/api/drive/files', data={'parent_id': parent_id or ''},
                           files={'file': (name, content, 'image/png')})
    assert response.status_code == 200, response.text
    return response.json()


def png_bytes(color='red'):
    output = io.BytesIO()
    Image.new('RGB', (32, 24), color).save(output, 'PNG')
    return output.getvalue()


def test_drive_requires_auth_and_persists_files(client):
    folder = create_folder(client, '项目')
    item = upload(client, '../unsafe.png', b'hello', folder['id'])
    assert item['name'] == 'unsafe.png'
    assert client.get('/api/drive/items', params={'parent_id': folder['id']}).json()['items'][0]['id'] == item['id']
    assert client.get('/api/drive/storage').json()['used_bytes'] == 5
    downloaded = client.get(f"/api/drive/files/{item['id']}")
    assert downloaded.content == b'hello'
    assert '..' not in downloaded.headers['content-disposition']
    client.post('/api/logout')
    assert client.get('/api/drive/items').status_code == 401


def test_active_documents_cannot_be_served_inline(client):
    item = client.post('/api/drive/files', files={'file': ('page.html', b'<script>alert(1)</script>', 'text/html')}).json()
    response = client.get(f"/api/drive/files/{item['id']}?inline=true")
    assert response.headers['content-disposition'].startswith('attachment')
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'sandbox' in response.headers['content-security-policy']


def test_cross_folder_search_breadcrumb_sort_and_favorites(client):
    folder = create_folder(client, '设计')
    first = upload(client, 'zeta.txt', b'z', folder['id'])
    upload(client, 'alpha.txt', b'alpha', folder['id'])
    result = client.get('/api/drive/search', params={'q': 'zeta'}).json()['items'][0]
    assert result['id'] == first['id'] and result['path'] == '/设计'
    assert [x['name'] for x in client.get('/api/drive/items', params={'parent_id': folder['id'], 'sort': 'name', 'direction': 'asc'}).json()['items']] == ['alpha.txt', 'zeta.txt']
    assert [x['name'] for x in client.get('/api/drive/breadcrumbs', params={'item_id': folder['id']}).json()['items']] == ['所有文件', '设计']
    assert client.patch(f"/api/drive/items/{first['id']}", json={'favorite': True}).json()['favorite'] is True


def test_move_rejects_cycles_and_name_collisions(client):
    parent = create_folder(client, 'parent')
    child = create_folder(client, 'child', parent['id'])
    cycle = client.post('/api/drive/move', json={'ids': [parent['id']], 'parent_id': child['id']})
    assert cycle.status_code == 207 and cycle.json()['failed'][0]['id'] == parent['id']
    upload(client, 'same.txt', b'a', parent['id'])
    other = upload(client, 'same.txt', b'b')
    result = client.post('/api/drive/move', json={'ids': [other['id']], 'parent_id': parent['id']})
    assert result.status_code == 207
    assert result.json()['failed'][0]['id'] == other['id']


def test_subtree_trash_restore_fallback_and_permanent_delete(client):
    folder = create_folder(client, 'to-delete')
    child = upload(client, 'child.txt', b'content', folder['id'])
    assert client.post('/api/drive/trash', json={'ids': [folder['id']]}).json()['succeeded'] == [folder['id']]
    trash = client.get('/api/drive/trash').json()['items']
    assert [x['id'] for x in trash] == [folder['id']]
    assert trash[0]['purge_at'] > trash[0]['trashed_at']
    # Parent is permanently removed; restoring the child falls back to root.
    assert client.post('/api/drive/delete-permanent', json={'ids': [folder['id']]}).status_code == 200
    assert client.get(f"/api/drive/files/{child['id']}").status_code == 404

    parent = create_folder(client, 'gone')
    orphan = upload(client, 'orphan.txt', b'x', parent['id'])
    client.post('/api/drive/trash', json={'ids': [orphan['id']]})
    # Simulate legacy/corrupt metadata whose original parent no longer exists.
    with store.db() as con:
        con.execute('DELETE FROM drive_items WHERE id=?', (parent['id'],))
    restored = client.post('/api/drive/restore', json={'ids': [orphan['id']]})
    assert restored.status_code == 200
    assert client.get('/api/drive/items').json()['items'][0]['id'] == orphan['id']


def test_rename_validation_and_oversize_upload(client, monkeypatch):
    item = upload(client, 'safe.txt', b'ok')
    assert client.patch(f"/api/drive/items/{item['id']}", json={'name': '../bad'}).status_code == 400
    monkeypatch.setattr(config, 'DRIVE_MAX_FILE_BYTES', 3, raising=False)
    assert client.post('/api/drive/files', files={'file': ('big.bin', b'1234', 'application/octet-stream')}).status_code == 413


def test_folder_workflow_rejects_unsafe_segments_and_conflicts_without_merge(client):
    root = create_folder(client, 'fixture-root')
    left = create_folder(client, 'left', root['id'])
    right = create_folder(client, 'right', root['id'])
    first = upload(client, 'same.bin', b'left', left['id'])
    second = upload(client, 'same.bin', b'right', right['id'])
    note = client.post('/api/drive/files', data={'parent_id': left['id']},
                       files={'file': ('readme.txt', b'non-image', 'text/plain')})
    assert note.status_code == 200
    assert first['parent_id'] == left['id'] and second['parent_id'] == right['id']
    assert client.post('/api/drive/folders', json={'name': '..', 'parent_id': root['id']}).status_code == 400
    conflict = client.post('/api/drive/folders', json={'name': 'fixture-root', 'parent_id': None})
    assert conflict.status_code == 409
    assert [x['name'] for x in client.get('/api/drive/items', params={'parent_id': left['id']}).json()['items']] == ['readme.txt', 'same.bin']


def test_drive_reference_import_copies_verified_image_bytes_without_mutating_original(client):
    folder = create_folder(client, 'references')
    first = upload(client, 'first.png', png_bytes('red'), folder['id'])
    second = upload(client, 'second.webp', png_bytes('blue'), folder['id'])
    bad = upload(client, 'fake.png', b'not an image', folder['id'])
    note = upload(client, 'note.txt', b'hello', folder['id'])

    response = client.post('/api/drive/import-references', json={'ids': [first['id'], bad['id'], note['id'], second['id']]})
    assert response.status_code == 207
    body = response.json()
    assert [item['drive_id'] for item in body['succeeded']] == [first['id'], second['id']]
    assert {item['drive_id'] for item in body['failed']} == {bad['id'], note['id']}
    assert all(item['asset']['id'] != item['drive_id'] for item in body['succeeded'])
    imported = body['succeeded'][0]['asset']
    assert client.get('/api/assets/' + imported['id']).status_code == 200
    assert client.get('/api/drive/files/' + first['id']).content == png_bytes('red')

    assert client.post('/api/drive/trash', json={'ids': [first['id']]}).status_code == 200
    assert client.get('/api/assets/' + imported['id']).status_code == 200


def test_drive_reference_import_rejects_duplicate_or_oversized_batch(client):
    image = upload(client, 'one.png', png_bytes())
    duplicate = client.post('/api/drive/import-references', json={'ids': [image['id'], image['id']]})
    assert duplicate.status_code == 400
    oversized = client.post('/api/drive/import-references', json={'ids': [str(i) for i in range(13)]})
    assert oversized.status_code == 400
