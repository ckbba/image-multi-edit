import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import config
import store
import segmentation
import provider

worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='image-jobs')
login_attempts = {}


@asynccontextmanager
async def lifespan(app):
    if config.MODE not in ('live', 'simulation'):
        raise RuntimeError('GENERATION_MODE must be live or simulation')
    if len(config.PASSWORD) < 6:
        raise RuntimeError('请在 .env 配置至少 6 字符 SITE_PASSWORD')
    store.init()
    with store.db() as con:
        pending = con.execute("SELECT id,status FROM jobs WHERE status IN ('queued','saving')").fetchall()
    for item in pending:
        worker.submit(provider.execute if item['status'] == 'queued' else provider.save_outputs, item['id'])
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def security(request, call_next):
    path = request.url.path
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '跨站请求被拒绝'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '跨站请求被拒绝'}, status_code=403)
    if path.startswith('/api/') and path not in ('/api/login', '/api/health'):
        token = request.cookies.get('editor_session', '')
        with store.db() as con:
            row = con.execute('SELECT expires FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row['expires'] < time.time():
            return JSONResponse({'detail': '请登录私有编辑空间'}, status_code=401)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(KeyError)
async def invalid_state(request, exc):
    return JSONResponse({'detail': '编辑数据字段缺失，请恢复已保存草稿'}, status_code=400)


@app.get('/api/health')
def health():
    return {'ok': True}


@app.post('/api/login')
async def login(request: Request):
    data = await request.json()
    ip = request.client.host
    attempts = [t for t in login_attempts.get(ip, []) if time.time() - t < 60]
    if len(attempts) >= 10:
        raise HTTPException(429, '尝试过于频繁，请一分钟后重试')
    if not secrets.compare_digest(str(data.get('password', '')), config.PASSWORD):
        login_attempts[ip] = attempts + [time.time()]
        raise HTTPException(401, '密码不正确')
    token = secrets.token_urlsafe(32)
    with store.db() as con:
        con.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        con.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time() + 30 * 86400))
    response = JSONResponse({'ok': True})
    response.set_cookie('editor_session', token, httponly=True, secure=os.getenv('COOKIE_SECURE') == 'true', samesite='strict', max_age=30 * 86400)
    return response


@app.post('/api/logout')
def logout(request: Request):
    with store.db() as con:
        con.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.cookies.get('editor_session', '').encode()).hexdigest(),))
    response = JSONResponse({'ok': True}); response.delete_cookie('editor_session'); return response


@app.get('/api/config')
def settings():
    return {'mode': config.MODE, 'model': config.MODEL or 'Image2.5 尚未配置', 'segmentation': segmentation.available(),
            'generation_ready': config.MODE == 'live' and bool(config.KEY and config.MODEL and config.EXPERIMENTAL),
            'source_strategy': config.SOURCE_STRATEGY, 'cost': '按渠道实际用量结算；接口未公开可靠单价',
            'limits': {'references': 12, 'mappings': 20, 'model_references': 12, 'megabytes': 20}, 'mask_mode': '原生 Mask 未验证，当前使用选区文字约束'}


@app.post('/api/assets')
async def upload(file: UploadFile = File(...)):
    content = await file.read(20 * 1024 * 1024 + 1)
    return await run_in_threadpool(store.ingest, content, file.filename or 'image')


@app.get('/api/assets/{aid}/meta')
def meta(aid: str):
    data = store.asset(aid).copy(); data.pop('path'); return data


@app.get('/api/assets/{aid}')
def asset_file(aid: str, thumbnail: bool = False, download: bool = False):
    data = store.asset(aid)
    path = config.DATA / (f'assets/{aid}.thumb.png' if thumbnail else data['path'])
    return FileResponse(path, media_type='image/png', filename=f'image-edit-{aid[:8]}.png' if download else None)


@app.post('/api/segmentation/prepare')
async def prepare(request: Request):
    data = await request.json()
    return await run_in_threadpool(segmentation.prepare, data['image_id'])


