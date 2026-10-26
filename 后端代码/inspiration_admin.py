"""Administrator-only inspiration publishing and recoverable deletion."""
import sqlite3
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

import config
import store


def require_admin(request: Request):
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(401, '请先登录账号')
    if user.get('role') != 'admin':
        raise HTTPException(403, '仅管理员可以管理灵感库')
    return user


router = APIRouter(prefix='/api/admin/inspiration', dependencies=[Depends(require_admin)])


class Metadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=40)
    description: str = Field(default='', max_length=3000)
    source: str = Field(default='', max_length=200)
    source_url: str = Field(default='', max_length=2000)
    published: StrictBool = False


class Category(BaseModel):
    name: str = Field(min_length=1, max_length=40)


def clean(value, label):
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value):
        raise HTTPException(400, f'{label}不能为空或包含控制字符')
    if label == '分类' and any(char in value for char in '/\\'):
        raise HTTPException(400, '分类名称不能包含斜杠')
    return value


def fields(meta):
    data = meta.model_dump()
    data['title'] = clean(data['title'], '标题')
    data['category'] = clean(data['category'], '分类')
    data['source_url'] = data['source_url'].strip()
    if data['source_url']:
        try:
            url = urlsplit(data['source_url'])
        except ValueError:
            raise HTTPException(400, '来源链接须为有效的 http/https 地址')
        if url.scheme not in ('http', 'https') or not url.netloc or url.username or url.password:
            raise HTTPException(400, '来源链接须为有效的 http/https 地址')
    return data


def category_exists(con, name):
    row = con.execute('SELECT name FROM inspiration_categories WHERE name=?', (name,)).fetchone()
    if not row:
        raise HTTPException(400, '请先创建或选择已有分类')
    return row['name']


def item(con, item_id):
    row = con.execute('SELECT * FROM inspiration_items WHERE id=?', (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, '图片不存在')
    return row


@router.get('')
def listing():
    with store.db() as con:
        rows = con.execute('''SELECT i.*,
            (SELECT COUNT(*) FROM inspiration_likes l WHERE l.item_id=i.id) like_count
            FROM inspiration_items i ORDER BY i.created DESC,i.id''').fetchall()
        categories = con.execute('''SELECT c.name,COUNT(i.id) item_count FROM inspiration_categories c
            LEFT JOIN inspiration_items i ON i.category=c.name GROUP BY c.name ORDER BY c.name''').fetchall()
    return {'items': [dict(row) for row in rows], 'categories': [dict(row) for row in categories]}


@router.get('/items/{item_id}/image')
def preview(item_id: str):
    with store.db() as con:
        row = item(con, item_id)
    asset = store.asset(row['asset_id'], user_id=None)
    path = config.DATA / asset['path']
    thumb = path.with_suffix('.thumb.png')
    return FileResponse(thumb if thumb.is_file() else path, media_type='image/png')


def upload(content, filename, meta, user_id):
    data = fields(meta)
    with store.db() as con:
        data['category'] = category_exists(con, data['category'])
    asset = store.ingest(content, filename, kind='inspiration', user_id=user_id)
    item_id = store.uid()
    with store.db() as con:
        data['category'] = category_exists(con, data['category'])
        con.execute('''INSERT INTO inspiration_items
            (id,title,category,asset_id,width,height,created,published,description,source,source_url)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (item_id,data['title'],data['category'],asset['id'],asset['width'],asset['height'],time.time(),
             data['published'],data['description'],data['source'],data['source_url']))
    return {'id': item_id}


@router.post('/items', status_code=201)
async def create(request: Request, file: UploadFile = File(...), title: str = Form(...),
                 category: str = Form(...), description: str = Form(''), source: str = Form(''),
                 source_url: str = Form(''), published: bool = Form(False)):
    try:
        meta = Metadata(title=title,category=category,description=description,source=source,
                        source_url=source_url,published=published)
    except ValueError:
        raise HTTPException(400, '标题、分类或简介长度不符合要求')
    content = await file.read(20 * 1024 * 1024 + 1)
    return await run_in_threadpool(upload, content, file.filename or 'upload.png', meta, request.state.user['id'])


@router.put('/items/{item_id}')
def update(item_id: str, meta: Metadata):
    data = fields(meta)
    with store.db() as con:
        row = item(con, item_id)
        if row['deleted_at'] is not None:
            raise HTTPException(409, '请先从回收站恢复图片')
        data['category'] = category_exists(con, data['category'])
        con.execute('''UPDATE inspiration_items SET title=?,category=?,description=?,source=?,source_url=?,published=?
                       WHERE id=?''', (data['title'],data['category'],data['description'],data['source'],
                                      data['source_url'],data['published'],item_id))
    return {'id': item_id}


@router.delete('/items/{item_id}')
def trash(item_id: str):
    with store.db() as con:
        item(con, item_id)
        con.execute('UPDATE inspiration_items SET published=0,deleted_at=COALESCE(deleted_at,?) WHERE id=?',
                    (time.time(),item_id))
    return {'id':item_id}


@router.post('/items/{item_id}/restore')
def restore(item_id: str):
    with store.db() as con:
        item(con, item_id)
        con.execute('UPDATE inspiration_items SET deleted_at=NULL,published=0 WHERE id=? AND deleted_at IS NOT NULL', (item_id,))
    return {'id':item_id}


@router.post('/categories', status_code=201)
def create_category(body: Category):
    name = clean(body.name, '分类')
    try:
        with store.db() as con:
            con.execute('INSERT INTO inspiration_categories(name) VALUES(?)', (name,))
    except sqlite3.IntegrityError:
        raise HTTPException(409, '分类已存在')
    return {'name':name}


@router.put('/categories/{name}')
def rename_category(name: str, body: Category):
    new_name = clean(body.name, '分类')
    try:
        with store.db() as con:
            old_name = category_exists(con, name)
            con.execute('UPDATE inspiration_categories SET name=? WHERE name=?', (new_name,old_name))
            con.execute('UPDATE inspiration_items SET category=? WHERE category=?', (new_name,old_name))
    except sqlite3.IntegrityError:
        raise HTTPException(409, '分类已存在，请使用其他名称')
    return {'name':new_name}


@router.delete('/categories/{name}')
def delete_category(name: str):
    with store.db() as con:
        name = category_exists(con, name)
        if con.execute('SELECT 1 FROM inspiration_items WHERE category=?', (name,)).fetchone():
            raise HTTPException(409, '分类中仍有图片（含下架和回收站），请先修改图片分类')
        con.execute('DELETE FROM inspiration_categories WHERE name=?', (name,))
    return {'name':name}
