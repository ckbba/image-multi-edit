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

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import config
import store
import segmentation
import provider
import recognition
import text_recognition
import drive
import auth
import inspiration
import inspiration_admin

worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='image-jobs')
login_attempts = {}
mail_attempts = {}
verification_attempts = {}


@asynccontextmanager
async def lifespan(app):
    if config.MODE not in ('live', 'simulation'):
        raise RuntimeError('GENERATION_MODE must be live or simulation')
    store.init()
    drive.init()
    auth.bootstrap_legacy(config.PASSWORD)
    inspiration.init()
    with store.db() as con:
        pending = con.execute("SELECT id,status FROM jobs WHERE status IN ('queued','saving')").fetchall()
    for item in pending:
        worker.submit(provider.execute if item['status'] == 'queued' else provider.save_outputs, item['id'])
    yield
    segmentation.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(inspiration_admin.router)


@app.middleware('http')
async def disable_job_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/jobs'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.middleware('http')
async def security(request, call_next):
    path = request.url.path
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '跨站请求被拒绝'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '跨站请求被拒绝'}, status_code=403)
    public = (path in ('/api/login', '/api/register', '/api/verify-email', '/api/verify-email-code', '/api/resend-verification',
                       '/api/request-password-reset', '/api/reset-password', '/api/health', '/api/me') or path == '/api/inspiration'
              or (request.method in ('GET', 'HEAD') and path.startswith('/api/inspiration/') and path.endswith('/image')))
    user = auth.session_user(request.cookies.get('editor_session', ''))
    request.state.user = user
    if path.startswith('/api/') and not public and not user:
        return JSONResponse({'detail': '请先登录账号'}, status_code=401)
    context_token = store.CURRENT_USER_ID.set(user['id'] if user else None)
    try:
        response = await call_next(request)
    finally:
        store.CURRENT_USER_ID.reset(context_token)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'" if path.startswith('/api/drive/files/') else "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
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
    try:
        user = (auth.authenticate(data.get('email'), data.get('password')) if data.get('email')
                else auth.authenticate_legacy(data.get('password')))
    except HTTPException:
        login_attempts[ip] = attempts + [time.time()]
        raise
    token = auth.create_session(user['id'])
    response = JSONResponse({'ok': True, 'user': user})
    response.set_cookie('editor_session', token, httponly=True, secure=os.getenv('COOKIE_SECURE') == 'true', samesite='lax', max_age=auth.SESSION_SECONDS)
    return response


@app.post('/api/register')
async def register(request: Request):
    data = await request.json()
    if config.EMAIL_VERIFICATION_REQUIRED and not config.mail_ready():
        raise HTTPException(503, '邮箱验证服务尚未配置，暂时无法注册')
    if config.EMAIL_VERIFICATION_REQUIRED:
        check_mail_rate_limit(request, 'register', data.get('email'))
        user = auth.begin_registration(data.get('email'), data.get('password'))
        try:
            await run_in_threadpool(auth.send_verification_code, user['id'], user['email'])
        except Exception:
            raise HTTPException(502, '验证码邮件发送失败，请稍后重试')
        return JSONResponse({'ok': True, 'pending_verification': True, 'email': user['email']}, status_code=202)
    user = auth.create_user(data.get('email'), data.get('password'))
    token = auth.create_session(user['id'])
    response = JSONResponse({'ok': True, 'user': user}, status_code=201)
    response.set_cookie('editor_session', token, httponly=True, secure=os.getenv('COOKIE_SECURE') == 'true', samesite='lax', max_age=auth.SESSION_SECONDS)
    return response


def check_mail_rate_limit(request, action, email):
    key = (request.client.host, action, str(email or '').strip().lower())
    now = time.time()
    previous = mail_attempts.get(key, 0)
    if now - previous < 60:
        raise HTTPException(429, '请等一分钟后再试')
    mail_attempts[key] = now


