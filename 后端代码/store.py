"""One-owner durable SQLite metadata and immutable image bytes."""
import hashlib
import io
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageDraw
from fastapi import HTTPException
import config

Image.MAX_IMAGE_PIXELS = 40_000_000


def uid():
    return uuid.uuid4().hex


def idempotency_scope(user_key, mode, model, compiler_version):
    """Separate simulation/live/compiler semantics without rewriting old rows."""
    payload = json.dumps({'key': user_key, 'mode': mode, 'model': model or '',
                          'compiler': compiler_version}, sort_keys=True, separators=(',', ':'))
    return 'v2:' + hashlib.sha256(payload.encode()).hexdigest()


def init():
    config.DATA.mkdir(parents=True, exist_ok=True)
    (config.DATA / 'assets').mkdir(exist_ok=True)
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, meta TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, updated REAL NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, created REAL NOT NULL,
          status TEXT NOT NULL, snapshot TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, expires REAL NOT NULL);
        ''')
        con.execute("UPDATE jobs SET status='unknown', result=json_set(result,'$.error','服务重启中断请求；上游状态未知，不自动重复扣费。') WHERE status='running'")


@contextmanager
def db():
    con = sqlite3.connect(config.DATA / 'editor.sqlite', timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=FULL')
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def asset(asset_id):
    with db() as con:
        row = con.execute('SELECT meta FROM assets WHERE id=?', (asset_id,)).fetchone()
    if not row:
        raise HTTPException(404, '素材不存在或已损坏')
    meta = json.loads(row['meta'])
    if not (config.DATA / meta['path']).is_file():
        raise HTTPException(409, '素材文件缺失，不能继续使用旧选区')
    return meta


def image(asset_id):
    return Image.open(config.DATA / asset(asset_id)['path'])


def persist_image(im, name, kind='image', origin=None):
    """Every asset is a new immutable version. PNG normalization removes EXIF location data."""
    im.load()
    im = im.convert('RGBA' if im.mode == 'RGBA' else 'RGB')
    buf = io.BytesIO()
    im.save(buf, format='PNG', compress_level=1 if kind == 'mask' else 6)
    content = buf.getvalue()
    aid = uid()
    relative = f'assets/{aid}.png'
    destination = config.DATA / relative
    temporary = destination.with_suffix('.tmp')
    temporary.write_bytes(content)
    temporary.replace(destination)
    thumb = im.copy()
    thumb.thumbnail((360, 360))
    thumb.save(config.DATA / f'assets/{aid}.thumb.png')
    meta = dict(id=aid, version=1, width=im.width, height=im.height, name=name[:160],
                mime='image/png', path=relative, kind=kind, origin=origin, created=time.time(),
                sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
    with db() as con:
        con.execute('INSERT INTO assets VALUES(?,?)', (aid, json.dumps(meta)))
    return meta


def ingest(content, name, kind='image'):
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, '单张图片必须在 20 MB 以内')
    try:
        im = Image.open(io.BytesIO(content))
        if im.format not in ('JPEG', 'PNG', 'WEBP') or getattr(im, 'n_frames', 1) != 1:
            raise ValueError('只支持静态 JPEG / PNG / WebP')
        if im.width * im.height > 24_000_000:
            raise ValueError('当前处理上限为 2400 万像素，请先缩小图片')
        im = ImageOps.exif_transpose(im)
        im.load()
    except Exception as exc:
        raise HTTPException(400, '图片无效、动画或超过像素上限') from exc
    return persist_image(im, name, kind)


def mask_asset(mask, image_id, method, extra=None):
    original = asset(image_id)
    mask = mask.convert('L').resize((original['width'], original['height']), Image.Resampling.NEAREST)
    if not mask.getbbox():
        raise HTTPException(400, '选区为空，请重新选择')
    rgba = Image.new('RGBA', mask.size, (255, 255, 255, 0))
    rgba.putalpha(mask)
    meta = persist_image(rgba, 'selection.png', 'mask', dict(image_id=image_id, image_version=1, method=method, **(extra or {})))
    bbox = mask.getbbox()
    meta['bbox'] = [bbox[0] / mask.width, bbox[1] / mask.height, bbox[2] / mask.width, bbox[3] / mask.height]
    with db() as con:
        con.execute('UPDATE assets SET meta=? WHERE id=?', (json.dumps(meta), meta['id']))
    return meta


def manual_mask(image_id, points):
    im = asset(image_id)
    if not 3 <= len(points) <= 500 or any(len(p) != 2 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in p) for p in points):
        raise HTTPException(400, '圈选至少需要三个有效点')
    mask = Image.new('L', (im['width'], im['height']))
    ImageDraw.Draw(mask).polygon([(round(x * (im['width'] - 1)), round(y * (im['height'] - 1))) for x, y in points], fill=255)
    return mask_asset(mask, image_id, 'manual-polygon', {'points': points})


COLORS = ['#8b5cf6', '#3b82f6', '#f59e0b', '#10b981', '#ec4899']
REFERENCE_UPLOAD_LIMIT = 12
MAPPING_DRAFT_LIMIT = 20
MODEL_REFERENCE_LIMIT = 12
GENERATION_MODELS = ('gpt-image-2.5-flare', 'gpt-image-2.5-sunburst')
DEFAULT_GENERATION_MODEL = GENERATION_MODELS[0]


def validate(state, for_submit=False, allow_overlap=False):
    mappings = state.get('mappings', [])
    refs = state.get('references', [])
    whole_refs = state.get('full_image_refs', [])
    text_edits = state.get('text_edits', [])
    if len(refs) > REFERENCE_UPLOAD_LIMIT or len(set(refs)) != len(refs):
        raise HTTPException(400, '最多 12 张参考图，且不能重复添加同一素材')
    if len(mappings) > MAPPING_DRAFT_LIMIT:
        raise HTTPException(400, '最多 20 条元素草稿')
    if len(state.get('instructions', '')) > 2000 or len(state.get('name', '')) > 100:
        raise HTTPException(400, '项目名或补充要求过长')
    if state.get('source_strategy', 'full') not in ('full', 'context-crop', 'transparent'):
        raise HTTPException(400, '请选择完整参考图或带上下文裁剪')
    if state.get('generation_model', DEFAULT_GENERATION_MODEL) not in GENERATION_MODELS:
        raise HTTPException(400, '请选择受支持的生成模型')
    main = state.get('main_image')
    for aid in ([main] if main else []) + refs:
        if asset(aid)['kind'] not in ('image', 'output'):
            raise HTTPException(400, '主图和参考图必须是图像素材')
    whole_ids = set()
    for reference in whole_refs:
        if reference.get('id') in whole_ids or reference.get('image_id') not in refs:
            raise HTTPException(400, '整图引用重复或指向失效素材')
        whole_ids.add(reference.get('id'))
        if len(reference.get('label', '')) > 80 or len(reference.get('purpose', '')) > 1000:
            raise HTTPException(400, '整图引用名称或用途过长')
    text_ids = set()
    for edit in text_edits:
        bbox = edit.get('bbox')
        polygon = edit.get('polygon', [])
        if (not edit.get('id') or edit['id'] in text_ids or edit.get('image_id') != main or edit.get('image_version') != 1
                or edit.get('source') not in ('ocr', 'user') or not str(edit.get('original_text', '')).strip()
                or not str(edit.get('replacement', '')).strip() or len(edit.get('original_text', '')) > 200
                or len(edit.get('replacement', '')) > 200 or not isinstance(bbox, list) or len(bbox) != 4
                or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in bbox)
                or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]
                or polygon and not (3 <= len(polygon) <= 12 and all(isinstance(p, list) and len(p) == 2
                    and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in p) for p in polygon))):
            raise HTTPException(400, '改字草稿无效、过长或不属于当前主图')
        text_ids.add(edit['id'])
    ids, numbers = set(), set()
    masks = []
    for mapping in mappings:
        number = mapping['display_index']
        if mapping['id'] in ids or number in numbers or not isinstance(number, int) or number < 1:
            raise HTTPException(400, '关系 ID 和编号必须唯一且稳定')
        ids.add(mapping['id']); numbers.add(number)
        if mapping.get('color') != COLORS[(number - 1) % 5]:
            raise HTTPException(400, '关系编号与颜色不一致')
        kind = mapping.get('kind', 'reference-edit')
        source = mapping.get('source')
        if kind not in ('reference-edit', 'main-edit') or (kind == 'main-edit') != (source is None):
            raise HTTPException(400, '编辑类型与来源不匹配')
        if source and len(source.get('label', '')) > 10:
            raise HTTPException(400, '物品名称最多 10 字')
        if len(mapping.get('requirement', '')) > 1000:
            raise HTTPException(400, '单条操作要求最多 1000 字')
        for side in (('target',) if kind == 'main-edit' else ('source', 'target')):
            data = mapping[side]
            expected = refs if side == 'source' else [main]
            if data.get('image_id') not in expected or data.get('image_version') != 1:
                raise HTTPException(400, '关系指向失效的素材版本')
            for mask_id in set([data['mask_id'], data.get('edit_region_id', data['mask_id'])]):
                ma = asset(mask_id)
                if ma['kind'] != 'mask' or ma['origin']['image_id'] != data['image_id']:
                    raise HTTPException(400, '选区与素材版本不匹配')
            anchor = data.get('anchor', {})
            if not all(isinstance(anchor.get(k), (int, float)) and 0 <= anchor[k] <= 1 for k in ('x', 'y')):
                raise HTTPException(400, '锚点必须在图像内')
            mask = image(data['mask_id']).getchannel('A')
            if mask.getpixel((min(mask.width - 1, int(anchor['x'] * mask.width)), min(mask.height - 1, int(anchor['y'] * mask.height)))) == 0:
                raise HTTPException(400, '锚点不在确认选区内，请重新选择或拖拽')
        target = image(mapping['target'].get('edit_region_id', mapping['target']['mask_id'])).getchannel('A')
        # Native resolution, not bbox intersection: touching polygon boxes is not a conflict.
        masks.append((number, np.asarray(target) > 0))
    conflicts = []
    for i, (a, ma) in enumerate(masks):
        for b, mb in masks[i + 1:]:
            ratio = float(np.count_nonzero(ma & mb) / max(1, min(np.count_nonzero(ma), np.count_nonzero(mb))))
            if ratio > 0.05:
                conflicts.append({'a': a, 'b': b, 'overlap': round(ratio, 4), 'duplicate': ratio > 0.85})
    if state.get('next_display_index', 1) <= max(numbers, default=0):
        raise HTTPException(400, '下个编号必须大于已分配编号')
    if for_submit and (not main or (not mappings and not whole_refs and not text_edits)):
        raise HTTPException(400, '请准备主图和至少一条有效编辑关系、改字或整图引用')
    actual_references = len(mappings) + len(whole_refs)
    if for_submit and actual_references > MODEL_REFERENCE_LIMIT:
        raise HTTPException(400, f'当前共 {actual_references} 个实际参考输入，最多 12 个；请删除部分元素操作或整图引用后再生成')
    if for_submit and not mappings and whole_refs and not (state.get('instructions', '').strip() or any(r.get('purpose', '').strip() for r in whole_refs)):
        raise HTTPException(400, '仅整图引用时请填写明确要求')
    if for_submit and conflicts and not allow_overlap:
        raise HTTPException(409, {'code': 'target_overlap_confirmation_required',
            'message': '目标选区存在重叠，确认可能影响效果后仍可生成', 'conflicts': conflicts})
    return conflicts


def new_draft(state=None):
    state = json.loads(json.dumps(state)) if state else dict(schema_version=3, name='未命名编辑', main_image=None,
        references=[], mappings=[], text_edits=[], full_image_refs=[], next_display_index=1, instructions='', source_strategy='context-crop')
    state['id'] = uid()
    state['project_id'] = state.get('project_id', uid())
    state['revision'] = 0
    state['schema_version'] = 3
    state.setdefault('references', [])
    state.setdefault('full_image_refs', [])
    state.setdefault('text_edits', [])
    state.setdefault('instructions', '')
    state.setdefault('source_strategy', 'context-crop')
    state.setdefault('generation_model', DEFAULT_GENERATION_MODEL)
    state.setdefault('next_display_index', max([m['display_index'] for m in state.get('mappings', [])], default=0) + 1)
    with db() as con:
        con.execute('INSERT INTO drafts VALUES(?,?,?,?)', (state['id'], 0, time.time(), json.dumps(state)))
    return state


def job(jid, include_deleted=False):
    with db() as con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
    if not row or (row['deleted'] and not include_deleted):
        raise HTTPException(404, '历史不存在')
    result = dict(row)
    result['snapshot'] = json.loads(row['snapshot'])
    result['result'] = json.loads(row['result'])
    return result


def update_job(jid, status, result):
    with db() as con:
        con.execute('UPDATE jobs SET status=?,result=? WHERE id=?', (status, json.dumps(result), jid))
