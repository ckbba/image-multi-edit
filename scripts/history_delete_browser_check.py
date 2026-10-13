"""Isolated browser acceptance for history-card deletion; simulation only."""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'history-delete'
DATA = OUT / 'data'
BASE = 'http://127.0.0.1:8793'
PASSWORD = 'history-delete-isolated-password'
ENV = {**os.environ, 'DATA_DIR': str(DATA), 'SITE_PASSWORD': PASSWORD, 'PORT': '8793', 'GENERATION_MODE': 'simulation'}
OUT.mkdir(parents=True, exist_ok=True)
log = (OUT / 'server.log').open('w', encoding='utf-8')
proc = subprocess.Popen([sys.executable, str(ROOT / 'run.py')], cwd=ROOT, env=ENV, stdout=log, stderr=log)

def wait_server():
    for _ in range(100):
        try:
            if httpx.get(BASE + '/api/health', trust_env=False, timeout=1).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(.1)
    raise RuntimeError('isolated server did not start')

def upload(client, color):
    buf = io.BytesIO(); Image.new('RGB', (80, 60), color).save(buf, 'PNG')
    response = client.post('/api/assets', files={'file': ('fixture.png', buf.getvalue(), 'image/png')})
    response.raise_for_status(); return response.json()['id']

def create_job(client, name, main, shared, key):
    state = client.post('/api/drafts').json()
    state.update(name=name, main_image=main, references=[shared], instructions='保留共享素材', full_image_refs=[{'id':'whole-'+key,'image_id':shared,'label':'共享输入','purpose':'保留构图'}])
    saved = client.put('/api/drafts/' + state['id'], json=state); saved.raise_for_status()
    response = client.post('/api/jobs', json={'draft_id':state['id'],'revision':saved.json()['revision'],'idempotency_key':key})
    response.raise_for_status(); return response.json()['id']

try:
    wait_server()
    with httpx.Client(base_url=BASE, trust_env=False) as client:
        client.post('/api/login', json={'password':PASSWORD}).raise_for_status()
        main = upload(client, 'blue')
        shared = upload(client, 'purple')
        delete_id = create_job(client, '待删除样例', main, shared, 'delete-fixture')
        keep_id = create_job(client, '保留样例', main, shared, 'keep-fixture')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':1280,'height':900})
        page = context.new_page()
        page.goto(BASE)
        page.get_by_role('textbox', name='空间密码').fill(PASSWORD)
        page.get_by_role('button', name='进入工作室 →').click()
        page.goto(BASE + '/history')
        expect(page.locator('.history-card-shell')).to_have_count(2)
        target = page.locator(f'.history-card-shell[data-job-id="{delete_id}"]')
        delete_button = target.get_by_role('button', name='删除历史「待删除样例」')
        expect(delete_button).to_have_css('opacity', '0')
        target.hover(); expect(delete_button).to_have_css('opacity', '1')
        page.screenshot(path=str(OUT / 'history-delete-hover.png'), full_page=True)

        page.once('dialog', lambda dialog: dialog.dismiss())
        delete_button.click()
        expect(page).to_have_url(BASE + '/history')
        expect(target).to_have_count(1)
        with httpx.Client(base_url=BASE, trust_env=False) as verify:
            verify.post('/api/login', json={'password':PASSWORD}).raise_for_status()
            cancel_zero_write = verify.get('/api/jobs/' + delete_id).status_code == 200
            assert cancel_zero_write

        page.once('dialog', lambda dialog: dialog.accept())
        delete_button.click()
        expect(page).to_have_url(BASE + '/history')
        expect(page.locator(f'.history-card-shell[data-job-id="{delete_id}"]')).to_have_count(0)
        expect(page.locator(f'.history-card-shell[data-job-id="{keep_id}"]')).to_have_count(1)
        page.screenshot(path=str(OUT / 'history-delete-confirmed.png'), full_page=True)
        with httpx.Client(base_url=BASE, trust_env=False) as verify:
            verify.post('/api/login', json={'password':PASSWORD}).raise_for_status()
            listed = {item['id'] for item in verify.get('/api/jobs').json()['items']}
            result = {
                'cancel_zero_write': cancel_zero_write,
                'deleted_absent_from_server_list': delete_id not in listed,
                'other_history_present': keep_id in listed and verify.get('/api/jobs/' + keep_id).status_code == 200,
                'shared_asset_accessible': verify.get('/api/assets/' + shared).status_code == 200,
                'no_navigation': page.url == BASE + '/history',
                'screenshot': str(OUT / 'history-delete-confirmed.png'),
            }
        assert all(value for key,value in result.items() if key != 'screenshot'), result
        (OUT / 'history-delete-browser.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        browser.close()
finally:
    proc.terminate()
    try: proc.wait(timeout=15)
    except subprocess.TimeoutExpired: proc.kill()
    log.close()
