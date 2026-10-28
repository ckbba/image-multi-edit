import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import config
import store
from app import app


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'MODE', 'simulation')
    monkeypatch.setattr(config, 'EMAIL_VERIFICATION_REQUIRED', False)
    with TestClient(app) as admin, TestClient(app) as member, TestClient(app) as other:
        admin_user = admin.post('/api/register', json={'email': 'credits-admin@example.com', 'password': 'strong-pass-123'}).json()['user']
        member_user = member.post('/api/register', json={'email': 'member@example.com', 'password': 'strong-pass-123'}).json()['user']
        other_user = other.post('/api/register', json={'email': 'other@example.com', 'password': 'strong-pass-123'}).json()['user']
        with store.db() as con:
            con.execute("UPDATE users SET role='admin' WHERE id=?", (admin_user['id'],))
        yield admin, member, other, admin_user, member_user, other_user


def insert_job(user_id, status='simulated', mode='simulation', idem=None):
    jid = store.uid()
    snapshot = {'state': {'name': 'credit fixture', 'main_image': 'fixture', 'mappings': [], 'text_edits': [], 'full_image_refs': []},
                'compiled': {'bindings': []}, 'mode': mode, 'model': 'gpt-image-2.5-flare'}
    with store.db() as con:
        con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result,user_id) VALUES(?,?,?,?,?,?,?)',
                    (jid, idem or jid, time.time(), status, json.dumps(snapshot), '{}', user_id))
    return jid


def test_new_user_starts_with_one_hundred_credits_and_member_cannot_admin(clients):
    admin, member, _, _, member_user, _ = clients
    summary = member.get('/api/account/credits').json()
    assert summary['balance'] == summary['available'] == 100
    assert summary['reserved'] == 0
    assert [(item['kind'], item['amount']) for item in summary['items']] == [('welcome', 100)]
    assert member.get('/api/admin/users').status_code == 403
    assert member.get(f"/api/admin/users/{member_user['id']}/credits").status_code == 403
    assert admin.get('/api/admin/users').status_code == 200


def test_legacy_owner_created_after_schema_migration_receives_welcome_credits(tmp_path, monkeypatch):
    import auth
    monkeypatch.setattr(config, 'DATA', tmp_path)
    store.init()
    auth.bootstrap_legacy('legacy-password')
    assert store.credit_summary(auth.LEGACY_USER_ID)['balance'] == 100


def test_admin_adjustments_are_audited_and_never_go_negative(clients):
    admin, member, _, admin_user, member_user, _ = clients
    assert admin.post(f"/api/admin/users/{member_user['id']}/credits", json={'amount': 25, 'note': '用户购买充值'}).json()['balance'] == 125
    assert admin.post(f"/api/admin/users/{member_user['id']}/credits", json={'amount': -20, 'note': '订单退款扣减'}).json()['balance'] == 105
    data = member.get('/api/account/credits').json()
    assert data['balance'] == 105
    assert data['items'][0]['amount'] == -20
    assert data['items'][0]['operator_user_id'] == admin_user['id']
    assert data['items'][0]['operator_email'] == 'credits-admin@example.com'
    assert admin.post(f"/api/admin/users/{member_user['id']}/credits", json={'amount': -106, 'note': '超额扣减'}).status_code == 409
    assert admin.post(f"/api/admin/users/{member_user['id']}/credits", json={'amount': 1, 'note': ''}).status_code == 400


def test_success_charge_is_idempotent_and_simulation_or_failure_does_not_charge(clients):
    _, member, _, _, member_user, _ = clients
    success = insert_job(member_user['id'], status='succeeded', mode='live')
    failed = insert_job(member_user['id'], status='failed', mode='live')
    simulated = insert_job(member_user['id'], status='simulated', mode='simulation')
    assert store.charge_successful_job(success)['created'] is True
    assert store.charge_successful_job(success)['created'] is False
    assert store.charge_successful_job(failed) is None
    assert store.charge_successful_job(simulated) is None
    summary = member.get('/api/account/credits').json()
    assert summary['balance'] == 99
    assert [item['job_id'] for item in summary['items'] if item['kind'] == 'generation'] == [success]


def test_reserved_credits_are_protected_from_admin_deduction(clients):
    admin, member, _, _, member_user, _ = clients
    insert_job(member_user['id'], status='queued', mode='live')
    summary = member.get('/api/account/credits').json()
    assert summary['balance'] == 100 and summary['reserved'] == 1 and summary['available'] == 99
    response = admin.post(f"/api/admin/users/{member_user['id']}/credits", json={'amount': -100, 'note': '清空测试'} )
    assert response.status_code == 409
    assert member.get('/api/account/credits').json()['balance'] == 100


def test_admin_user_list_does_not_multiply_ledger_by_job_rows(clients):
    admin, _, _, _, member_user, _ = clients
    store.add_credits(member_user['id'], -10, 'admin_adjustment', '测试扣减')
    insert_job(member_user['id']); insert_job(member_user['id'])
    row = next(item for item in admin.get('/api/admin/users').json()['items'] if item['id'] == member_user['id'])
    assert row['balance'] == 90
    assert row['spent'] == 10


def test_history_user_filter_is_admin_only(clients):
    admin, member, other, _, member_user, other_user = clients
    member_job = insert_job(member_user['id'])
    other_job = insert_job(other_user['id'])
    assert [item['id'] for item in member.get(f"/api/jobs?user_id={other_user['id']}").json()['items']] == [member_job]
    assert [item['id'] for item in admin.get(f"/api/jobs?user_id={other_user['id']}").json()['items']] == [other_job]
    assert admin.get(f'/api/jobs/{other_job}').status_code == 200
    assert member.get(f'/api/jobs/{other_job}').status_code == 404


def test_admin_can_read_but_not_modify_another_users_assets(clients):
    from PIL import Image
    import io
    admin, member, _, _, _, _ = clients
    image = io.BytesIO(); Image.new('RGB', (12, 12), 'purple').save(image, 'PNG')
    asset = member.post('/api/assets', files={'file': ('private.png', image.getvalue(), 'image/png')}).json()
    assert admin.get(f"/api/assets/{asset['id']}?thumbnail=true").status_code == 200
    assert admin.get(f"/api/assets/{asset['id']}/meta").status_code == 200
