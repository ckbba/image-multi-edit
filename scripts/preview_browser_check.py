"""Read-only history preview and isolated duplicate-target checks. No paid calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'后端代码'))
import config,store
OUT=ROOT/'output/playwright';OUT.mkdir(parents=True,exist_ok=True)
original_data=config.DATA
jid='c01b4a13e56248eea24d27ff98ddcc06'
job=store.job(jid);state=job['snapshot']['state']
ids={state['main_image'],*state['references'],*job['result']['assets']}
for mapping in state['mappings']:
    for side in ('source','target'):
        ids.add(mapping[side]['mask_id'])
        ids.add(mapping[side].get('edit_region_id',mapping[side]['mask_id']))
metadata=[store.asset(aid) for aid in ids]
config.DATA=Path(tempfile.mkdtemp(prefix='preview-',dir=OUT));store.init()
with store.db() as con:
    for asset in metadata:
        shutil.copy2(original_data/asset['path'],config.DATA/asset['path'])
        thumb=Path(asset['path']).with_suffix('.thumb.png');shutil.copy2(original_data/thumb,config.DATA/thumb)
        con.execute('INSERT INTO assets VALUES(?,?)',(asset['id'],json.dumps(asset)))
    con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result) VALUES(?,?,?,?,?,?)',
        (jid,jid,job['created'],job['status'],json.dumps(job['snapshot']),json.dumps(job['result'])))
draft=store.new_draft(state)
base='http://127.0.0.1:8790'
env={**os.environ,'DATA_DIR':str(config.DATA),'GENERATION_MODE':'simulation','SITE_PASSWORD':'preview-check-password',
     'PORT':'8790','SEGMENTATION_MODEL_DIR':str(config.DATA/'no-model')}
log=(OUT/'preview-server.log').open('w',encoding='utf-8')
process=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
checks=[]
try:
    with httpx.Client(base_url=base,trust_env=False,timeout=10) as client:
        for _ in range(100):
            try:
                if client.get('/api/health').status_code==200:break
            except httpx.ConnectError:time.sleep(.1)
        client.post('/api/login',json={'password':env['SITE_PASSWORD']}).raise_for_status()
        before=client.get('/api/jobs/'+jid).json()
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':871,'height':686})
            errors=[];writes=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') and '/api/login' not in r.url else None)
            page.goto(base+'/history/'+jid)
            page.get_by_role('textbox',name='空间密码').fill(env['SITE_PASSWORD']);page.get_by_role('button',name='进入工作室 →').click()
            page.locator('#view-edit-regions').click()
            inline=page.locator('#history-regions canvas')
            expect(inline).to_have_attribute('data-regions','1,2,3')
            expect(page.locator('.detail-sidebar')).to_be_visible()
            expect(page.locator('#result-image')).to_be_visible()
            page.screenshot(path=str(OUT/'history-regions-inline.png'),full_page=True)
            page.locator('#history-regions select').select_option('1')
            expect(inline).to_have_attribute('data-regions','1')
            page.locator('#view-edit-regions').click()
            expect(page.locator('#history-regions')).to_be_hidden()
            page.locator('#view-edit-regions').click()
            page.locator('#history-regions select').select_option('0')
            expect(inline).to_have_attribute('data-regions','1,2,3')
            inline.click()
            canvas=page.locator('#image-viewer canvas');expect(canvas).to_have_attribute('data-regions','1,2,3')
            expect(canvas).to_have_attribute('data-asset-id',state['main_image'])
            page.screenshot(path=str(OUT/'history-regions-preview.png'))
            checks.append('History button renders original target masks with stable numbers and colors')
            # Verify numbered marker colors are painted at the saved original-image anchors.
            pixels=canvas.evaluate('''(c,mappings)=>mappings.map(m=>{const r=Math.max(c.width,c.height)*.023;const a=m.target.anchor;const p=c.getContext('2d').getImageData(Math.round(a.x*c.width+r*.7),Math.round(a.y*c.height+r*.5),1,1).data;return '#'+Array.from(p).slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('');})''',state['mappings'])
            assert pixels==[m['color'] for m in state['mappings']],pixels
            scale=float(canvas.get_attribute('data-scale'));box=page.locator('.viewer-stage').bounding_box()
            page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.wheel(0,-600)
            page.wait_for_function('(previous)=>Number(document.querySelector("#image-viewer canvas").dataset.scale)>previous',arg=scale)
            transform=canvas.evaluate('c=>c.style.transform');page.mouse.down();page.mouse.move(box['x']+box['width']/2+65,box['y']+box['height']/2+55,steps=5);page.mouse.up()
            assert canvas.evaluate('c=>c.style.transform')!=transform
            page.locator('#viewer-fit').click();assert abs(float(canvas.get_attribute('data-scale'))-scale)<.001
            checks.append('Mouse wheel zoom, drag pan and fit-to-window work')
            page.get_by_role('button',name='参考图 1',exact=True).click();expect(canvas).to_have_attribute('data-regions','1')
            page.locator('#viewer-regions').uncheck();expect(canvas).to_have_attribute('data-regions','')
            page.keyboard.press('Escape');expect(page.locator('#image-viewer')).to_have_count(0)
            page.locator('.snapshot-images img').last.click();expect(canvas).to_have_attribute('data-asset-id',state['references'][-1])
            page.locator('#viewer-close').click()
            page.locator('#result-image').click();expect(canvas).to_have_attribute('data-asset-id',job['result']['assets'][0])
            expect(canvas).to_have_attribute('data-regions','');page.locator('#viewer-close').click()
            page.goto(base+'/history');page.locator('.history-card img').first.click()
            expect(page.locator('#view-edit-regions')).to_be_visible()
            expect(page.locator('#image-viewer')).to_have_count(0)
            expect(page.locator('#history-regions')).to_be_hidden()
            checks.append('History thumbnails open the full detail page; saved regions toggle inline, with source selection and zoom')
            assert not writes,writes
            assert client.get('/api/jobs/'+jid).json()==before
            assert client.get('/api/drafts/latest').json()==draft
            checks.append('Viewing and toggling overlays perform no writes and leave history/draft unchanged')
            page.goto(base);expect(page.locator('.mapping')).to_have_count(3)
            page.locator('#preview-main').click();expect(canvas).to_have_attribute('data-asset-id',state['main_image']);page.locator('#magic-close').click()
            page.locator('#main-canvas').click(position={'x':20,'y':20});expect(canvas).to_be_visible();page.locator('#magic-close').click()
            (OUT/'preview-editor-structure.txt').write_text(page.locator('body').aria_snapshot()+'\nERRORS: '+json.dumps(errors),encoding='utf-8')
            page.get_by_title('参考图 1',exact=True).click();expect(canvas).to_have_attribute('data-asset-id',state['references'][0]);page.locator('#magic-close').click()
            # Manual selection + real mouse drag must keep working, including near-duplicate targets.
            def point(side,x,y):
                b=page.locator('#'+side+'-canvas').bounding_box();meta=store.asset(state['main_image'] if side=='main' else state['references'][0]);s=min(b['width']/meta['width'],b['height']/meta['height'])
                return b['x']+(b['width']-meta['width']*s)/2+x*meta['width']*s,b['y']+(b['height']-meta['height']*s)/2+y*meta['height']*s
            def polygon(side,points):
                page.locator('#preview-'+side).click()
                expect(canvas).to_be_visible()
                expect(page.locator('.viewer-gallery')).to_be_hidden()
                expect(page.locator('.viewer-head')).to_be_hidden()
                scale=float(canvas.get_attribute('data-scale'))
                b=canvas.bounding_box();page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2);page.mouse.wheel(0,-65)
                page.wait_for_function('(s)=>Number(document.querySelector("#image-viewer canvas").dataset.scale)>s',arg=scale)
                page.locator('#magic-brush').click()
                b=canvas.bounding_box()
                def zoom_point(x,y):return b['x']+x*b['width'],b['y']+y*b['height']
                page.mouse.move(*zoom_point(*points[0]));page.mouse.down()
                for x,y in points[1:]:page.mouse.move(*zoom_point(x,y),steps=12)
                page.screenshot(path=str(OUT/('magic-brush-'+side+'.png')))
                page.mouse.up()
                expect(page.locator('#image-viewer')).to_have_count(0)
            # Desktop width keeps both panels in view while dragging between them.
            page.set_viewport_size({'width':1440,'height':1100})
            masks_before=sum(u.endswith('/api/masks') for u in writes)
            page.locator('#manual-main').click()
            page.locator('#main-canvas').scroll_into_view_if_needed()
            page.mouse.click(*point('main',.4,.4))
            expect(page.locator('#cancel-select')).to_be_visible()
            page.mouse.move(*point('main',.4,.4));page.mouse.down()
            page.mouse.move(*point('main',.5,.5),steps=10)
            page.keyboard.press('Escape');page.mouse.up()
            expect(page.locator('#cancel-select')).to_have_count(0)
            assert sum(u.endswith('/api/masks') for u in writes)==masks_before
            expect(page.locator('#image-viewer')).to_have_count(0)
            polygon('main',[[.32,.42],[.53,.42],[.53,.55],[.32,.55]])
            polygon('reference',[[.1,.1],[.9,.1],[.9,.9],[.1,.9]])
            assert sum(u.endswith('/api/masks') for u in writes)==masks_before+2
            checks.append('Freehand source and target close on release; clicks and Escape do not save masks')
            page.mouse.move(*point('reference',.5,.5));page.mouse.down();page.mouse.move(*point('main',.43,.48),steps=15);page.mouse.up()
            expect(page.locator('#duplicate-dialog')).to_be_visible()
            page.get_by_role('button',name='保留两条关系').click();expect(page.locator('.mapping')).to_have_count(4)
            expect(page.locator('#save-status')).to_have_text('已保存到私有空间')
            latest=client.get('/api/drafts/latest').json();assert latest['mappings'][:3]==state['mappings']
            for side,expected in [('target',[.32,.42,.53,.55]),('source',[.1,.1,.9,.9])]:
                bbox=store.asset(latest['mappings'][-1][side]['mask_id'])['bbox']
                assert all(abs(a-b)<.01 for a,b in zip(bbox,expected)),(side,bbox)
            checks.append('Minimal single-image preview supports zoomed magic brush; saved source/target coordinates match within 1 percent')
            assert latest['mappings'][-1]['target']['anchor']!=state['mappings'][0]['target']['anchor']
            assert not page.locator('#image-viewer').count()
            assert len(client.get('/api/jobs').json()['items'])==1
            assert client.get('/api/jobs/'+jid).json()==before
            checks.append('Workspace preview preserves drag; overlapping target can keep both mappings and distinct anchors')
            assert not errors,errors
            browser.close()
        (OUT/'preview-check.json').write_text(json.dumps({'checks':checks,'console_errors':errors,'generation_requests':[u for u in writes if u==base+'/api/jobs'],'source_history':jid},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'checks':checks,'console_errors':errors},ensure_ascii=True))
finally:
    process.terminate();process.wait(timeout=15);log.close();config.DATA=original_data
assert store.job(jid)==job,'Real history must remain unchanged'
