"""Read-only regression probe for the 2026-10-12 02:45:54 history UI."""
import hashlib, io, json, math
from pathlib import Path
import requests
from PIL import Image
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:8791'
JOB='d38777528e114fbea2769acc14059c17'
OUT=Path(__file__).resolve().parents[1]/'output'/'history-marker-fix'
OUT.mkdir(parents=True,exist_ok=True)

def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def mask_bbox(data):
    im=Image.open(io.BytesIO(data)).convert('RGBA').getchannel('A')
    box=im.point(lambda p: 255 if p else 0).getbbox()
    return {'size':list(im.size),'bbox':list(box) if box else None,'sha256':hashlib.sha256(data).hexdigest()}

s=requests.Session(); assert s.post(BASE+'/api/login',json={'password':'demo123'}).ok
before=s.get(BASE+'/api/jobs/'+JOB); before.raise_for_status(); job=before.json(); state=job['snapshot']['state']
original_meta=s.get(BASE+'/api/assets/'+state['main_image']+'/meta').json()
masks={str(m['display_index']):mask_bbox(s.get(BASE+'/api/assets/'+m['target']['mask_id']).content) for m in state['mappings']}
expected=sorted(m['display_index'] for m in state['mappings'])
assert expected==[2,4,5,6,7], expected
report={'job':JOB,'snapshot_sha256_before':canonical(job['snapshot']),'original_meta':original_meta,'stored_anchors':{str(m['display_index']):m['target']['anchor'] for m in state['mappings']},'mask_evidence':masks,'viewports':[]}

with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]; writes=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:writes.append((r.method,r.url)) if r.method not in ('GET','HEAD','OPTIONS') else None)
    page.goto(BASE+'/history/'+JOB); page.locator('input[name=password]').fill('demo123'); page.get_by_role('button',name='进入工作室 →').click()
    expect(page.locator('#result-image')).to_be_visible()
    for index,(width,height) in enumerate(((1440,1000),(980,900)),1):
        page.set_viewport_size({'width':width,'height':height})
        page.locator('#view-edit-regions').click() if page.locator('#history-regions').is_hidden() else None
        expect(page.locator('.history-original-layer canvas')).to_be_visible()
        expect(page.locator('.history-requirement-bubbles button')).to_have_count(5)
        metrics=page.evaluate("""() => {
          const layer=document.querySelector('.history-original-layer'), canvas=layer.querySelector('canvas');
          const lr=layer.getBoundingClientRect(), cr=canvas.getBoundingClientRect();
          return {layer:{x:lr.x,y:lr.y,w:lr.width,h:lr.height},canvas:{x:cr.x,y:cr.y,w:cr.width,h:cr.height},markers:[...document.querySelectorAll('.history-requirement-bubbles button')].map(b=>{const r=b.getBoundingClientRect();return {n:Number(b.textContent),x:r.x+r.width/2,y:r.y+r.height/2,dot:!!b.querySelector('i')}})};
        }""")
        nums=sorted(m['n'] for m in metrics['markers']); assert nums==expected and all(m['dot'] for m in metrics['markers'])
        deltas={}
        for marker in metrics['markers']:
            a=report['stored_anchors'][str(marker['n'])]
            ex=metrics['canvas']['x']+a['x']*metrics['canvas']['w']; ey=metrics['canvas']['y']+a['y']*metrics['canvas']['h']
            delta=math.hypot(marker['x']-ex,marker['y']-ey); assert delta<=2, (marker,ex,ey,delta)
            deltas[str(marker['n'])]=delta
        page.locator('.history-requirement-bubbles button',has_text='2').click()
        expect(page.locator('.history-requirement-popover')).to_contain_text('猫在男人肩膀上')
        page.screenshot(path=str(OUT/f'{index:02d}-{width}-regions.png'),full_page=True)
        report['viewports'].append({'width':width,'height':height,'numbers':nums,'max_alignment_error_px':max(deltas.values()),'alignment_error_px':deltas})
        page.locator('#view-edit-regions').click()
    page.locator('#slider-toggle').click(); expect(page.locator('#comparison-slider')).to_be_visible()
    page.locator('#comparison-slider').evaluate("e=>{e.value='50';e.dispatchEvent(new Event('input',{bubbles:true}))}")
    clip=page.locator('.history-original-layer').evaluate("e=>getComputedStyle(e).clipPath")
    assert '50%' in clip
    expect(page.locator('.history-requirement-bubbles button')).to_have_count(5)
    page.screenshot(path=str(OUT/'03-slider-50.png'),full_page=True)
    whole=page.locator('.snapshot-mapping.whole img'); expect(whole).to_have_count(1)
    size=whole.evaluate("e=>{const r=e.getBoundingClientRect();return {w:r.width,h:r.height,maxWidth:getComputedStyle(e).maxWidth}}")
    assert size['w']<=60.1 and size['h']<=67.1, size
    report.update({'slider_clip_path':clip,'sidebar_whole_image_size':size,'page_errors':errors,'non_get_requests_after_login':writes[1:]})
    browser.close()

after=s.get(BASE+'/api/jobs/'+JOB).json(); report['snapshot_sha256_after']=canonical(after['snapshot'])
report['stored_data_unchanged']=report['snapshot_sha256_before']==report['snapshot_sha256_after']
assert report['stored_data_unchanged'] and not errors and not report['non_get_requests_after_login']
(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