@app.post('/api/segmentation/select')
async def select(request: Request):
    data = await request.json()
    if not all(isinstance(data.get(k), (int, float)) and 0 <= data[k] <= 1 for k in ('x', 'y')):
        raise HTTPException(400, '选区点在图像外')
    return await run_in_threadpool(segmentation.select, data['image_id'], data['x'], data['y'])


@app.post('/api/masks')
async def mask(request: Request):
    data = await request.json()
    return await run_in_threadpool(store.manual_mask, data['image_id'], data['points'])


@app.post('/api/validate')
async def validate(request: Request):
    return {'conflicts': await run_in_threadpool(store.validate, await request.json())}


@app.post('/api/drafts')
def create_draft():
    return store.new_draft()


@app.get('/api/drafts/latest')
def latest_draft():
    with store.db() as con:
        row = con.execute('SELECT state FROM drafts ORDER BY updated DESC LIMIT 1').fetchone()
    return json.loads(row['state']) if row else store.new_draft()


@app.get('/api/drafts/{did}')
def get_draft(did: str):
    with store.db() as con:
        row = con.execute('SELECT state FROM drafts WHERE id=?', (did,)).fetchone()
    if not row:
        raise HTTPException(404, '草稿不存在')
    return json.loads(row['state'])


@app.put('/api/drafts/{did}')
async def save_draft(did: str, request: Request):
    state = await request.json()
    if state.get('id') != did:
        raise HTTPException(400, '草稿标识不一致')
    conflicts = await run_in_threadpool(store.validate, state)
    with store.db() as con:
        current = con.execute('SELECT revision FROM drafts WHERE id=?', (did,)).fetchone()
        if not current:
            raise HTTPException(404, '草稿不存在')
        if state['revision'] != current['revision']:
            raise HTTPException(409, '草稿已在其他页面更新，请刷新后继续，未覆盖服务器版本')
        state['revision'] += 1
        updated = con.execute('UPDATE drafts SET revision=?,updated=?,state=? WHERE id=? AND revision=?',
                             (state['revision'], time.time(), json.dumps(state), did, current['revision']))
        if updated.rowcount != 1:
            raise HTTPException(409, '并发保存冲突')
    return {'revision': state['revision'], 'conflicts': conflicts}


@app.post('/api/jobs')
async def submit(request: Request):
    data = await request.json()
    idem = data.get('idempotency_key', '')
    if not 10 <= len(idem) <= 160:
        raise HTTPException(400, '缺少有效提交标识')
    with store.db() as con:
        previous = con.execute('SELECT id FROM jobs WHERE idem=?', (idem,)).fetchone()
    if previous:
        return public_job(store.job(previous['id'], True))
    state = get_draft(data['draft_id'])
    if state['revision'] != data['revision']:
        raise HTTPException(409, '请先保存当前草稿')
    overlaps = await run_in_threadpool(store.validate, state, True, data.get('allow_overlap') is True)
    if config.MODE == 'live':
        if state.get('generation_model') and state['generation_model'] != config.MODEL:
            raise HTTPException(409, '历史模型与当前配置不同；请在服务端核对原模型，禁止静默换模型生成')
        if not config.EXPERIMENTAL:
            raise HTTPException(409, '真实生成尚未通过能力门禁；需明确开启实验性接入')
        await run_in_threadpool(provider.preflight)
    compiled = await run_in_threadpool(provider.compile_request, state)
    snapshot = {'state': state, 'compiled': compiled, 'mode': config.MODE, 'model': config.MODEL,
                'created': time.time(), 'mask_processing': {'dilation': 0, 'feather': 0},
                'overlap_confirmation': {'accepted': bool(overlaps), 'conflicts': overlaps}}
    jid = store.uid()
    with store.db() as con:
        try:
            con.execute('INSERT INTO jobs(id,idem,created,status,snapshot) VALUES(?,?,?,?,?)',
                        (jid, idem, time.time(), 'queued', json.dumps(snapshot)))
        except sqlite3.IntegrityError:
            jid = con.execute('SELECT id FROM jobs WHERE idem=?', (idem,)).fetchone()['id']
            return public_job(store.job(jid, True))
    worker.submit(provider.execute, jid)
    return public_job(store.job(jid))