@app.post('/api/resend-verification')
async def resend_verification(request: Request):
    data = await request.json()
    check_mail_rate_limit(request, 'verify', data.get('email'))
    if config.EMAIL_VERIFICATION_REQUIRED and config.mail_ready():
        await run_in_threadpool(auth.resend_verification, data.get('email'))
    return {'ok': True, 'message': '如果该邮箱存在且未验证，新邮件已发送'}


@app.post('/api/verify-email')
async def verify_email(request: Request):
    user = auth.verify_email((await request.json()).get('token'))
    token = auth.create_session(user['id'])
    response = JSONResponse({'ok': True, 'user': user})
    response.set_cookie('editor_session', token, httponly=True, secure=os.getenv('COOKIE_SECURE') == 'true', samesite='lax', max_age=auth.SESSION_SECONDS)
    return response


@app.post('/api/verify-email-code')
async def verify_email_code(request: Request):
    data = await request.json()
    key = (request.client.host, str(data.get('email') or '').strip().lower())
    now = time.time()
    attempts = [item for item in verification_attempts.get(key, []) if now - item < 600]
    if len(attempts) >= 5:
        raise HTTPException(429, '验证码错误次数过多，请 10 分钟后重试')
    try:
        user = auth.verify_email_code(data.get('email'), data.get('code'))
    except HTTPException:
        verification_attempts[key] = attempts + [now]
        raise
    verification_attempts.pop(key, None)
    token = auth.create_session(user['id'])
    response = JSONResponse({'ok': True, 'user': user})
    response.set_cookie('editor_session', token, httponly=True, secure=os.getenv('COOKIE_SECURE') == 'true', samesite='lax', max_age=auth.SESSION_SECONDS)
    return response


@app.post('/api/request-password-reset')
async def request_password_reset(request: Request):
    data = await request.json()
    check_mail_rate_limit(request, 'reset', data.get('email'))
    if config.mail_ready():
        await run_in_threadpool(auth.request_password_reset, data.get('email'))
    return {'ok': True, 'message': '如果该邮箱已注册，重置邮件已发送'}


@app.post('/api/reset-password')
async def reset_password(request: Request):
    data = await request.json()
    auth.reset_password(data.get('token'), data.get('password'))
    return {'ok': True}


@app.post('/api/logout')
def logout(request: Request):
    auth.delete_session(request.cookies.get('editor_session', ''))
    response = JSONResponse({'ok': True}); response.delete_cookie('editor_session'); return response


@app.get('/api/config')
def settings(request: Request):
    return {'mode': config.MODE, 'model': config.MODEL or 'Image2.5 尚未配置', 'segmentation': segmentation.available(),
            'generation_ready': config.MODE == 'live' and bool(config.KEY and config.MODEL and config.EXPERIMENTAL),
            'source_strategy': config.SOURCE_STRATEGY, 'cost': '按渠道实际用量结算；接口未公开可靠单价',
            'limits': {'references': 12, 'mappings': 20, 'model_references': 12, 'megabytes': 20}, 'mask_mode': '原生 Mask 未验证，当前使用选区文字约束',
            'object_recognition': bool(config.GEMINI_KEY and segmentation.available()), 'recognition_model': config.GEMINI_MODEL,
            'text_recognition': text_recognition.available(), 'text_recognition_engine': 'RapidOCR（本机）',
            'user': request.state.user}


@app.get('/api/me')
def me(request: Request):
    return {'user': request.state.user}


@app.get('/api/inspiration')
def inspiration_list(request: Request, category: str = 'all'):
    user = getattr(request.state, 'user', None)
    return inspiration.list_items(user['id'] if user else None, category)


