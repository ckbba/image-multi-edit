"""Real API-to-browser warm selection latency; does not call image generation."""
import json,os,subprocess,sys,time
from pathlib import Path
import httpx
import numpy as np
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence'
sys.path.insert(0,str(ROOT/'后端代码'))
import config

with httpx.Client(base_url='http://127.0.0.1:8787',trust_env=False,timeout=180) as client:
    client.post('/api/login',json={'password':config.PASSWORD}).raise_for_status()
    sample=ROOT/'evidence/samples/bag.png'
    meta=client.post('/api/assets',files={'file':('bag.png',sample.read_bytes(),'image/png')}).json()
    start=time.perf_counter();pre=client.post('/api/segmentation/prepare',json={'image_id':meta['id']}).json();cold=(time.perf_counter()-start)*1000
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True);context=b.new_context();context.add_cookies([{'name':'editor_session','value':client.cookies.get('editor_session'),'domain':'127.0.0.1','path':'/'}]);page=context.new_page();page.goto('http://127.0.0.1:8787')
        measurements=[]
        for i in range(20):
            # Includes request, queue, native-mask persistence, download, decode and visible canvas paint.
            value=page.evaluate('''async ({id,x,y})=>{const start=performance.now();const r=await fetch('/api/segmentation/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_id:id,x,y})});const d=await r.json();if(!d.candidates?.length)throw new Error('no candidates');const im=new Image();im.src='/api/assets/'+d.candidates[0].id;await im.decode();const c=document.createElement('canvas');c.width=512;c.height=342;document.body.append(c);c.getContext('2d').drawImage(im,0,0,512,342);await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);const result={visible_ms:performance.now()-start,server_ms:d.elapsed_ms,cached:d.cached};c.remove();return result;}''',{'id':meta['id'],'x':.35+i*.012,'y':.47})
            measurements.append(value)
        result={'hardware':'Quadro T2000 Max-Q / Windows / localhost','image_size':[meta['width'],meta['height']], 'n':20,'prepare_wall_ms':cold,'prepare':pre,'dwell_ms':120,'p50_ms':float(np.percentile([v['visible_ms'] for v in measurements],50)),'p95_ms':float(np.percentile([v['visible_ms'] for v in measurements],95)),'measurements':measurements,'note':'Browser transport/decode/paint harness; main editor first-hover measurement in output/playwright/browser-check.json. Dwell reported separately; add 120ms for pause-to-visible total.'}
        (OUT/'performance-final.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k!='measurements'}));b.close()
