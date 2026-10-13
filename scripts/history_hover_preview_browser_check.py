"""Zero-fee isolated acceptance for historical frozen/model and mask previews."""
import io, json, os, sqlite3, subprocess, sys, time
from pathlib import Path
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'history-hover-preview'; DATA=OUT/'data'; BASE='http://127.0.0.1:8796'; PASSWORD='history-hover-isolated-password'
ENV={**os.environ,'DATA_DIR':str(DATA),'SITE_PASSWORD':PASSWORD,'PORT':'8796','GENERATION_MODE':'simulation'}
OUT.mkdir(parents=True,exist_ok=True)
log=(OUT/'server.log').open('w',encoding='utf-8')
proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=ENV,stdout=log,stderr=log)

def wait_server():
 for _ in range(100):
  try:
   if httpx.get(BASE+'/api/health',trust_env=False,timeout=1).status_code==200:return
  except Exception:pass
  time.sleep(.1)
 raise RuntimeError('isolated server did not start')

def upload(client,name,color):
 buf=io.BytesIO();Image.new('RGB',(240,160),color).save(buf,'PNG')
 r=client.post('/api/assets',files={'file':(name,buf.getvalue(),'image/png')});r.raise_for_status();return r.json()['id']

def db_state():
 with sqlite3.connect(DATA/'editor.sqlite') as db:
  return {'jobs':[tuple(r) for r in db.execute('SELECT id,idem,created,status,snapshot,result FROM jobs ORDER BY id').fetchall()],'assets':[tuple(r) for r in db.execute('SELECT id,meta FROM assets ORDER BY id').fetchall()]}

try:
 wait_server()
 with httpx.Client(base_url=BASE,trust_env=False) as c:
  c.post('/api/login',json={'password':PASSWORD}).raise_for_status()
  main=upload(c,'main.png','#4169a8');source=upload(c,'source.png','#c4475d');frozen=upload(c,'frozen-model-input.png','#29a36a')
  source_mask=c.post('/api/masks',json={'image_id':source,'points':[[.2,.2],[.55,.2],[.55,.45],[.38,.45],[.38,.72],[.2,.72]]}).json()['id']
  source_target=c.post('/api/masks',json={'image_id':main,'points':[[.48,.18],[.8,.18],[.8,.7],[.48,.7]]}).json()['id']
  local_mask=c.post('/api/masks',json={'image_id':main,'points':[[.1,.5],[.34,.5],[.34,.88],[.1,.88]]}).json()['id']
  state={'id':'history-fixture','revision':1,'name':'历史悬停零付费验收','main_image':main,'references':[source],'instructions':'保留构图','full_image_refs':[], 'text_edits':[], 'next_display_index':3,'generation_model':'gpt-image-2.5-flare-eco','source_strategy':'context-crop','mappings':[
   {'id':'source-map','kind':'reference-edit','display_index':1,'color':'#8b5cf6','mode':'replace','requirement':'换成参考元素','source':{'image_id':source,'image_version':1,'mask_id':source_mask,'anchor':{'x':.3,'y':.3},'label':'元素'},'target':{'image_id':main,'image_version':1,'mask_id':source_target,'edit_region_id':source_target,'anchor':{'x':.62,'y':.35}}},
   {'id':'local-map','kind':'main-edit','display_index':2,'color':'#3b82f6','mode':'replace','requirement':'改成金色','source':None,'target':{'image_id':main,'image_version':1,'mask_id':local_mask,'edit_region_id':local_mask,'anchor':{'x':.22,'y':.68}}}]}
  compiled={'inputs':[main,frozen],'bindings':[{'kind':'element','mapping_id':'source-map','display_index':1,'input_index':2,'input_asset_id':frozen},{'kind':'main-edit','mapping_id':'local-map','display_index':2,'mask_id':local_mask}], 'strategy':'context-crop','compiler_version':'fixture'}
  jid='historyhoverfixture0000000000000000'
  with sqlite3.connect(DATA/'editor.sqlite') as db:
   db.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result) VALUES(?,?,?,?,?,?)',(jid,jid,time.time(),'simulated',json.dumps({'state':state,'compiled':compiled,'mode':'simulation','model':state['generation_model']}),json.dumps({'calls':0,'cost_usd':0,'message':'fixture'})))
  before_jobs=c.get('/api/jobs').json()['items']; before_state=db_state()
 errors=[]; requests=[]
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1360,'height':1000})
  page.on('pageerror',lambda error:errors.append(str(error)));page.on('request',lambda req:requests.append({'method':req.method,'url':req.url}))
  page.goto(BASE);page.get_by_role('textbox',name='空间密码').fill(PASSWORD);page.get_by_role('button',name='进入工作室 →').click();page.goto(BASE+'/history/'+jid)
  page.get_by_role('button',name='查看编辑区域').click();expect(page.locator('[data-history-requirement="source-map"]')).to_be_visible()
  bubble=page.locator('[data-history-requirement="source-map"]');bubble.dispatch_event('mouseenter');expect(page.locator('.history-frozen-preview')).to_contain_text('当时实际模型输入 · IMAGE 2',timeout=10000)
  frozen_src=page.locator('.history-frozen-preview img').get_attribute('src');assert frozen in frozen_src and source not in frozen_src,(frozen_src,frozen,source)
  page.screenshot(path=str(OUT/'bubble-frozen-input.png'),full_page=True)
  bubble.click();expect(page.locator('.history-requirement-popover')).to_contain_text('只读历史快照')
  source_token=page.locator('[data-mapping-preview="source-map"]');source_token.dispatch_event('mouseenter');expect(page.locator('.history-selected-preview')).to_contain_text('当时选区预览',timeout=10000);expect(page.locator('.history-selected-preview')).to_contain_text('源参考图蒙版元素')
  canvas=page.locator('.history-selected-preview canvas');size=canvas.evaluate("(c)=>{const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let transparent=0;for(let i=3;i<d.length;i+=4)if(d[i]===0)transparent++;return {w:c.width,h:c.height,transparent}}") ;assert size['transparent']>0,size
  page.screenshot(path=str(OUT/'source-mask-token.png'),full_page=True)
  local_token=page.locator('[data-mapping-preview="local-map"]');page.mouse.move(1300,50);local_token.dispatch_event('focus');expect(page.locator('.history-selected-preview')).to_contain_text('主图目标蒙版元素 · 无单独参考图',timeout=10000)
  page.screenshot(path=str(OUT/'main-local-mask-token.png'),full_page=True)
  page.keyboard.press('Escape');expect(page.locator('#asset-hover-preview')).to_be_hidden()
  browser.close()
 with httpx.Client(base_url=BASE,trust_env=False) as c:
  c.post('/api/login',json={'password':PASSWORD}).raise_for_status();after_jobs=c.get('/api/jobs').json()['items']
 result={'job_id':jid,'generation_calls':0,'paid_calls':0,'jobs_unchanged':before_jobs==after_jobs,'db_state_unchanged':before_state==db_state(),'non_get_requests_after_login':[r for r in requests if r['method']!='GET' and not r['url'].endswith('/api/login')],'frozen_input_url':frozen_src,'frozen_asset_id':frozen,'selected_canvas':size,'console_errors':errors,'screenshots':[str(OUT/p) for p in ['bubble-frozen-input.png','source-mask-token.png','main-local-mask-token.png']]}
 assert result['jobs_unchanged'] and result['db_state_unchanged'] and not result['non_get_requests_after_login'] and not errors,result
 (OUT/'check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:
 proc.terminate()
 try:proc.wait(timeout=15)
 except subprocess.TimeoutExpired:proc.kill()
 log.close()
