"""Public inspiration catalogue plus per-account favorites."""
import hashlib
import io
import math
import time

from fastapi import HTTPException
from PIL import Image, ImageDraw

import config
import drive
import store


SEEDS = [
    ("editorial", "野生花束的夏日画报", "杂志风", "#ffc46b", "#ef6351", 4, 5),
    ("product", "透明瓶的光影实验", "商品摄影", "#a8e6cf", "#3c91e6", 3, 4),
    ("fashion", "红色绒布与金属首饰", "时尚视觉", "#8e294c", "#f7c948", 4, 5),
    ("type", "新怪谈字体海报", "字体排版", "#1b1b1b", "#ff6b35", 1, 1),
    ("food", "柑橘气泡水广告", "食品广告", "#ff9f1c", "#2ec4b6", 3, 4),
    ("space", "银色流体太空站", "3D 概念", "#101935", "#8d99ff", 16, 10),
    ("interior", "柔光客厅色彩练习", "空间设计", "#dbc2a4", "#7a9e7e", 4, 3),
    ("beauty", "浴室水波护肤视觉", "美妆广告", "#bde0fe", "#ffafcc", 4, 5),
    ("poster", "夜色中的红色跑车", "电影海报", "#0b132b", "#e63946", 3, 2),
    ("nature", "苔藓森林中的白色建筑", "建筑概念", "#31572c", "#ecf39e", 4, 5),
    ("packaging", "黑金香水包装系统", "包装设计", "#111111", "#d4af37", 1, 1),
    ("surreal", "粉色沙漠的超现实门", "超现实", "#f4acb7", "#5e60ce", 3, 4),
]


