"""Import a reviewed local image manifest into an existing inspiration catalogue."""
import argparse
import hashlib
import io
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '后端代码'))
import config
import inspiration
import store


def import_manifest(manifest_path, data_dir, hide_demo=False):
    manifest_path = Path(manifest_path).resolve()
    config.DATA = Path(data_dir).resolve()
    database = config.DATA / 'editor.sqlite'
    if not database.is_file():
        raise ValueError('请指定已经运行过应用的 DATA_DIR')
    entries = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(entries, list) or not entries:
        raise ValueError('清单必须包含至少一条图片记录')
    prepared, seen = [], set()
    for entry in entries:
        item_id = entry['id']
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', item_id) or item_id in seen:
            raise ValueError(f'无效或重复的 id: {item_id}')
        seen.add(item_id)
        for field in ('title', 'category', 'source'):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f'{item_id}: 缺少 {field}')
        path = (manifest_path.parent / entry['file']).resolve()
        content = path.read_bytes()
        if not content or len(content) > 20 * 1024 * 1024:
            raise ValueError(f'{path.name}: 单张图片须小于 20 MB')
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP') or getattr(image, 'n_frames', 1) != 1:
                raise ValueError(f'{path.name}: 仅支持静态 PNG/JPEG/WebP')
            if image.width * image.height > 24_000_000:
                raise ValueError(f'{path.name}: 超过 2400 万像素')
            image = ImageOps.exif_transpose(image)
            image.load()
            prepared.append((entry, path, hashlib.sha256(content).hexdigest()))
    # Check all collisions before writing files or changing catalogue visibility.
    with store.db() as con:
        for entry, path, digest in prepared:
            row = con.execute('SELECT asset_id FROM inspiration_items WHERE id=?', (entry['id'],)).fetchone()
            if row:
                existing = store.asset(row['asset_id'], user_id=None)
                if (existing.get('origin') or {}).get('source_sha256') != digest:
                    raise ValueError(f"{entry['id']}: 已有不同图片，请使用新的 id")
    backup = config.DATA / f'inspiration-before-import-{time.time_ns()}.sqlite'
    with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    assets = []
    for entry, path, digest in prepared:
        with store.db() as con:
            existing = con.execute('SELECT asset_id FROM inspiration_items WHERE id=?', (entry['id'],)).fetchone()
        if existing:
            asset = store.asset(existing['asset_id'], user_id=None)
        else:
            origin = dict(source=entry['source'], source_sha256=digest,
                          prompt=entry.get('prompt', ''), tags=entry.get('tags', []))
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image)
                asset = store.persist_image(image, path.stem + '.png', 'inspiration', origin, user_id=None)
        assets.append((entry, asset))
    with store.db() as con:
        store._add_column(con, 'inspiration_items', "description TEXT NOT NULL DEFAULT ''")
        store._add_column(con, 'inspiration_items', "source TEXT NOT NULL DEFAULT ''")
        store._add_column(con, 'inspiration_items', "source_url TEXT NOT NULL DEFAULT ''")
        con.execute('CREATE TABLE IF NOT EXISTS inspiration_categories(name TEXT PRIMARY KEY COLLATE NOCASE)')
        for index, (entry, asset) in enumerate(assets):
            con.execute('INSERT OR IGNORE INTO inspiration_categories(name) VALUES(?)', (entry['category'],))
            con.execute('''INSERT INTO inspiration_items
                (id,title,category,asset_id,width,height,created,published) VALUES(?,?,?,?,?,?,?,1)
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,category=excluded.category''',
                (entry['id'], entry['title'], entry['category'], asset['id'], asset['width'],
                 asset['height'], time.time() - index))
            con.execute('UPDATE inspiration_items SET description=?,source=?,source_url=? WHERE id=?',
                        (entry.get('description', ''), entry['source'], entry.get('source_url', ''), entry['id']))
        if hide_demo:
            for seed in inspiration.SEEDS:
                row = con.execute('SELECT asset_id FROM inspiration_items WHERE id=?', (seed[0],)).fetchone()
                if row:
                    asset = store.asset(row['asset_id'], user_id=None)
                    if asset['name'] == f'inspiration-{seed[0]}.png' and not asset.get('origin'):
                        con.execute('UPDATE inspiration_items SET published=0 WHERE id=?', (seed[0],))
    return {'imported': len(assets), 'backup': str(backup), 'data_dir': str(config.DATA)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--hide-demo', action='store_true', help='隐藏原始渐变占位图，保留记录及文件')
    args = parser.parse_args()
    print(json.dumps(import_manifest(args.manifest, args.data_dir, args.hide_demo), ensure_ascii=False))
