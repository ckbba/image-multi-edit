import json,time,httpx
from pathlib import Path
from PIL import Image
base='http://127.0.0.1:8792'
out=Path('output/playwright')
with httpx.Client(base_url=base,timeout=30,trust_env=False) as c:
 r=c.post('/api/login',json={'password':'ocr-hover-fixture'});r.raise_for_status()
 d=c.get('/api/drafts/latest').json()
 if not d.get('main_image'):
  with open('C:/Users/Lenovo/AppData/Roaming/Hermes/composer-images/image_242fd5.png','rb') as f:
   a=c.post('/api/assets',files={'file':('image_242fd5.png',f,'image/png')}).json()
  d['main_image']=a['id']
 ocr=c.post('/api/text-recognition/'+d['main_image']).json()
 e=next(x for x in ocr['items'] if 'COMING' in x['text'].upper() and 'SOON' in x['text'].upper())
 edit={'id':f"text:{d['main_image']}:1:{e['id']}",'image_id':d['main_image'],'image_version':1,'source':'ocr','original_text':e['text'].strip(),'replacement':'IN CINEMAS NOW','bbox':e['bbox'],'polygon':e.get('polygon',[]),'confidence':e.get('confidence'),'needs_review':bool(e.get('needs_review'))}
 d.update(references=[],mappings=[],full_image_refs=[],instructions='',text_edits=[edit])
 r=c.put('/api/drafts/'+d['id'],json=d);r.raise_for_status();d['revision']=r.json()['revision'];e=edit
 payload={'draft_id':d['id'],'revision':d['revision'],'idempotency_key':f"live-final-{d['id']}-{d['revision']}"}
 r=c.post('/api/jobs',json=payload)
 if r.status_code>=400: print('submit-error',r.status_code,r.text)
 r.raise_for_status();j=r.json(); jid=j['id']; print('submitted',jid)
 deadline=time.time()+420
 while time.time()<deadline:
  j=c.get('/api/jobs/'+jid).json()
  if j['status'] in ('succeeded','failed','unknown','save_failed'): break
  time.sleep(1)
 assert j['status']=='succeeded',j
 comp=j['snapshot']['compiled']; assert len(comp['bindings'])==1 and comp['bindings'][0]['kind']=='text-edit'; assert len(comp['inputs'])==1
 assert 'ANNA KARINA' not in comp['prompt'] and 'JEAN-LUC GODARD' not in comp['prompt']
 assert j['result']['calls']==1 and len(j['result']['assets'])==1
 aid=j['result']['assets'][0]; data=c.get('/api/assets/'+aid+'?download=true').content
 path=out/f'live-text-edit-{jid}.png'; path.write_bytes(data)
 with Image.open(path) as im: size=im.size
 health=[]
 for _ in range(7):
  health.append(c.get('/api/health').json()=={'ok':True});time.sleep(10)
 assert all(health)
 result={'job_id':jid,'status':j['status'],'model_calls':j['result']['calls'],'request_id':j['result'].get('request_id'),'elapsed_s':j['result'].get('elapsed_s'),'cost_usd':j['result'].get('cost_usd'),'output_asset_id':aid,'output_path':str(path.resolve()),'output_size':size,'original':e['original_text'],'replacement':e['replacement'],'bindings':comp['bindings'],'input_count':len(comp['inputs']),'sentinel_absent':True,'health_checks_after_generation':len(health),'health_window_seconds':60}
 (out/'ocr-hover-live-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False))