@app.get('/api/inspiration/{item_id}/image')
def inspiration_image(item_id: str, thumbnail: bool = False):
    with store.db() as con:
        row = con.execute('SELECT asset_id FROM inspiration_items WHERE id=? AND published=1', (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, '灵感作品不存在')
    data = store.asset(row['asset_id'])
    path = config.DATA / data['path']
    if thumbnail:
        thumb = path.with_suffix('.thumb.png')
        if thumb.is_file():
            path = thumb
    return FileResponse(path, media_type='image/png')


@app.put('/api/inspiration/{item_id}/like')
async def inspiration_like(item_id: str, request: Request):
    return inspiration.set_like(request.state.user['id'], item_id, (await request.json()).get('liked'))


@app.put('/api/inspiration/{item_id}/favorite')
async def inspiration_favorite(item_id: str, request: Request):
    return inspiration.set_favorite(request.state.user['id'], item_id, bool((await request.json()).get('favorite')))


@app.post('/api/inspiration/{item_id}/drive')
def inspiration_drive(item_id: str, request: Request):
    return inspiration.copy_to_drive(request.state.user['id'], item_id)


@app.post('/api/inspiration/{item_id}/workspace')
def inspiration_workspace(item_id: str, request: Request):
    return inspiration.add_to_workspace(request.state.user['id'], item_id)


@app.get('/api/drive/items')
def drive_items(request: Request, parent_id: str | None = None, sort: str = 'updated', direction: str = 'desc'):
    return drive.list_items(parent_id, sort, direction, request.state.user['id'])


@app.get('/api/drive/breadcrumbs')
def drive_breadcrumbs(request: Request, item_id: str | None = None):
    return drive.breadcrumbs(item_id, request.state.user['id'])


@app.get('/api/drive/search')
def drive_search(request: Request, q: str = ''):
    return drive.search(q, request.state.user['id'])


@app.get('/api/drive/storage')
def drive_storage(request: Request):
    return drive.storage(request.state.user['id'])


@app.post('/api/drive/folders')
async def drive_create_folder(request: Request):
    body = await request.json()
    return drive.create_folder(body.get('name'), body.get('parent_id'), request.state.user['id'])


@app.post('/api/drive/files')
async def drive_upload(request: Request, file: UploadFile = File(...), parent_id: str = Form('')):
    limit = getattr(config, 'DRIVE_MAX_FILE_BYTES', drive.DEFAULT_MAX_FILE_BYTES)
    content = await file.read(limit + 1)
    return await run_in_threadpool(drive.create_file, file.filename, content, file.content_type, parent_id or None, request.state.user['id'])


@app.get('/api/drive/files/{item_id}')
def drive_download(item_id: str, request: Request, inline: bool = False):
    path, mime, name = drive.file_info(item_id, request.state.user['id'])
    inline = inline and mime in {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif'}
    return FileResponse(path, media_type=mime, filename=None if inline else name,
                        content_disposition_type='inline' if inline else 'attachment',
                        headers={'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "sandbox; default-src 'none'"})


@app.post('/api/drive/import-references')
async def drive_import_references(request: Request):
    body = await request.json()
    result = await run_in_threadpool(drive.import_references, body.get('ids'), request.state.user['id'])
    if body.get('pre_recognition'):
        for item in result['succeeded']:
            recognition.start(item['asset']['id'])
    return JSONResponse(result, status_code=207 if result['failed'] else 200)


@app.patch('/api/drive/items/{item_id}')
async def drive_update(item_id: str, request: Request):
    return drive.update(item_id, await request.json(), request.state.user['id'])


def _drive_result(result):
    return JSONResponse(result, status_code=207 if result['failed'] else 200)


@app.post('/api/drive/move')
async def drive_move(request: Request):
    body = await request.json()
    return _drive_result(drive.move(body.get('ids') or [], body.get('parent_id'), request.state.user['id']))


@app.post('/api/drive/trash')
async def drive_trash(request: Request):
    return _drive_result(drive.trash((await request.json()).get('ids') or [], request.state.user['id']))


@app.get('/api/drive/trash')
def drive_trash_items(request: Request):
    return drive.list_trash(request.state.user['id'])


@app.post('/api/drive/restore')
async def drive_restore(request: Request):
    return _drive_result(drive.restore((await request.json()).get('ids') or [], request.state.user['id']))


@app.post('/api/drive/delete-permanent')
async def drive_delete_permanent(request: Request):
    return _drive_result(drive.delete_permanent((await request.json()).get('ids') or [], request.state.user['id']))


@app.post('/api/assets')
async def upload(request: Request, file: UploadFile = File(...), pre_recognition: bool = False):
    content = await file.read(20 * 1024 * 1024 + 1)
    asset = await run_in_threadpool(store.ingest, content, file.filename or 'image', 'image', request.state.user['id'])
    if pre_recognition:
        user_id = request.state.user['id']
        def begin():
            token = store.CURRENT_USER_ID.set(user_id)
            try:
                return recognition.start(asset['id'])
            finally:
                store.CURRENT_USER_ID.reset(token)
        await run_in_threadpool(begin)
    return asset


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
    hit = await run_in_threadpool(segmentation.cached_hit, data['image_id'], data['x'], data['y'])
    if hit and not data.get('force_sam'):
        return {'candidates': [store.asset(hit['mask_id'])], 'elapsed_ms': 0, 'cached': True,
                'recognition_cached': True, 'label': hit['label']}
    return await run_in_threadpool(segmentation.select, data['image_id'], data['x'], data['y'])


@app.get('/api/recognition/{aid}')
def recognition_status(aid: str):
    store.asset(aid)
    return recognition.status(aid)


@app.post('/api/recognition/{aid}/start')
def start_recognition(aid: str):
    store.asset(aid)
    return recognition.start(aid)


@app.post('/api/recognition/{aid}/cancel')
def cancel_recognition(aid: str):
    store.asset(aid)
    return recognition.cancel(aid)


@app.post('/api/text-recognition/{aid}')
async def recognize_text(aid: str):
    store.asset(aid)
    return await run_in_threadpool(text_recognition.recognize, aid)


@app.post('/api/masks')
async def mask(request: Request):
    data = await request.json()
    return await run_in_threadpool(store.manual_mask, data['image_id'], data['points'])


@app.post('/api/reference-preview')
async def reference_preview(request: Request):
    data = await request.json()
    mapping = data.get('mapping')
    if not isinstance(mapping, dict):
        raise HTTPException(400, '缺少操作快照')
    # Validate asset provenance without saving a draft, creating an asset, running
    # recognition/segmentation, or creating a generation job.
    source = mapping.get('source')
    target = mapping.get('target') or {}
    if source:
        image_meta = store.asset(source.get('image_id'))
        mask_meta = store.asset(source.get('mask_id'))
        if image_meta['kind'] not in ('image', 'output') or mask_meta['kind'] != 'mask' or mask_meta['origin']['image_id'] != source['image_id']:
            raise HTTPException(400, '源选区与素材不匹配')
    else:
        store.asset(target.get('image_id'))
    strategy = data.get('strategy', 'context-crop')
    if strategy not in ('full', 'context-crop', 'transparent', 'scale-aligned'):
        raise HTTPException(400, '不支持的参考图策略')
    content, _, kind, focus = await run_in_threadpool(provider.reference_input_bytes, mapping, strategy)
    return Response(content, media_type='image/png', headers={
        'X-Reference-Preview-Kind': kind, 'X-Subject-Focus': focus,
        'Cache-Control': 'private, max-age=60'})


@app.post('/api/validate')
async def validate(request: Request):
    return {'conflicts': await run_in_threadpool(store.validate, await request.json())}


@app.post('/api/drafts')
def create_draft(request: Request):
    return store.new_draft(user_id=request.state.user['id'])


@app.get('/api/drafts/latest')
def latest_draft(request: Request):
    with store.db() as con:
        row = con.execute('SELECT state FROM drafts WHERE user_id=? ORDER BY updated DESC LIMIT 1', (request.state.user['id'],)).fetchone()
    return store.normalize_draft_state(json.loads(row['state'])) if row else store.new_draft(user_id=request.state.user['id'])


@app.get('/api/drafts/{did}')
def get_draft(did: str, request: Request):
    with store.db() as con:
        row = con.execute('SELECT state FROM drafts WHERE id=? AND user_id=?', (did, request.state.user['id'])).fetchone()
    if not row:
        raise HTTPException(404, '草稿不存在')
    return store.normalize_draft_state(json.loads(row['state']))


@app.put('/api/drafts/{did}')
async def save_draft(did: str, request: Request):
    state = await request.json()
    if state.get('id') != did:
        raise HTTPException(400, '草稿标识不一致')
    conflicts = await run_in_threadpool(store.validate, state)
    with store.db() as con:
        current = con.execute('SELECT revision FROM drafts WHERE id=? AND user_id=?', (did, request.state.user['id'])).fetchone()
        if not current:
            raise HTTPException(404, '草稿不存在')
        if state['revision'] != current['revision']:
            raise HTTPException(409, '草稿已在其他页面更新，请刷新后继续，未覆盖服务器版本')
        state['revision'] += 1
        updated = con.execute('UPDATE drafts SET revision=?,updated=?,state=? WHERE id=? AND revision=? AND user_id=?',
                             (state['revision'], time.time(), json.dumps(state), did, current['revision'], request.state.user['id']))
        if updated.rowcount != 1:
            raise HTTPException(409, '并发保存冲突')
    return {'revision': state['revision'], 'conflicts': conflicts}


@app.post('/api/jobs')
async def submit(request: Request):
    data = await request.json()
    idem = data.get('idempotency_key', '')
    if not 10 <= len(idem) <= 160:
        raise HTTPException(400, '缺少有效提交标识')
    state = get_draft(data['draft_id'], request)
    selected_model = state.get('generation_model', store.DEFAULT_GENERATION_MODEL)
    if selected_model not in store.GENERATION_MODELS:
        raise HTTPException(400, '请选择受支持的生成模型')
    idem_scope = store.user_idempotency_scope(request.state.user['id'], idem, config.MODE, selected_model, provider.COMPILER_VERSION)
    with store.db() as con:
        previous = con.execute('SELECT id FROM jobs WHERE idem=? AND user_id=?', (idem_scope, request.state.user['id'])).fetchone()
        legacy = con.execute('SELECT id,snapshot FROM jobs WHERE idem=? AND user_id=?', (idem, request.state.user['id'])).fetchone() if not previous else None
    if legacy:
        old = json.loads(legacy['snapshot'])
        old_compiler = old.get('compiled', {}).get('compiler_version')
        old_model = store.normalize_generation_model(old.get('model'))
        if old.get('mode') == config.MODE and old_model == selected_model and old_compiler == provider.COMPILER_VERSION:
            previous = legacy
    if previous:
        return public_job(store.job(previous['id'], True, request.state.user['id']))
    if state['revision'] != data['revision']:
        raise HTTPException(409, '请先保存当前草稿')
    overlaps = await run_in_threadpool(store.validate, state, True, data.get('allow_overlap') is True)
    if config.MODE == 'live':
        if not config.EXPERIMENTAL:
            raise HTTPException(409, '真实生成尚未通过能力门禁；需明确开启实验性接入')
        await run_in_threadpool(provider.preflight, selected_model)
    compiled = await run_in_threadpool(provider.compile_request, state)
    snapshot = {'state': state, 'compiled': compiled, 'mode': config.MODE, 'model': selected_model,
                'created': time.time(), 'mask_processing': {'dilation': 0, 'feather': 0},
                'overlap_confirmation': {'accepted': bool(overlaps), 'conflicts': overlaps}}
    jid = store.uid()
    with store.db() as con:
        try:
            con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,user_id) VALUES(?,?,?,?,?,?)',
                        (jid, idem_scope, time.time(), 'queued', json.dumps(snapshot), request.state.user['id']))
        except sqlite3.IntegrityError:
            jid = con.execute('SELECT id FROM jobs WHERE idem=? AND user_id=?', (idem_scope, request.state.user['id'])).fetchone()['id']
            return public_job(store.job(jid, True, request.state.user['id']))
    worker.submit(provider.execute, jid)
    return public_job(store.job(jid, user_id=request.state.user['id']))


def public_job(data):
    # Signed upstream URLs/base64 are server recovery data, not browser history dependencies.
    result = data['result'].copy()
    result.pop('outputs', None)
    original_name = data['snapshot']['state']['name']
    return {**data, 'name': data.get('display_name') or original_name, 'result': result}


@app.get('/api/jobs')
def history(request: Request, status: str = 'all', offset: int = 0, q: str = ''):
    offset = max(0, offset)
    keyword = q.strip()
    with store.db() as con:
        where = ['deleted=0', 'user_id=?']
        params = [request.state.user['id']]
        if status != 'all':
            where.append('status=?'); params.append(status)
        if keyword:
            escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where.append("COALESCE(display_name, json_extract(snapshot, '$.state.name')) LIKE ? ESCAPE '\\'")
            params.append(f'%{escaped}%')
        clause = ' AND '.join(where)
        count = con.execute(f'SELECT COUNT(*) FROM jobs WHERE {clause}', params).fetchone()[0]
        rows = con.execute(f'SELECT id FROM jobs WHERE {clause} ORDER BY created DESC, id DESC LIMIT 20 OFFSET ?', [*params, offset]).fetchall()
    result = []
    for row in rows:
        item = public_job(store.job(row['id'], user_id=request.state.user['id']))
        state = item['snapshot']['state']
        result.append({k: item[k] for k in ('id', 'created', 'status', 'result', 'name')} | {'main_image': state['main_image'], 'count': len(state.get('mappings', [])) + len(state.get('text_edits', [])) + len(state.get('full_image_refs', []))})
    next_offset = offset + len(result) if offset + len(result) < count else None
    return {'items': result, 'count': count, 'next_offset': next_offset}


@app.patch('/api/jobs/{jid}')
async def rename_history(jid: str, request: Request):
    job = store.job(jid, user_id=request.state.user['id'])
    body = await request.json()
    if set(body) != {'name'} or not isinstance(body.get('name'), str):
        raise HTTPException(400, '请提供历史名称')
    name = body['name'].strip()
    if not name or len(name) > 100:
        raise HTTPException(400, '历史名称需为 1 到 100 个字符')
    with store.db() as con:
        con.execute('UPDATE jobs SET display_name=? WHERE id=? AND user_id=? AND deleted=0', (name, jid, request.state.user['id']))
    return public_job(store.job(jid, user_id=request.state.user['id']))


@app.get('/api/jobs/{jid}')
def detail(jid: str, request: Request):
    return public_job(store.job(jid, user_id=request.state.user['id']))


@app.delete('/api/jobs/{jid}')
def delete_history(jid: str, request: Request):
    job = store.job(jid, user_id=request.state.user['id'])
    if job['status'] in ('queued', 'running', 'saving'):
        raise HTTPException(409, '任务执行中，完成后才能删除历史；删除不会取消生成')
    with store.db() as con:
        con.execute('UPDATE jobs SET deleted=1 WHERE id=? AND user_id=?', (jid, request.state.user['id']))
    return {'ok': True}


@app.post('/api/jobs/{jid}/restore')
async def restore(jid: str, request: Request):
    job = store.job(jid, user_id=request.state.user['id'])
    body = await request.json()
    state = json.loads(json.dumps(job['snapshot']['state']))
    state['origin_history_id'] = jid
    restored_model = store.normalize_generation_model(job['snapshot'].get('model'))
    state['generation_model'] = restored_model if restored_model in store.GENERATION_MODELS else store.DEFAULT_GENERATION_MODEL
    state['source_strategy'] = job['snapshot'].get('compiled', {}).get('strategy', 'full')
    state['name'] += ' · 恢复'
    if body.get('use_result'):
        aid = body.get('asset_id')
        if aid not in job['result'].get('assets', []):
            raise HTTPException(400, '该输出不存在')
        state['main_image'] = aid
        state['mappings'] = []
        state['text_edits'] = []
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
    return store.new_draft(state, user_id=request.state.user['id'])


@app.post('/api/jobs/{jid}/retry-save')
def retry_save(jid: str, request: Request):
    job = store.job(jid, user_id=request.state.user['id'])
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
