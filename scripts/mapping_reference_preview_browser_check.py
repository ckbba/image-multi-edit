"""Zero-fee isolated acceptance for compact mapping cards and previews."""
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
OUT = ROOT / 'output' / 'mapping-reference-preview'
DATA = OUT / 'data'
BASE = 'http://127.0.0.1:8794'
PASSWORD = 'mapping-preview-isolated-password'
ENV = {**os.environ, 'DATA_DIR': str(DATA), 'SITE_PASSWORD': PASSWORD, 'PORT': '8794', 'GENERATION_MODE': 'simulation'}
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
    buf = io.BytesIO(); Image.new('RGB', (160, 100), color).save(buf, 'PNG')
    response = client.post('/api/assets', files={'file': ('fixture.png', buf.getvalue(), 'image/png')})
    response.raise_for_status(); return response.json()['id']

try:
    wait_server()
    with httpx.Client(base_url=BASE, trust_env=False) as client:
        client.post('/api/login', json={'password':PASSWORD}).raise_for_status()
        main, ref = upload(client, '#4466aa'), upload(client, '#ba4b62')
        sm = client.post('/api/masks', json={'image_id':ref,'points':[[.2,.2],[.6,.2],[.6,.7],[.2,.7]]}).json()
        tm = client.post('/api/masks', json={'image_id':main,'points':[[.4,.2],[.8,.2],[.8,.7],[.4,.7]]}).json()
        state = client.post('/api/drafts').json()
        state.update(name='零付费预览验收', main_image=main, references=[ref], next_display_index=2,
            mappings=[{'id':'accept-mapping','kind':'reference-edit','display_index':1,'color':'#8b5cf6','mode':'replace','requirement':'替换主体','subject_focus':False,
            'source':{'image_id':ref,'image_version':1,'mask_id':sm['id'],'anchor':{'x':.3,'y':.3},'label':'海报'},
            'target':{'image_id':main,'image_version':1,'mask_id':tm['id'],'edit_region_id':tm['id'],'anchor':{'x':.5,'y':.3}}}])
        client.put('/api/drafts/'+state['id'], json=state).raise_for_status()
        before_jobs=client.get('/api/jobs').json()['items']

    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1100,'height':900})
        page.on('console',lambda message: errors.append(message.text) if message.type=='error' and '401 (Unauthorized)' not in message.text else None)
        page.goto(BASE)
        page.get_by_role('textbox',name='空间密码').fill(PASSWORD)
        page.get_by_role('button',name='进入工作室 →').click()
        card=page.locator('.mapping').first
        expect(card.locator('details')).to_have_attribute('open','')
        title=card.locator('.mapping-title-row'); corrections=card.locator('.mapping-corrections')
        boxes=page.evaluate("""() => {const t=document.querySelector('.mapping-title-row>b').getBoundingClientRect(),c=document.querySelector('.mapping-corrections').getBoundingClientRect(),m=document.querySelector('.mapping').getBoundingClientRect();return {titleTop:t.top,controlsTop:c.top,right:c.right,mapRight:m.right,overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth}}""")
        assert abs(boxes['titleTop']-boxes['controlsTop']) < 8 and boxes['right'] <= boxes['mapRight'] and not boxes['overflow'], boxes
        control=card.locator('.subject-focus-toggle')
        expect(control).to_contain_text('蒙版效果')
        control_box=control.bounding_box(); assert control_box and control_box['width'] <= 150 and control_box['height'] <= 32, control_box
        assert page.evaluate("el=>el.scrollWidth<=el.clientWidth",control.element_handle())
        boxes['subjectFocusControl']=control_box
        thumb=card.locator('[data-actual-preview]');page.wait_for_timeout(500);thumb=page.locator('[data-actual-preview]').first;thumb.dispatch_event('mouseenter')
        expect(page.locator('.actual-input-preview')).to_be_visible(timeout=10000)
        expect(page.locator('.actual-input-preview')).to_contain_text('模型参考输入 · 蒙版关闭')
        page.screenshot(path=str(OUT/'compact-actual-preview.png'),full_page=True)
        card.locator('[data-label]').fill('奖杯');card.locator('[data-label]').press('Tab')
        expect(page.locator('#toast')).to_contain_text('未定位到新区域')
        card=page.locator('.mapping').first;card.locator('[data-subject-focus]').check()
        page.locator('[data-actual-preview]').first.dispatch_event('mouseenter');expect(page.locator('.actual-input-preview')).to_contain_text('模型参考输入 · 蒙版效果')
        page.screenshot(path=str(OUT/'subject-focus-preview.png'),full_page=True)
        browser.close()

    with httpx.Client(base_url=BASE, trust_env=False) as verify:
        verify.post('/api/login', json={'password':PASSWORD}).raise_for_status()
        result={'jobs_unchanged':verify.get('/api/jobs').json()['items']==before_jobs,'generation_calls':0,'mode':'simulation','console_errors':errors,'layout':boxes,
            'screenshots':[str(OUT/'compact-actual-preview.png'),str(OUT/'subject-focus-preview.png')]}
    assert result['jobs_unchanged'] and not errors, result
    (OUT/'check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
finally:
    proc.terminate()
    try: proc.wait(timeout=15)
    except subprocess.TimeoutExpired: proc.kill()
    log.close()