def init():
    with store.db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS inspiration_items(
          id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, asset_id TEXT NOT NULL,
          width INTEGER NOT NULL, height INTEGER NOT NULL, created REAL NOT NULL, published INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS inspiration_favorites(
          user_id TEXT NOT NULL, item_id TEXT NOT NULL, created REAL NOT NULL,
          PRIMARY KEY(user_id,item_id), FOREIGN KEY(user_id) REFERENCES users(id),
          FOREIGN KEY(item_id) REFERENCES inspiration_items(id));
        CREATE TABLE IF NOT EXISTS inspiration_likes(
          user_id TEXT NOT NULL, item_id TEXT NOT NULL, created REAL NOT NULL,
          PRIMARY KEY(user_id,item_id), FOREIGN KEY(user_id) REFERENCES users(id),
          FOREIGN KEY(item_id) REFERENCES inspiration_items(id));
        ''')
        store._add_column(con, 'inspiration_items', "description TEXT NOT NULL DEFAULT ''")
        store._add_column(con, 'inspiration_items', "source TEXT NOT NULL DEFAULT ''")
        store._add_column(con, 'inspiration_items', "source_url TEXT NOT NULL DEFAULT ''")
        store._add_column(con, 'inspiration_items', 'deleted_at REAL')
        con.execute('CREATE TABLE IF NOT EXISTS inspiration_categories(name TEXT PRIMARY KEY COLLATE NOCASE)')
        con.execute('INSERT OR IGNORE INTO inspiration_categories(name) SELECT DISTINCT category FROM inspiration_items')
        count = con.execute("SELECT COUNT(*) FROM inspiration_items").fetchone()[0]
    if count:
        return
    for index, seed in enumerate(SEEDS):
        slug, title, category, start, end, ratio_w, ratio_h = seed
        width = 900
        height = max(620, round(width * ratio_h / ratio_w))
        image = _poster(width, height, start, end, index)
        asset = store.persist_image(image, f"inspiration-{slug}.png", "inspiration")
        with store.db() as con:
            con.execute("""INSERT INTO inspiration_items(id,title,category,asset_id,width,height,created)
                           VALUES(?,?,?,?,?,?,?)""",
                        (slug, title, category, asset["id"], width, height, time.time() - index * 86400))
            con.execute('INSERT OR IGNORE INTO inspiration_categories(name) VALUES(?)', (category,))


def _poster(width, height, start, end, index):
    def rgb(value):
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    first, second = rgb(start), rgb(end)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(round(first[channel] * (1 - t) + second[channel] * t) for channel in range(3))
        draw.line((0, y, width, y), fill=color)
    accent = (255, 255, 255, 215)
    for step in range(6):
        radius = round(width * (.08 + step * .045))
        cx = round(width * (.2 + .13 * math.sin(index + step)))
        cy = round(height * (.2 + step * .12))
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=accent[:3], width=7)
    draw.rounded_rectangle((width * .1, height * .68, width * .9, height * .9), radius=32,
                           fill=(15, 15, 20), outline=(255, 255, 255), width=3)
    draw.text((width * .14, height * .73), f"SHIYING / {index + 1:02d}", fill="white", font=None)
    draw.text((width * .14, height * .82), "VISUAL STUDY", fill=(220, 220, 220), font=None)
    return image


def list_items(user_id=None, category="all"):
    params = []
    where = ["i.published=1"]
    if category != "all":
        where.append("i.category=?")
        params.append(category)
    join = "LEFT JOIN inspiration_favorites f ON f.item_id=i.id AND f.user_id=?" if user_id else ""
    if user_id:
        params = [user_id, *params]
    favorite = "CASE WHEN f.user_id IS NULL THEN 0 ELSE 1 END" if user_id else "0"
    liked = "EXISTS(SELECT 1 FROM inspiration_likes l WHERE l.item_id=i.id AND l.user_id=?)"
    with store.db() as con:
        rows = con.execute(f"""SELECT i.*, {favorite} favorite, {liked} liked,
                              (SELECT COUNT(*) FROM inspiration_likes l WHERE l.item_id=i.id) like_count
                              FROM inspiration_items i {join}
                              WHERE {' AND '.join(where)} ORDER BY i.created DESC,i.id""", [user_id, *params]).fetchall()
        categories = [row[0] for row in con.execute("SELECT DISTINCT category FROM inspiration_items WHERE published=1 ORDER BY category")]
    return {"items": [_public(row) for row in rows], "categories": categories}


def _public(row):
    data = dict(row)
    data["favorite"] = bool(data["favorite"])
    data["liked"] = bool(data["liked"])
    data["like_count"] += _display_likes(data["id"])
    if not data['description']:
        data['description'] = f"{data['title']}。可用于{data['category']}的构图、配色和素材融合参考。"
    return data


def _display_likes(item_id):
    """Stable 0-60 social proof for the public inspiration catalogue."""
    return int.from_bytes(hashlib.sha256(f'shiying-likes:{item_id}'.encode()).digest()[:4], 'big') % 61


def set_like(user_id, item_id, liked):
    if not isinstance(liked, bool):
        raise HTTPException(400, 'liked 必须是布尔值')
    with store.db() as con:
        _item(con, item_id)
        if liked:
            con.execute('INSERT OR IGNORE INTO inspiration_likes(user_id,item_id,created) VALUES(?,?,?)',
                        (user_id, item_id, time.time()))
        else:
            con.execute('DELETE FROM inspiration_likes WHERE user_id=? AND item_id=?', (user_id, item_id))
        count = con.execute('SELECT COUNT(*) FROM inspiration_likes WHERE item_id=?', (item_id,)).fetchone()[0]
    return {'id': item_id, 'liked': liked, 'like_count': count + _display_likes(item_id)}


def _item(con, item_id):
    row = con.execute("SELECT * FROM inspiration_items WHERE id=? AND published=1", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "灵感作品不存在")
    return row


def set_favorite(user_id, item_id, favorite):
    with store.db() as con:
        _item(con, item_id)
        if favorite:
            con.execute("INSERT OR IGNORE INTO inspiration_favorites(user_id,item_id,created) VALUES(?,?,?)",
                        (user_id, item_id, time.time()))
        else:
            con.execute("DELETE FROM inspiration_favorites WHERE user_id=? AND item_id=?", (user_id, item_id))
    return {"id": item_id, "favorite": bool(favorite)}


def copy_to_drive(user_id, item_id):
    with store.db() as con:
        item = _item(con, item_id)
    asset = store.asset(item["asset_id"], user_id=None)
    content = (config.DATA / asset["path"]).read_bytes()
    name = f"{item['title']}.png"
    with store.db() as con:
        existing = con.execute("""SELECT * FROM drive_items WHERE user_id=? AND parent_id IS NULL
                                  AND name=? COLLATE NOCASE AND trashed_at IS NULL""", (user_id, name)).fetchone()
    if existing:
        return drive._row(existing)
    return drive.create_file(name, content, "image/png", user_id=user_id)


def add_to_workspace(user_id, item_id):
    with store.db() as con:
        item = _item(con, item_id)
    source = store.asset(item["asset_id"], user_id=None)
    with store.db() as con:
        row = con.execute("SELECT state FROM drafts WHERE user_id=? ORDER BY updated DESC LIMIT 1", (user_id,)).fetchone()
    if row:
        import json
        existing_state = store.normalize_draft_state(json.loads(row["state"]))
        for reference_id in existing_state.get("references", []):
            try:
                candidate = store.asset(reference_id, user_id)
                if (candidate.get("origin") or {}).get("inspiration_id") == item_id:
                    return {"item_id": item_id, "asset": candidate, "draft": existing_state}
            except HTTPException:
                continue
    image = Image.open(config.DATA / source["path"])
    asset = store.persist_image(image, source["name"], "image", {"inspiration_id": item_id}, user_id=user_id)
    if row:
        state = existing_state
        if asset["id"] not in state["references"]:
            if len(state["references"]) >= store.REFERENCE_UPLOAD_LIMIT:
                raise HTTPException(409, "当前工作区已有 12 张参考图")
            state["references"].append(asset["id"])
            with store.db() as con:
                con.execute("UPDATE drafts SET revision=revision+1,updated=?,state=json_set(?, '$.revision', revision+1) WHERE id=? AND user_id=?",
                            (time.time(), __import__('json').dumps(state), state["id"], user_id))
                state["revision"] += 1
    else:
        state = store.new_draft(user_id=user_id)
        state["references"].append(asset["id"])
        with store.db() as con:
            con.execute("UPDATE drafts SET revision=1,updated=?,state=? WHERE id=? AND user_id=?",
                        (time.time(), __import__('json').dumps({**state, "revision": 1}), state["id"], user_id))
        state["revision"] = 1
    return {"item_id": item_id, "asset": asset, "draft": state}
