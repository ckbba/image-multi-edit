"""IME composition must save only committed global text, never pinyin prefixes."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='composer-ime-',ignore_cleanup_errors=True) as data:
 env={**os.environ,'DATA_DIR':data,'SITE_PASSWORD':'ime-test-password','PORT':'8837','GENERATION_MODE':'simulation'}
 log=open(Path(data)/'server.log','w',encoding='utf-8');server=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
 base='http://127.0.0.1:8837'
 try:
  for _ in range(120):
   try:
    if httpx.get(base+'/api/health',trust_env=False,timeout=1).status_code==200:break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('server not ready')
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe');page=browser.new_page(viewport={'width':1360,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base);page.locator('#login input').fill('ime-test-password');page.locator('#login button').click()
   global_text=page.locator('#composer-editor .composer-fragment.global .composer-text');global_text.click()
   page.evaluate('''() => {const el=document.querySelector('#composer-editor .composer-fragment.global .composer-text');el.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));for(const partial of ['h','hu','hua','huam','画面','画面c','画面尺寸']){el.textContent=partial;el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,inputType:'insertCompositionText'}));}el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}));}''')
   expect(global_text).to_have_text('画面尺寸')
   assert page.locator('#composer-editor .composer-fragment.global .composer-text').inner_text()=='画面尺寸'
   page.locator('#project-name').click();expect(page.locator('#save-status')).to_have_text('已保存到私有空间',timeout=10000)
   with httpx.Client(base_url=base,trust_env=False) as c:
    c.post('/api/login',json={'password':'ime-test-password'}).raise_for_status();assert c.get('/api/drafts/latest').json()['instructions']=='画面尺寸'
   page.reload();expect(global_text).to_have_text('画面尺寸')
   page.evaluate('''() => {const el=document.querySelector('#composer-editor .composer-fragment.global .composer-text');el.textContent='画面尺寸严格参照原图';el.dispatchEvent(new InputEvent('input',{bubbles:true}));}''')
   page.locator('#project-name').click();expect(page.locator('#save-status')).to_have_text('已保存到私有空间')
   page.reload();expect(global_text).to_have_text('画面尺寸严格参照原图')
   with httpx.Client(base_url=base,trust_env=False) as c:
    c.post('/api/login',json={'password':'ime-test-password'}).raise_for_status();state=c.get('/api/drafts/latest').json()
   assert state['instructions']=='画面尺寸严格参照原图',state['instructions']
   assert not errors,errors
   print({'ime_prefixes_saved':False,'committed_text':state['instructions'],'reload_exact':True,'page_errors':errors})
   browser.close()
 finally:
  server.terminate();server.wait(timeout=10);log.close()
