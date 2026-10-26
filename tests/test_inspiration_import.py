import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '后端代码'))
import config
import store
import inspiration

spec = importlib.util.spec_from_file_location('inspiration_import', ROOT / 'scripts/import_inspiration.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    store.init()
    inspiration.init()
    Image.new('RGB', (30, 40), 'blue').save(tmp_path / 'sample.png')
    manifest = tmp_path / 'manifest.json'
    entries = [dict(id='sample-product', title='商品案例', category='商品摄影',
                    file='sample.png', source='Self-created', prompt='Blue product')]
    manifest.write_text(json.dumps(entries), encoding='utf-8')
    return tmp_path, manifest, entries


def test_import_is_idempotent_and_demo_hiding_is_reversible(catalogue):
    data, manifest, entries = catalogue
    result = importer.import_manifest(manifest, data, hide_demo=True)
    assert Path(result['backup']).is_file()
    items = inspiration.list_items()['items']
    assert [item['id'] for item in items] == ['sample-product']
    asset_id = items[0]['asset_id']
    assert store.asset(asset_id)['origin']['prompt'] == 'Blue product'
    importer.import_manifest(manifest, data, hide_demo=True)
    assert inspiration.list_items()['items'][0]['asset_id'] == asset_id
    with store.db() as con:
        assert con.execute('SELECT COUNT(*) FROM inspiration_items WHERE published=0').fetchone()[0] == 12
        assert con.execute('SELECT COUNT(*) FROM assets').fetchone()[0] == 13


def test_invalid_batch_does_not_publish_partial_results(catalogue):
    data, manifest, entries = catalogue
    entries.append(dict(entries[0], id='missing-file', file='missing.png'))
    manifest.write_text(json.dumps(entries), encoding='utf-8')
    with pytest.raises(FileNotFoundError):
        importer.import_manifest(manifest, data, hide_demo=True)
    assert len(inspiration.list_items()['items']) == 12
    assert not list(data.glob('inspiration-before-import-*.sqlite'))


def test_reimport_preserves_unpublished_and_trash_state(catalogue):
    data, manifest, _ = catalogue
    importer.import_manifest(manifest, data)
    with store.db() as con:
        assert con.execute('SELECT name FROM inspiration_categories WHERE name=?', ('商品摄影',)).fetchone()
        con.execute("UPDATE inspiration_items SET published=0 WHERE id='sample-product'")
    importer.import_manifest(manifest, data)
    with store.db() as con:
        assert con.execute("SELECT published FROM inspiration_items WHERE id='sample-product'").fetchone()[0] == 0
        con.execute("UPDATE inspiration_items SET deleted_at=123 WHERE id='sample-product'")
    importer.import_manifest(manifest, data)
    with store.db() as con:
        row = con.execute("SELECT published,deleted_at FROM inspiration_items WHERE id='sample-product'").fetchone()
        assert tuple(row) == (0,123)


def test_changed_image_cannot_silently_replace_existing_asset(catalogue):
    data, manifest, entries = catalogue
    importer.import_manifest(manifest, data)
    asset_id = inspiration.list_items()['items'][0]['asset_id']
    Image.new('RGB', (30, 40), 'red').save(data / 'sample.png')
    with pytest.raises(ValueError, match='已有不同图片'):
        importer.import_manifest(manifest, data)
    assert inspiration.list_items()['items'][0]['asset_id'] == asset_id
