"""Persistent private drive metadata and bytes, separate from editor assets."""
import mimetypes
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
import config
import store

RETENTION_SECONDS = 30 * 86400
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
SORT_COLUMNS = {'name': 'name COLLATE NOCASE', 'updated': 'updated', 'created': 'created', 'size': 'size'}


def init():
    (config.DATA / 'drive_files').mkdir(parents=True, exist_ok=True)
    with store.db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS drive_items(
          id TEXT PRIMARY KEY, parent_id TEXT, kind TEXT NOT NULL CHECK(kind IN ('file','folder')),
          name TEXT NOT NULL, mime TEXT, size INTEGER, storage_name TEXT,
          created REAL NOT NULL, updated REAL NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
          trashed_at REAL, purge_at REAL, original_parent_id TEXT,
          FOREIGN KEY(parent_id) REFERENCES drive_items(id));
        CREATE INDEX IF NOT EXISTS drive_parent_idx ON drive_items(parent_id, trashed_at);
        CREATE INDEX IF NOT EXISTS drive_name_idx ON drive_items(name);
        ''')
    purge_expired()


def _clean_name(name, *, upload=False):
    value = str(name or '').strip()
    if upload:
        value = re.split(r'[\\/]+', value)[-1].strip()
    if (not value or value in ('.', '..') or '/' in value or '\\' in value or '\x00' in value
            or len(value) > 180 or any(ord(c) < 32 for c in value)):
        raise HTTPException(400, '名称无效；不能包含路径、控制字符或超过 180 字符')
    return value


def _row(row):
    if not row:
        return None
    data = dict(row)
    data['favorite'] = bool(data['favorite'])
    data.pop('storage_name', None)
    return data


def _get(con, item_id, include_trashed=False):
    row = con.execute('SELECT * FROM drive_items WHERE id=?', (item_id,)).fetchone()
    if not row or (row['trashed_at'] is not None and not include_trashed):
        raise HTTPException(404, '云盘项目不存在')
    return row


def _parent(con, parent_id):
    if not parent_id:
        return None
    row = _get(con, parent_id)
    if row['kind'] != 'folder':
        raise HTTPException(400, '目标位置不是文件夹')
    return row


def _ensure_unique(con, parent_id, name, exclude=None):
    row = con.execute('SELECT id FROM drive_items WHERE parent_id IS ? AND name=? COLLATE NOCASE AND trashed_at IS NULL AND id IS NOT ?',
                      (parent_id, name, exclude)).fetchone()
    if row:
        raise HTTPException(409, f'当前位置已存在“{name}”')


def create_folder(name, parent_id=None):
    name = _clean_name(name)
    now = time.time(); item_id = uuid.uuid4().hex
    with store.db() as con:
        _parent(con, parent_id); _ensure_unique(con, parent_id, name)
        con.execute('INSERT INTO drive_items(id,parent_id,kind,name,created,updated) VALUES(?,?,?,?,?,?)',
                    (item_id, parent_id, 'folder', name, now, now))
        row = con.execute('SELECT * FROM drive_items WHERE id=?', (item_id,)).fetchone()
    return _row(row)


def create_file(name, content, mime, parent_id=None):
    name = _clean_name(name, upload=True)
    limit = getattr(config, 'DRIVE_MAX_FILE_BYTES', DEFAULT_MAX_FILE_BYTES)
    if not content:
        raise HTTPException(400, '文件为空')
    if len(content) > limit:
        raise HTTPException(413, f'单个文件不能超过 {limit // 1024 // 1024} MB')
    now = time.time(); item_id = uuid.uuid4().hex; storage_name = item_id + '.bin'
    path = config.DATA / 'drive_files' / storage_name
    with store.db() as con:
        _parent(con, parent_id); _ensure_unique(con, parent_id, name)
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(content); temporary.replace(path)
        try:
            con.execute('''INSERT INTO drive_items(id,parent_id,kind,name,mime,size,storage_name,created,updated)
                           VALUES(?,?,?,?,?,?,?,?,?)''',
                        (item_id, parent_id, 'file', name, (mime or mimetypes.guess_type(name)[0] or 'application/octet-stream')[:120], len(content), storage_name, now, now))
            row = con.execute('SELECT * FROM drive_items WHERE id=?', (item_id,)).fetchone()
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    return _row(row)


def list_items(parent_id=None, sort='updated', direction='desc'):
    if sort not in SORT_COLUMNS or direction not in ('asc', 'desc'):
        raise HTTPException(400, '排序参数无效')
    purge_expired()
    with store.db() as con:
        _parent(con, parent_id)
        rows = con.execute(f'''SELECT * FROM drive_items WHERE parent_id IS ? AND trashed_at IS NULL
                              ORDER BY kind='folder' DESC, {SORT_COLUMNS[sort]} {direction.upper()}, id ASC''', (parent_id,)).fetchall()
    return {'items': [_row(row) for row in rows]}


def breadcrumbs(item_id=None):
    crumbs = [{'id': None, 'name': '所有文件'}]
    if not item_id:
        return {'items': crumbs}
    with store.db() as con:
        current = _get(con, item_id); chain = []
        seen = set()
        while current:
            if current['id'] in seen:
                raise HTTPException(409, '文件夹层级损坏')
            seen.add(current['id']); chain.append({'id': current['id'], 'name': current['name']})
            current = con.execute('SELECT * FROM drive_items WHERE id=? AND trashed_at IS NULL', (current['parent_id'],)).fetchone() if current['parent_id'] else None
    return {'items': crumbs + list(reversed(chain))}


def _path(con, row):
    names = []; parent_id = row['parent_id']; seen = set()
    while parent_id:
        if parent_id in seen: break
        seen.add(parent_id)
        parent = con.execute('SELECT id,parent_id,name FROM drive_items WHERE id=?', (parent_id,)).fetchone()
        if not parent: break
        names.append(parent['name']); parent_id = parent['parent_id']
    return '/' + '/'.join(reversed(names))


def search(query):
    query = str(query or '').strip()
    if not query:
        return {'items': []}
    escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    with store.db() as con:
        rows = con.execute("SELECT * FROM drive_items WHERE trashed_at IS NULL AND name LIKE ? ESCAPE '\\' ORDER BY updated DESC LIMIT 50", (f'%{escaped}%',)).fetchall()
        return {'items': [{**_row(row), 'path': _path(con, row)} for row in rows]}


def update(item_id, changes):
    allowed = {'name', 'favorite'}
    if not changes or set(changes) - allowed:
        raise HTTPException(400, '仅支持重命名或收藏')
    with store.db() as con:
        row = _get(con, item_id)
        name = _clean_name(changes.get('name', row['name']))
        favorite = int(bool(changes.get('favorite', row['favorite'])))
        _ensure_unique(con, row['parent_id'], name, item_id)
        con.execute('UPDATE drive_items SET name=?,favorite=?,updated=? WHERE id=?', (name, favorite, time.time(), item_id))
        result = con.execute('SELECT * FROM drive_items WHERE id=?', (item_id,)).fetchone()
    return _row(result)


def _descendant_ids(con, item_id):
    return [row[0] for row in con.execute('''WITH RECURSIVE tree(id) AS (
      SELECT id FROM drive_items WHERE id=? UNION ALL
      SELECT d.id FROM drive_items d JOIN tree t ON d.parent_id=t.id)
      SELECT id FROM tree''', (item_id,)).fetchall()]


def move(ids, parent_id):
    succeeded, failed = [], []
    with store.db() as con:
        target = _parent(con, parent_id)
        for item_id in dict.fromkeys(ids):
            try:
                row = _get(con, item_id)
                if parent_id == item_id or (row['kind'] == 'folder' and parent_id in _descendant_ids(con, item_id)):
                    raise HTTPException(409, '不能将文件夹移动到自身或子文件夹')
                _ensure_unique(con, parent_id, row['name'], item_id)
                con.execute('UPDATE drive_items SET parent_id=?,updated=? WHERE id=?', (parent_id, time.time(), item_id))
                succeeded.append(item_id)
            except HTTPException as exc:
                failed.append({'id': item_id, 'error': exc.detail})
    return {'succeeded': succeeded, 'failed': failed}


def trash(ids):
    now = time.time(); succeeded, failed = [], []
    with store.db() as con:
        for item_id in dict.fromkeys(ids):
            try:
                row = _get(con, item_id)
                subtree = _descendant_ids(con, item_id)
                placeholders = ','.join('?' * len(subtree))
                con.execute(f'''UPDATE drive_items SET original_parent_id=CASE WHEN id=? THEN parent_id ELSE original_parent_id END,
                    trashed_at=?,purge_at=? WHERE id IN ({placeholders})''', (item_id, now, now + RETENTION_SECONDS, *subtree))
                succeeded.append(item_id)
            except HTTPException as exc:
                failed.append({'id': item_id, 'error': exc.detail})
    return {'succeeded': succeeded, 'failed': failed}


def list_trash():
    purge_expired()
    with store.db() as con:
        rows = con.execute('''SELECT d.* FROM drive_items d
          LEFT JOIN drive_items p ON p.id=d.parent_id
          WHERE d.trashed_at IS NOT NULL AND (p.id IS NULL OR p.trashed_at IS NULL)
          ORDER BY d.trashed_at DESC''').fetchall()
    return {'items': [_row(row) for row in rows]}


def restore(ids):
    succeeded, failed = [], []
    with store.db() as con:
        for item_id in dict.fromkeys(ids):
            try:
                row = _get(con, item_id, True)
                if row['trashed_at'] is None: raise HTTPException(409, '项目不在回收站')
                parent_id = row['original_parent_id']
                parent = con.execute('SELECT * FROM drive_items WHERE id=? AND trashed_at IS NULL', (parent_id,)).fetchone() if parent_id else None
                destination = parent_id if parent else None
                _ensure_unique(con, destination, row['name'], item_id)
                subtree = _descendant_ids(con, item_id); placeholders = ','.join('?' * len(subtree))
                con.execute(f'UPDATE drive_items SET trashed_at=NULL,purge_at=NULL WHERE id IN ({placeholders})', subtree)
                con.execute('UPDATE drive_items SET parent_id=?,original_parent_id=NULL,updated=? WHERE id=?', (destination, time.time(), item_id))
                succeeded.append(item_id)
            except HTTPException as exc:
                failed.append({'id': item_id, 'error': exc.detail})
    return {'succeeded': succeeded, 'failed': failed}


def delete_permanent(ids):
    succeeded, failed, paths = [], [], []
    with store.db() as con:
        for item_id in dict.fromkeys(ids):
            try:
                row = _get(con, item_id, True)
                if row['trashed_at'] is None: raise HTTPException(409, '只能永久删除回收站项目')
                subtree = _descendant_ids(con, item_id); placeholders = ','.join('?' * len(subtree))
                paths.extend(config.DATA / 'drive_files' / r['storage_name'] for r in con.execute(f'SELECT storage_name FROM drive_items WHERE id IN ({placeholders}) AND storage_name IS NOT NULL', subtree))
                con.execute(f'DELETE FROM drive_items WHERE id IN ({placeholders})', subtree)
                succeeded.append(item_id)
            except HTTPException as exc:
                failed.append({'id': item_id, 'error': exc.detail})
    for path in paths: path.unlink(missing_ok=True)
    return {'succeeded': succeeded, 'failed': failed}


def purge_expired():
    now = time.time()
    with store.db() as con:
        roots = [row['id'] for row in con.execute('''SELECT d.id FROM drive_items d LEFT JOIN drive_items p ON p.id=d.parent_id
          WHERE d.purge_at IS NOT NULL AND d.purge_at<=? AND (p.id IS NULL OR p.trashed_at IS NULL)''', (now,)).fetchall()]
    if roots:
        delete_permanent(roots)


def storage():
    purge_expired()
    with store.db() as con:
        used = con.execute("SELECT COALESCE(SUM(size),0) FROM drive_items WHERE kind='file'").fetchone()[0]
    return {'used_bytes': used, 'file_count': None}


def file_info(item_id):
    with store.db() as con:
        row = _get(con, item_id)
        if row['kind'] != 'file': raise HTTPException(400, '文件夹不能下载')
        path = config.DATA / 'drive_files' / row['storage_name']
        if not path.is_file(): raise HTTPException(404, '文件内容不存在')
        return path, row['mime'] or 'application/octet-stream', _clean_name(row['name'])


def import_references(ids):
    """Copy drive images into immutable editor assets; never link lifecycles."""
    if not isinstance(ids, list) or not ids or len(ids) > store.REFERENCE_UPLOAD_LIMIT:
        raise HTTPException(400, '请选择 1 至 12 张云盘图片')
    if len(set(ids)) != len(ids) or any(not isinstance(item_id, str) or not item_id for item_id in ids):
        raise HTTPException(400, '云盘图片选择无效或重复')
    succeeded, failed = [], []
    for item_id in ids:
        try:
            path, mime, name = file_info(item_id)
            if mime not in {'image/jpeg', 'image/png', 'image/webp'}:
                raise HTTPException(400, '仅支持静态 JPEG / PNG / WebP 图片')
            asset = store.ingest(path.read_bytes(), name, 'image')
            succeeded.append({'drive_id': item_id, 'asset': asset})
        except HTTPException as exc:
            failed.append({'drive_id': item_id, 'error': exc.detail})
        except OSError:
            failed.append({'drive_id': item_id, 'error': '读取云盘文件失败'})
    return {'succeeded': succeeded, 'failed': failed}
