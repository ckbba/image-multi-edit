"""Check the user's saved overlap geometry in an isolated, non-billing server."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '后端代码'))
import config
import store

OUT = ROOT / 'output/playwright'
OUT.mkdir(parents=True, exist_ok=True)
original_data = config.DATA
with store.db() as con:
    state = json.loads(con.execute('SELECT state FROM drafts ORDER BY updated DESC LIMIT 1').fetchone()['state'])
original_state = copy.deepcopy(state)
overlaps = store.validate(state)
assert overlaps, 'This check needs a saved draft with overlapping targets'
ids = {state['main_image'], *state['references']}
for mapping in state['mappings']:
    for side in ('source', 'target'):
        ids.add(mapping[side]['mask_id'])
        ids.add(mapping[side].get('edit_region_id', mapping[side]['mask_id']))
metadata = [store.asset(aid) for aid in ids]
config.DATA = Path(tempfile.mkdtemp(prefix='overlap-', dir=OUT))
store.init()
with store.db() as con:
    for asset in metadata:
        shutil.copy2(original_data / asset['path'], config.DATA / asset['path'])
        thumb = Path(asset['path']).with_suffix('.thumb.png')
        shutil.copy2(original_data / thumb, config.DATA / thumb)
        con.execute('INSERT INTO assets VALUES(?,?)', (asset['id'], json.dumps(asset)))
store.new_draft(state)
env = {**os.environ, 'DATA_DIR': str(config.DATA), 'GENERATION_MODE': 'simulation',
       'SITE_PASSWORD': 'overlap-check-password', 'PORT': '8789',
       'SEGMENTATION_MODEL_DIR': str(config.DATA / 'no-model')}
base = 'http://127.0.0.1:8789'
log = (OUT / 'overlap-server.log').open('w', encoding='utf-8')
process = subprocess.Popen([sys.executable, str(ROOT / 'run.py')], cwd=ROOT, env=env, stdout=log, stderr=log)
try:
    with httpx.Client(base_url=base, trust_env=False, timeout=10) as client:
        for _ in range(100):
            try:
                if client.get('/api/health').status_code == 200:
                    break
            except httpx.ConnectError:
                time.sleep(.1)
        client.post('/api/login', json={'password': env['SITE_PASSWORD']}).raise_for_status()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 719, 'height': 686})
            errors = []
            submissions = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: submissions.append(request.post_data_json)
                    if request.method == 'POST' and request.url == base + '/api/jobs' else None)
            page.goto(base)
            page.get_by_role('textbox', name='空间密码').fill(env['SITE_PASSWORD'])
            page.get_by_role('button', name='进入工作室 →').click()
            expect(page.locator('.mapping')).to_have_count(len(state['mappings']))
            page.reload()
            expect(page.locator('#generate')).to_be_enabled()
            page.locator('#generate').click()
            dialog = page.get_by_role('dialog')
            expect(dialog).to_be_visible()
            for conflict in overlaps:
                expect(dialog).to_contain_text(f"{conflict['a']} 与 {conflict['b']}")
            page.screenshot(path=str(OUT / 'overlap-confirmation.png'))
            dialog.get_by_role('button', name='返回调整').click()
            expect(dialog).to_have_count(0)
            assert not client.get('/api/jobs').json()['items'] and not submissions
            page.locator('#generate').click()
            expect(dialog).to_be_visible()
            page.keyboard.press('Escape')
            expect(dialog).to_have_count(0)
            assert not submissions
            page.locator('#generate').click()
            dialog.get_by_role('button', name='仍要继续模拟', exact=False).click()
            expect(page.locator('.status-badge')).to_have_text('模拟检查 · 未生图')
            expect(page.locator('.detail-notice')).to_contain_text('本次已确认继续生成')
            assert len(submissions) == 1 and submissions[0]['allow_overlap'] is True
            jobs = client.get('/api/jobs').json()['items']
            assert len(jobs) == 1 and jobs[0]['result']['calls'] == 0
            job = client.get('/api/jobs/' + jobs[0]['id']).json()
            assert job['snapshot']['overlap_confirmation']['conflicts'] == overlaps
            page.locator('#restore').click()
            expect(page.locator('.mapping')).to_have_count(len(state['mappings']))
            page.locator('#generate').click()
            expect(dialog).to_be_visible()
            dialog.get_by_role('button', name='返回调整').click()
            assert len(submissions) == 1 and not errors
            browser.close()
        report = {'overlaps': overlaps, 'console_errors': errors, 'job_requests': len(submissions),
                  'generation_calls': 0, 'checks': ['saved overlaps shown after refresh; button enabled',
                  'cancel and Escape create no job', 'continue submits exactly once',
                  'immutable snapshot records the acknowledgement', 'restore requires fresh confirmation']}
        (OUT / 'overlap-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=True))
finally:
    process.terminate()
    process.wait(timeout=15)
    log.close()
    config.DATA = original_data
with store.db() as con:
    original = json.loads(con.execute('SELECT state FROM drafts WHERE id=?', (original_state['id'],)).fetchone()['state'])
assert original == original_state, 'The real user draft must remain unchanged'
