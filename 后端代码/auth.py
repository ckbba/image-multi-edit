"""Email/password accounts and server-side sessions."""
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import quote

from fastapi import HTTPException

import store
import config
import mailer


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PBKDF2_ITERATIONS = 310_000
SESSION_SECONDS = 30 * 86400
VERIFY_SECONDS = 10 * 60
RESET_SECONDS = 30 * 60
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


def _public_user(row):
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def create_user(email, password):
    email = normalize_email(email)
    password = validate_password(password)
    user_id = store.uid()
    now = time.time()
    with store.db() as con:
        if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "该邮箱已注册，请直接登录")
        verified = 0 if config.EMAIL_VERIFICATION_REQUIRED else 1
        con.execute("INSERT INTO users(id,email,password_hash,created,email_verified) VALUES(?,?,?,?,?)",
                    (user_id, email, _password_hash(password), now, verified))
        con.execute("INSERT INTO credit_ledger(id,user_id,amount,kind,note,created) VALUES(?,?,?,?,?,?)",
                    (store.uid(), user_id, 100, 'welcome', '新用户注册赠送', now))
    return {"id": user_id, "email": email, "role": "user", "email_verified": bool(verified)}


def begin_registration(email, password):
    """Create, or safely refresh, an account that has not verified its email yet."""
    email = normalize_email(email)
    password = validate_password(password)
    now = time.time()
    with store.db() as con:
        row = con.execute("SELECT id,email_verified FROM users WHERE email=?", (email,)).fetchone()
        if row and row['email_verified']:
            raise HTTPException(409, "该邮箱已注册，请直接登录")
        if row:
            user_id = row['id']
            con.execute("UPDATE users SET password_hash=? WHERE id=?", (_password_hash(password), user_id))
        else:
            user_id = store.uid()
            con.execute("INSERT INTO users(id,email,password_hash,created,email_verified) VALUES(?,?,?,?,0)",
                        (user_id, email, _password_hash(password), now))
            con.execute("INSERT INTO credit_ledger(id,user_id,amount,kind,note,created) VALUES(?,?,?,?,?,?)",
                        (store.uid(), user_id, 100, 'welcome', '新用户注册赠送', now))
    return {"id": user_id, "email": email, "role": "user", "email_verified": False}


def authenticate(email, password):
    email = str(email or '').strip().lower()
    if email != 'admin':
        email = normalize_email(email)
    with store.db() as con:
        row = con.execute("SELECT id,email,password_hash,role,email_verified FROM users WHERE email=?", (email,)).fetchone()
    if not row or (email == 'admin' and row['role'] != 'admin') or not _password_matches(str(password or ""), row["password_hash"]):
        raise HTTPException(401, "邮箱或密码不正确")
    if not row['email_verified']:
        raise HTTPException(403, "请先打开验证邮件完成邮箱验证")
    return _public_user(row)


def _issue_token(user_id, purpose, lifetime, token=None):
    token = token or secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with store.db() as con:
        con.execute("DELETE FROM auth_tokens WHERE expires<? OR (user_id=? AND purpose=?)", (now, user_id, purpose))
        con.execute("INSERT INTO auth_tokens(token_hash,user_id,purpose,expires,created) VALUES(?,?,?,?,?)",
                    (digest, user_id, purpose, now + lifetime, now))
    return token


def _consume_token(token, purpose):
    digest = hashlib.sha256(str(token or '').encode()).hexdigest()
    now = time.time()
    with store.db() as con:
        row = con.execute("SELECT user_id FROM auth_tokens WHERE token_hash=? AND purpose=? AND expires>=?",
                          (digest, purpose, now)).fetchone()
        if not row:
            raise HTTPException(400, "链接无效或已过期，请重新申请")
        con.execute("DELETE FROM auth_tokens WHERE token_hash=?", (digest,))
    return row['user_id']


def send_verification(user_id, email):
    token = _issue_token(user_id, 'verify_email', VERIFY_SECONDS)
    url = f"{config.PUBLIC_BASE_URL}/verify-email?token={quote(token)}"
    mailer.send(email, '验证你的拾影账号', '验证邮箱', '点击下方按钮完成注册，链接 24 小时内有效。', '验证并登录', url)


def send_verification_code(user_id, email):
    code = f'{secrets.randbelow(1_000_000):06d}'
    _issue_token(user_id, 'verify_email_code', VERIFY_SECONDS, code)
    mailer.send_code(email, '拾影注册验证码', '邮箱验证码', code, '验证码 10 分钟内有效，请勿转发给他人。')


def resend_verification(email):
    email = normalize_email(email)
    with store.db() as con:
        row = con.execute("SELECT id,email,email_verified FROM users WHERE email=?", (email,)).fetchone()
    if row and not row['email_verified']:
        send_verification_code(row['id'], row['email'])


def verify_email_code(email, code):
    email = normalize_email(email)
    code = str(code or '').strip()
    if not re.fullmatch(r'\d{6}', code):
        raise HTTPException(400, '请输入 6 位邮箱验证码')
    digest = hashlib.sha256(code.encode()).hexdigest()
    now = time.time()
    with store.db() as con:
        row = con.execute('''SELECT u.id,u.email,u.role FROM auth_tokens t
                             JOIN users u ON u.id=t.user_id
                             WHERE u.email=? AND t.token_hash=? AND t.purpose='verify_email_code'
                               AND t.expires>=? AND u.email_verified=0''',
                          (email, digest, now)).fetchone()
        if not row:
            raise HTTPException(400, '验证码错误或已过期，请重新获取')
        con.execute("DELETE FROM auth_tokens WHERE user_id=? AND purpose='verify_email_code'", (row['id'],))
        con.execute("UPDATE users SET email_verified=1 WHERE id=?", (row['id'],))
    return _public_user(row)


def verify_email(token):
    user_id = _consume_token(token, 'verify_email')
    with store.db() as con:
        con.execute("UPDATE users SET email_verified=1 WHERE id=?", (user_id,))
        row = con.execute("SELECT id,email,role FROM users WHERE id=?", (user_id,)).fetchone()
    return _public_user(row)


def request_password_reset(email):
    email = normalize_email(email)
    with store.db() as con:
        row = con.execute("SELECT id,email,email_verified FROM users WHERE email=?", (email,)).fetchone()
    if row and row['email_verified']:
        token = _issue_token(row['id'], 'reset_password', RESET_SECONDS)
        url = f"{config.PUBLIC_BASE_URL}/reset-password?token={quote(token)}"
        mailer.send(row['email'], '重置你的拾影密码', '重置密码', '点击下方按钮设置新密码，链接 30 分钟内有效。', '设置新密码', url)


def reset_password(token, password):
    password = validate_password(password)
    user_id = _consume_token(token, 'reset_password')
    with store.db() as con:
        con.execute("UPDATE users SET password_hash=? WHERE id=?", (_password_hash(password), user_id))
        con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


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
                           WHERE s.token=? AND s.expires>=? AND u.email_verified=1""", (digest, time.time())).fetchone()
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
            now = time.time()
            con.execute("INSERT INTO users(id,email,password_hash,created) VALUES(?,?,?,?)",
                        (LEGACY_USER_ID, email, _password_hash(password), now))
            con.execute("INSERT INTO credit_ledger(id,user_id,amount,kind,note,created) VALUES(?,?,?,?,?,?)",
                        (store.uid(), LEGACY_USER_ID, 100, 'welcome', '新用户注册赠送', now))
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
