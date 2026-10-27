import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import config
import mailer
from app import app


def configure(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'legacy-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    monkeypatch.setattr(config, 'EMAIL_VERIFICATION_REQUIRED', True)
    monkeypatch.setattr(config, 'PUBLIC_BASE_URL', 'https://example.test')
    monkeypatch.setattr(config, 'mail_ready', lambda: True)


def code_from(messages, index=-1):
    return messages[index][3]


def test_registration_requires_single_use_email_code(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    messages = []
    monkeypatch.setattr(mailer, 'send_code', lambda *args: messages.append(args))
    with TestClient(app) as client:
        response = client.post('/api/register', json={'email': 'new@example.com', 'password': 'strong-pass-123'})
        assert response.status_code == 202
        assert response.json()['pending_verification'] is True
        assert client.get('/api/me').json()['user'] is None
        assert client.post('/api/login', json={'email': 'new@example.com', 'password': 'strong-pass-123'}).status_code == 403
        code = code_from(messages)
        assert len(code) == 6 and code.isdigit()
        assert client.post('/api/verify-email-code', json={'email': 'new@example.com', 'code': '000000'}).status_code == 400
        verified = client.post('/api/verify-email-code', json={'email': 'new@example.com', 'code': code})
        assert verified.status_code == 200
        assert verified.json()['user']['email'] == 'new@example.com'
        assert client.post('/api/verify-email-code', json={'email': 'new@example.com', 'code': code}).status_code == 400


def test_password_reset_revokes_existing_sessions(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    messages = []
    monkeypatch.setattr(mailer, 'send_code', lambda *args: messages.append(args))
    reset_messages = []
    monkeypatch.setattr(mailer, 'send', lambda *args: reset_messages.append(args))
    with TestClient(app) as account, TestClient(app) as old_session:
        account.post('/api/register', json={'email': 'reset@example.com', 'password': 'strong-pass-123'})
        account.post('/api/verify-email-code', json={'email': 'reset@example.com', 'code': code_from(messages)})
        assert old_session.post('/api/login', json={'email': 'reset@example.com', 'password': 'strong-pass-123'}).status_code == 200
        requested = account.post('/api/request-password-reset', json={'email': 'reset@example.com'})
        assert requested.status_code == 200
        from urllib.parse import parse_qs, urlparse
        reset_token = parse_qs(urlparse(reset_messages[-1][-1]).query)['token'][0]
        reset = account.post('/api/reset-password', json={'token': reset_token, 'password': 'new-strong-pass-456'})
        assert reset.status_code == 200
        assert old_session.get('/api/me').json()['user'] is None
        assert account.post('/api/login', json={'email': 'reset@example.com', 'password': 'strong-pass-123'}).status_code == 401
        assert account.post('/api/login', json={'email': 'reset@example.com', 'password': 'new-strong-pass-456'}).status_code == 200


def test_unknown_email_reset_does_not_disclose_account(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    messages = []
    monkeypatch.setattr(mailer, 'send', lambda *args: messages.append(args))
    with TestClient(app) as client:
        response = client.post('/api/request-password-reset', json={'email': 'missing@example.com'})
        assert response.status_code == 200
        assert messages == []
