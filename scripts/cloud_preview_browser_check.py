"""Isolated browser checks for the real cloud-image preview entry and state."""
import io
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'cloud-preview'
OUT.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='cloud-preview-') as temp:
    env={**os.environ,'DATA_DIR':temp,'SITE_PASSWORD':'preview-isolated-pass','PORT':'8819','GENERATION_MODE':'simulation'}
    log=open(Path(temp)/'server.log','w',encoding='utf-8')
    server=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
    base='http://127.0.0.1:8819'
    try:
        for _ in range(120):
            try:
                if httpx.get(base+'/api/health',trust_env=False,timeout=1).status_code==200:break
            except Exception: time.sleep(.1)
        else:raise RuntimeError('server not ready')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe')
            page=browser.new_page(viewport={'width':1440,'height':900})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base+'/drive');page.locator('#login input').fill('preview-isolated-pass');page.locator('#login button[type=submit]').click()
            image=Image.new('RGB',(180,360),'orange');buf=io.BytesIO();image.save(buf,'PNG')
            with httpx.Client(base_url=base,trust_env=False) as client:
                client.post('/api/login',json={'password':'preview-isolated-pass'}).raise_for_status()
                response=client.post('/api/drive/files',data={'parent_id':''},files={'file':('portrait.png',buf.getvalue(),'image/png')});response.raise_for_status();item=response.json()
                assert client.get('/api/drive/storage').json()['used_bytes']>0
            page.reload();expect(page.locator('[data-item]')).to_have_count(1)
            page.locator('.drive-name').dblclick()
            expect(page.locator('.cloud-image-preview')).to_be_visible()
            assert page.url.endswith('#p_fid='+item['id'])
            assert page.locator('.cloud-preview-stage img').evaluate('(e)=>e.complete && e.naturalWidth===180')
            expect(page.locator('.cloud-preview-sidebar button')).to_have_count(6)
            page.screenshot(path=str(OUT/'base.png'))
            assert page.get_by_role('button',name='图像转视频').is_disabled()
            page.get_by_role('button',name='右旋').click()
            assert 'rotate(90deg)' in page.locator('.cloud-preview-image-box').get_attribute('style')
            page.get_by_role('button',name='重置旋转与缩放').click()
            assert 'rotate(0deg)' in page.locator('.cloud-preview-image-box').get_attribute('style')
            page.get_by_role('button',name='魔法橡皮擦').click()
            page.screenshot(path=str(OUT/'eraser.png'))
            expect(page.locator('.cloud-preview-mask')).to_be_visible()
            assert page.locator('[data-apply]').is_disabled() and page.locator('[data-save]').is_disabled()
            canvas=page.locator('.cloud-preview-mask');rect=canvas.bounding_box();page.mouse.move(rect['x']+60,rect['y']+80);page.mouse.down();page.mouse.move(rect['x']+130,rect['y']+120,steps=5);page.mouse.up()
            assert page.locator('[data-undo]').is_enabled()
            page.once('dialog',lambda d:d.dismiss())
            page.get_by_role('button',name='返回预览').click()
            expect(page.locator('.cloud-preview-mask')).to_be_visible()
            page.once('dialog',lambda d:d.accept())
            page.get_by_role('button',name='返回预览').click()
            page.get_by_role('button',name='关闭预览').click()
            expect(page.locator('.cloud-image-preview')).to_have_count(0)
            assert page.url.endswith('/drive') and page.locator('[data-item]').count()==1
            assert not errors,errors
            print({'preview':True,'hash_restored':True,'tool_count':6,'brush_undo':True,'unsaved_guard':True,'paid_calls':0,'errors':errors})
            browser.close()
    finally:
        server.terminate();server.wait(timeout=10);log.close()
