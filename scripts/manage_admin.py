"""Create the local admin login or promote an existing email account."""
import argparse
import getpass
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import auth
import config
import store


def provision(data_dir, username, password=None):
    config.DATA = Path(data_dir).resolve()
    if not (config.DATA / 'editor.sqlite').is_file():
        raise ValueError('请先运行应用，并指定正确的数据目录')
    username = username.strip().lower()
    if username != 'admin':
        username = auth.normalize_email(username)
    with store.db() as con:
        store._add_column(con, 'users', "role TEXT NOT NULL DEFAULT 'user'")
        row = con.execute('SELECT id FROM users WHERE email=?', (username,)).fetchone()
        if row:
            con.execute("UPDATE users SET role='admin' WHERE id=?", (row['id'],))
            return '已将已有账号设为管理员，原密码保持不变'
        if username != 'admin':
            raise ValueError('邮箱尚未注册，请先注册')
        if password is None or not 8 <= len(password) <= 128:
            raise ValueError('管理员密码需为 8 至 128 个字符')
        con.execute("INSERT INTO users(id,email,password_hash,created,role) VALUES(?,?,?,?,'admin')",
                    (store.uid(),username,auth._password_hash(password),time.time()))
    return '管理员账号已创建'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    password = getpass.getpass('新管理员密码（已有账号不改密码）: ') if args.username == 'admin' else None
    print(provision(args.data_dir,args.username,password))
