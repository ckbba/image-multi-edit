"""Simulated running job poll must preserve scroll and avoid viewport jumps."""
import io,json,os,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='poll-scroll-',ignore_cleanup_errors=True) as data:
 env={**os.environ,'DATA_DIR':data,'SITE_PASSWORD':'scroll-isolated','PORT':'8831','GENERATION_MODE':'simulation'}
 log=open(Path(data)/'server.log','w',encoding='utf-8');server=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
 base='http://127.0.0.1:8831'
 try:
  for _ in range(120):
   try:
    if httpx.get(base+'/api/health',trust_env=False,timeout=1).status_code==200:break
   except Exception:time.sleep(.1)
  else:raise RuntimeError('server not ready')
  with httpx.Client(base_url=base,trust_env=False) as c:
   c.post('/api/login',json={'password':'scroll-isolated'}).raise_for_status()
   buf=io.BytesIO();Image.new('RGB',(640,900),'steelblue').save(buf,'PNG')
   asset=c.post('/api/assets',files={'file':('original.png',buf.getvalue(),'image/png')}).json()['id']
   draft=c.get('/api/drafts/latest').json();draft['main_image']=asset;draft['instructions']='保留画面';compiled={'inputs':[asset],'bindings':[],'prompt':'fixture','execution':'fixture','strategy':'context-crop','mask_mode':'disabled'}
   jobid='scrollfixture00000000000000000000'
   with sqlite3.connect(Path(data)/'editor.sqlite') as db:
    db.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result) VALUES(?,?,?,?,?,?)',(jobid,jobid,time.time(),'running',json.dumps({'state':draft,'compiled':compiled,'mode':'simulation','model':'fixture'}),json.dumps({'assets':[],'calls':0,'message':'fixture'})))
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe');page=browser.new_page(viewport={'width':1000,'height':700});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base+'/history/'+jobid);page.locator('#login input').fill('scroll-isolated');page.locator('#login button').click()
   expect(page.locator('.generation-wait-status')).to_be_visible()
   page.evaluate('window.scrollTo(0,Math.min(500,document.documentElement.scrollHeight-innerHeight))')
   before=page.evaluate('window.scrollY');assert before>100,before
   page.wait_for_timeout(3400)
   after=page.evaluate('window.scrollY');assert abs(after-before)<3,(before,after)
   expect(page.locator('.generation-wait-status')).to_be_visible()
   assert not errors,errors
   print({'before':before,'after':after,'poll_scroll_preserved':True,'paid_calls':0,'errors':errors})
   browser.close()
 finally:
  server.terminate();server.wait(timeout=10);log.close()
