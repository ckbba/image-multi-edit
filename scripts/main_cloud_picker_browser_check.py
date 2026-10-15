"""Isolated main-image source menu and cloud picker regression."""
import io,os,subprocess,sys,tempfile,time
from pathlib import Path
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='main-cloud-picker-', dir=os.environ.get('TMPDIR') or str(ROOT/'output'), ignore_cleanup_errors=True) as data:
 env={**os.environ,'DATA_DIR':data,'SITE_PASSWORD':'main-cloud-test','PORT':'8827','GENERATION_MODE':'simulation'}
 log=open(Path(data)/'server.log','w',encoding='utf-8');proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
 base='http://127.0.0.1:8827'
 try:
  for _ in range(120):
   try:
    if httpx.get(base+'/api/health',trust_env=False,timeout=1).status_code==200:break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('server not ready')
  buf=io.BytesIO();Image.new('RGB',(80,100),'red').save(buf,'PNG')
  with httpx.Client(base_url=base,trust_env=False) as c:
   c.post('/api/login',json={'password':'main-cloud-test'}).raise_for_status()
   first=c.post('/api/drive/files',files={'file':('red.png',buf.getvalue(),'image/png')});first.raise_for_status()
   buf=io.BytesIO();Image.new('RGB',(70,90),'blue').save(buf,'PNG')
   second=c.post('/api/drive/files',files={'file':('blue.png',buf.getvalue(),'image/png')});second.raise_for_status()
  with sync_playwright() as pw:
   b=pw.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe');page=b.new_page(viewport={'width':1360,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base);page.locator('#login input').fill('main-cloud-test');page.locator('#login button').click()
   expect(page.locator('#main-upload-empty')).to_be_attached()
   page.locator('label:has(#main-upload-empty)').click();expect(page.locator('.reference-source-menu')).to_contain_text('本地上传云盘上传')
   page.locator('.reference-source-menu [data-cloud]').click();expect(page.locator('.drive-picker')).to_be_visible()
   expect(page.locator('[data-picker-count]')).to_contain_text('只能选择 1 张')
   page.locator('[data-picker-file]').filter(has_text='red.png').click()
   page.locator('[data-picker-file]').filter(has_text='blue.png').click()
   expect(page.locator('[data-picker-count]')).to_contain_text('已选择1张')
   page.locator('[data-cancel]').click();assert page.locator('#main-empty').is_visible()
   page.locator('label:has(#main-upload-empty)').click();page.locator('.reference-source-menu [data-cloud]').click()
   page.locator('[data-picker-file]').filter(has_text='red.png').click();page.locator('[data-confirm]').click()
   expect(page.locator('#main-empty')).to_be_hidden();expect(page.locator('#main-canvas')).to_be_visible()
   assert page.locator('#reference-count').inner_text()=='0 / 12'
   page.reload();expect(page.locator('#main-empty')).to_be_hidden()
   page.locator('label:has(#main-upload)').click();expect(page.locator('.reference-source-menu')).to_be_visible()
   page.locator('[data-cloud]').click();page.locator('[data-picker-file]').filter(has_text='blue.png').click();page.locator('[data-confirm]').click()
   expect(page.locator('#main-empty')).to_be_hidden()
   assert not errors,errors
   print({'empty_main_cloud':True,'cancel_no_change':True,'single_select':True,'persisted_after_reload':True,'replace_main_cloud':True,'errors':errors,'paid_calls':0})
   b.close()
 finally:
  proc.terminate();proc.wait(timeout=10);log.close()