def public_job(data):
    # Signed upstream URLs/base64 are server recovery data, not browser history dependencies.
    result = data['result'].copy()
    result.pop('outputs', None)
    return {**data, 'result': result}


@app.get('/api/jobs')
def history(status: str = 'all', offset: int = 0):
    offset = max(0, offset)
    with store.db() as con:
        query = 'SELECT id FROM jobs WHERE deleted=0'
        params = []
        if status != 'all':
            query += ' AND status=?'; params.append(status)
        query += ' ORDER BY created DESC LIMIT 20 OFFSET ?'; params.append(offset)
        rows = con.execute(query, params).fetchall()
    result = []
    for row in rows:
        item = public_job(store.job(row['id']))
        state = item['snapshot']['state']
        result.append({k: item[k] for k in ('id', 'created', 'status', 'result')} | {'name': state['name'], 'main_image': state['main_image'], 'count': len(state.get('mappings', [])) + len(state.get('full_image_refs', []))})
    return {'items': result, 'next_offset': offset + 20 if len(result) == 20 else None}


@app.get('/api/jobs/{jid}')
def detail(jid: str):
    return public_job(store.job(jid))


@app.delete('/api/jobs/{jid}')
def delete_history(jid: str):
    store.job(jid)
    with store.db() as con:
        con.execute('UPDATE jobs SET deleted=1 WHERE id=?', (jid,))
    return {'ok': True}


@app.post('/api/jobs/{jid}/restore')
async def restore(jid: str, request: Request):
    job = store.job(jid)
    body = await request.json()
    state = json.loads(json.dumps(job['snapshot']['state']))
    state['origin_history_id'] = jid
    state['generation_model'] = job['snapshot'].get('model')
    state['source_strategy'] = job['snapshot'].get('compiled', {}).get('strategy', 'full')
    state['name'] += ' · 恢复'
    if body.get('use_result'):
        aid = body.get('asset_id')
        if aid not in job['result'].get('assets', []):
            raise HTTPException(400, '该输出不存在')
        state['main_image'] = aid
        state['mappings'] = []
        state['references'] = []
        state['full_image_refs'] = []
        state['instructions'] = ''
        state['next_display_index'] = 1
        state['origin_result_id'] = aid
        state['name'] = job['snapshot']['state']['name'] + ' · 下一轮'
    elif job['snapshot'].get('research_case'):
        # Early serial research kept geometry on the previous, same-sized input.
        # Rebind immutable copies in the NEW draft only; never amend old snapshots.
        for mapping in state['mappings']:
            target = mapping['target']
            if target['image_id'] != state['main_image']:
                before, after = store.asset(target['image_id']), store.asset(state['main_image'])
                if (before['width'], before['height']) != (after['width'], after['height']):
                    raise HTTPException(409, '实验输入尺寸发生变化，需重新确认目标选区')
                for field in ('mask_id', 'edit_region_id'):
                    if field in target:
                        previous = target[field]
                        target[field] = store.mask_asset(store.image(previous).getchannel('A'),
                            state['main_image'], 'research-version-binding', {'original_mask_id': previous})['id']
                target['image_id'] = state['main_image']
                state['restoration_notice'] = '串行实验沿用的选区已复制到当时输入版本；请检查目标对齐后再生成。'
        if job['snapshot']['research_case'].startswith('mask-'):
            state['restoration_notice'] = '已恢复原始选区。原生 Mask 实验未通过能力验证，本次草稿不启用实验膨胀或羽化参数。'
    await run_in_threadpool(store.validate, state)
    return store.new_draft(state)


@app.post('/api/jobs/{jid}/retry-save')
def retry_save(jid: str):
    job = store.job(jid)
    if job['status'] != 'save_failed':
        raise HTTPException(409, '仅保存异常任务可重试保存')
    store.update_job(jid, 'saving', job['result'])
    worker.submit(provider.save_outputs, jid)
    return {'ok': True}


app.mount('/static', StaticFiles(directory=config.ROOT / '前端代码'), name='static')


@app.get('/{path:path}')
def frontend(path: str):
    if path.startswith('api/'):
        raise HTTPException(404, '接口不存在')
    return FileResponse(config.ROOT / '前端代码' / 'index.html')
