"""Read-only browser acceptance of frozen text regions on original history image."""
import os,subprocess,sys,tempfile,time,io,json,sqlite3
from pathlib import Path
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='history-green-',ignore_cleanup_errors=True) as data:
 env={**os.environ,'DATA_DIR':data,'SITE_PASSWORD':'green-regions-test','PORT':'8841','GENERATION_MODE':'simulation'}
 log=open(Path(data)/'server.log','w',encoding='utf-8');proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
 base='http://127.0.0.1:8841'
 try:
  for _ in range(120):
   try:
    if httpx.get(base+'/api/health',trust_env=False,timeout=1).status_code==200:break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('server not ready')
  with httpx.Client(base_url=base,trust_env=False) as c:
   c.post('/api/login',json={'password':'green-regions-test'}).raise_for_status()
   buf=io.BytesIO();Image.new('RGB',(600,400),'white').save(buf,'PNG')
   main=c.post('/api/assets',files={'file':('original.png',buf.getvalue(),'image/png')}).json()['id']
   state={'id':'fixture','revision':1,'name':'历史文字绿区验证','main_image':main,'references':[],'instructions':'','full_image_refs':[],'mappings':[],'text_edits':[{'id':'text:fixture:1','image_id':main,'image_version':1,'source':'ocr','original_text':'OLD','replacement':'NEW','bbox':[.2,.3,.5,.5],'polygon':[[.2,.3],[.5,.3],[.5,.5],[.2,.5]],'confidence':.99,'needs_review':False}],'next_display_index':1,'generation_model':'gpt-image-2.5-flare-eco','source_strategy':'context-crop'}
   jid='historygreenfixture0000000000000000'
   with sqlite3.connect(Path(data)/'editor.sqlite') as db:
    db.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result) VALUES(?,?,?,?,?,?)',(jid,jid,time.time(),'simulated',json.dumps({'state':state,'compiled':{'inputs':[main],'bindings':[],'prompt':'fixture','execution':'simulation','strategy':'context-crop','mask_mode':'disabled'},'mode':'simulation','model':state['generation_model']}),json.dumps({'assets':[],'calls':0,'message':'fixture'})))
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe');page=browser.new_page(viewport={'width':1360,'height':950});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base+'/history/'+jid);page.locator('#login input').fill('green-regions-test');page.locator('#login button').click()
   assert page.locator('.history-text-regions').is_hidden()
   page.get_by_role('button',name='查看编辑区域').click()
   region=page.locator('.history-text-region');expect(region).to_have_count(1);expect(region).to_be_visible()
   color=region.evaluate('(e)=>getComputedStyle(e).borderColor');assert color=='rgb(22, 163, 74)',color
   region.click();expect(page.locator('#text-region-editor textarea').first).to_have_value('OLD');expect(page.locator('#text-region-editor textarea').last).to_have_value('NEW')
   assert not errors,errors
   print({'green_region':True,'frozen_text_opened':True,'console_errors':errors,'generation_requests':0})
   browser.close()
 finally:
  proc.terminate();proc.wait(timeout=10);log.close()
