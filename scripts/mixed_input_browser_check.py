"""Mixed-input editor browser regression in isolated simulation data."""
import json, os, subprocess, sys, time
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'mixed-input'
DATA=OUT/'data'
OUT.mkdir(parents=True,exist_ok=True)
from playwright.sync_api import sync_playwright, expect

env=os.environ.copy();env.update(DATA_DIR=str(DATA),SITE_PASSWORD='mixed-test-password',GENERATION_MODE='simulation',PORT='8790',SOURCE_STRATEGY='context-crop')
proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
try:
    for _ in range(100):
        try:
            if json.load(urlopen('http://127.0.0.1:8790/api/health'))['ok']:break
        except Exception: time.sleep(.1)
    else: raise RuntimeError('test server not ready')
    with sync_playwright() as pw:
        chrome=next((p for p in [Path(os.environ.get('PROGRAMFILES',r'C:\\Program Files'))/'Google/Chrome/Application/chrome.exe',Path(os.environ.get('PROGRAMFILES(X86)',r'C:\\Program Files (x86)'))/'Google/Chrome/Application/chrome.exe',Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe'] if p.is_file()),None)
        if not chrome: raise RuntimeError('local Chrome not found; browser verification requires installed Chrome')
        browser=pw.chromium.launch(headless=True,executable_path=str(chrome))
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];writes=[]
        page.on('console',lambda msg: errors.append(msg.text) if msg.type=='error' else None)
        page.on('request',lambda req: writes.append(req.url) if req.method!='GET' else None)
        page.goto('http://127.0.0.1:8790');page.locator('input[name=password]').fill('mixed-test-password');page.locator('#login button').click()
        expect(page.locator('.composer h2')).to_contain_text('统一提示词')
        # Create fixtures via authenticated API, avoiding native upload dialogs.
        from PIL import Image
        import io
        def png(color):
            b=io.BytesIO();Image.new('RGB',(240,180),color).save(b,'PNG');return b.getvalue()
        ctx=page.context.request
        main=ctx.post('http://127.0.0.1:8790/api/assets',multipart={'file':{'name':'main.png','mimeType':'image/png','buffer':png('navy')}}).json()
        ref=ctx.post('http://127.0.0.1:8790/api/assets',multipart={'file':{'name':'ref.png','mimeType':'image/png','buffer':png('orange')}}).json()
        main_mask=ctx.post('http://127.0.0.1:8790/api/masks',data={'image_id':main['id'],'points':[[.2,.2],[.7,.2],[.7,.8],[.2,.8]]}).json()
        ref_mask=ctx.post('http://127.0.0.1:8790/api/masks',data={'image_id':ref['id'],'points':[[.2,.2],[.7,.2],[.7,.8],[.2,.8]]}).json()
        mapping={'id':'browser-mapping','display_index':1,'color':'#8b5cf6','mode':'replace','requirement':'已确认旧要求','source':{'image_id':ref['id'],'image_version':1,'mask_id':ref_mask['id'],'anchor':{'x':.3,'y':.3},'label':'橙色外套'},'target':{'image_id':main['id'],'image_version':1,'mask_id':main_mask['id'],'edit_region_id':main_mask['id'],'anchor':{'x':.4,'y':.4}}}
        draft=ctx.post('http://127.0.0.1:8790/api/drafts').json();draft.update({'name':'混用浏览器验证','main_image':main['id'],'references':[ref['id']],'mappings':[mapping],'next_display_index':2,'full_image_refs':[],'instructions':'自然光'})
        saved=ctx.put('http://127.0.0.1:8790/api/drafts/'+draft['id'],data=draft);assert saved.ok
        page.reload();expect(page.locator('#main-canvas')).to_be_visible();expect(page.locator('#filmstrip img')).to_have_count(1);expect(page.locator('.composer-entry')).to_contain_text('元素 · 1 · 橙色外套')
        # Bubble draft is discarded outside, then confirmation updates the same composer entry in place.
        page.locator('[data-canvas-bubble="browser-mapping"]').click();page.locator('#bubble-editor textarea').fill('未确认草稿');page.locator('.workspace-heading').click();expect(page.locator('[data-requirement="browser-mapping"]')).to_have_value('已确认旧要求')
        page.locator('[data-canvas-bubble="browser-mapping"]').click();page.locator('#bubble-editor textarea').fill('让人物坐下并穿上外套');page.locator('#bubble-editor button').click();expect(page.locator('[data-requirement="browser-mapping"]')).to_have_value('让人物坐下并穿上外套');expect(page.locator('.composer-entry:not(.whole)')).to_have_count(1)
        page.locator('#mention').click();expect(page.locator('#mention-menu')).to_be_visible();expect(page.locator('#mention-menu')).to_contain_text('完整参考图');expect(page.locator('#mention-menu')).to_contain_text('已拖入主图的元素')
        page.locator('[data-add-whole]').click();expect(page.locator('.composer-entry.whole')).to_be_visible();expect(page.locator('.composer-entry.whole')).to_contain_text('整图 · 参考图 1')
        page.locator('[data-purpose]').fill('参考完整背景氛围');page.locator('[data-purpose]').blur();page.wait_for_timeout(900)
        expect(page.locator('#generate')).to_be_enabled()
        page.screenshot(path=str(OUT/'mixed-composer.png'),full_page=True)
        # Submit simulation and inspect immutable historical actual inputs.
        page.locator('#generate').click();expect(page.locator('.status-badge')).to_contain_text('模拟检查',timeout=10000)
        expect(page.locator('.detail-sidebar')).to_contain_text('整图 · 参考图 1');expect(page.locator('.detail-sidebar')).to_contain_text('让人物坐下并穿上外套');expect(page.locator('.detail-sidebar')).to_contain_text('实际模型输入');expect(page.locator('.detail-sidebar')).to_contain_text('元素 1 → IMAGE 2');expect(page.locator('.detail-sidebar')).to_contain_text('整图 IMAGE 3')
        page.screenshot(path=str(OUT/'mixed-history.png'),full_page=True)
        # Restore preserves binding; result continuation is backend-covered because simulation has no result bytes.
        page.locator('#restore').click();expect(page.locator('.composer-entry.whole')).to_contain_text('整图 · 参考图 1')
        page.screenshot(path=str(OUT/'mixed-restored.png'),full_page=True)
        result={'checks':['single rich composer visible','bubble outside-click discards draft','bubble confirmation replaces shared composer entry without duplication','whole-image @ menu uses existing references','same source element crop and whole image submit together','history shows immutable requirements and actual input indexes','restore returns bindings'],'console_errors':[e for e in errors if '401 (Unauthorized)' not in e],'expected_prelogin_401':any('401 (Unauthorized)' in e for e in errors),'job_posts':[u for u in writes if u.endswith('/api/jobs')],'screenshots':['mixed-composer.png','mixed-history.png','mixed-restored.png']}
        (OUT/'browser-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        assert not [e for e in errors if '401 (Unauthorized)' not in e] and len(result['job_posts'])==1
        browser.close()
finally:
    proc.terminate()
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired: proc.kill()
