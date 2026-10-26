"""Email/password accounts and server-side sessions."""
import hashlib
import hmac
import re
import secrets
import time

from fastapi import HTTPException

import store


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PBKDF2_ITERATIONS = 310_000
SESSION_SECONDS = 30 * 86400
LEGACY_USER_ID = "legacy-owner"


def normalize_email(value):
    email = str(value or "").strip().lower()
    if len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise HTTPException(400, "请输入有效邮箱")
    return email


def validate_password(value):
    password = str(value or "")
    if len(password) < 8 or len(password) > 128:
        raise HTTPException(400, "密码需为 8 至 128 个字符")
    return password


def _password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _password_matches(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (TypeError, ValueError):
        return False


def create_user(email, password):
    email = normalize_email(email)
    password = validate_password(password)
    user_id = store.uid()
    now = time.time()
    with store.db() as con:
        if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "该邮箱已注册，请直接登录")
        con.execute("INSERT INTO users(id,email,password_hash,created) VALUES(?,?,?,?)",
                    (user_id, email, _password_hash(password), now))
    return {"id": user_id, "email": email, "role": "user"}


def authenticate(email, password):
    email = str(email or '').strip().lower()
    if email != 'admin':
        email = normalize_email(email)
    with store.db() as con:
        row = con.execute("SELECT id,email,password_hash,role FROM users WHERE email=?", (email,)).fetchone()
    if not row or (email == 'admin' and row['role'] != 'admin') or not _password_matches(str(password or ""), row["password_hash"]):
        raise HTTPException(401, "邮箱或密码不正确")
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with store.db() as con:
        con.execute("DELETE FROM sessions WHERE expires<?", (now,))
        con.execute("INSERT INTO sessions(token,expires,user_id) VALUES(?,?,?)",
                    (hashlib.sha256(token.encode()).hexdigest(), now + SESSION_SECONDS, user_id))
    return token


def session_user(token):
    if not token:
        return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    with store.db() as con:
        row = con.execute("""SELECT u.id,u.email,u.role FROM sessions s JOIN users u ON u.id=s.user_id
                           WHERE s.token=? AND s.expires>=?""", (digest, time.time())).fetchone()
    return dict(row) if row else None


def delete_session(token):
    with store.db() as con:
        con.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256((token or "").encode()).hexdigest(),))


def bootstrap_legacy(password):
    """Keep the former single-owner space available while assigning all old rows."""
    if not password:
        return
    email = "legacy@local.invalid"
    with store.db() as con:
        if not con.execute("SELECT 1 FROM users WHERE id=?", (LEGACY_USER_ID,)).fetchone():
            con.execute("INSERT INTO users(id,email,password_hash,created) VALUES(?,?,?,?)",
                        (LEGACY_USER_ID, email, _password_hash(password), time.time()))
        for table in ("drafts", "jobs", "drive_items"):
            exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if exists:
                con.execute(f"UPDATE {table} SET user_id=? WHERE user_id IS NULL", (LEGACY_USER_ID,))
        con.execute("""UPDATE assets SET user_id=? WHERE user_id IS NULL
                       AND COALESCE(json_extract(meta,'$.kind'),'')!='inspiration'""", (LEGACY_USER_ID,))


def authenticate_legacy(password):
    with store.db() as con:
        row = con.execute("SELECT id,email,password_hash,role FROM users WHERE id=?", (LEGACY_USER_ID,)).fetchone()
    if not row or not _password_matches(str(password or ""), row["password_hash"]):
        raise HTTPException(401, "密码不正确")
    return {"id": row["id"], "email": row["email"], "role": row["role"]}
