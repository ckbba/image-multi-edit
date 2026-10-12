import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:8791'
IMAGE=Path('C:/Users/Lenovo/AppData/Roaming/Hermes/composer-images/image_5b3b70.png')
OUT=Path('output/playwright')
OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
    job_posts=[]
    page.on('request',lambda r: job_posts.append(r.url) if r.method=='POST' and r.url.endswith('/api/jobs') else None)
    page.goto(BASE)
    page.locator('input[name=password]').fill('ocr-test-local')
    page.locator('#login button[type=submit]').click()
    expect(page.locator('#main-upload-empty')).to_be_attached()
    with page.expect_response(lambda r:r.url.startswith(BASE+'/api/assets') and r.request.method=='POST'):
        page.locator('#main-upload-empty').set_input_files(str(IMAGE))
    page.wait_for_function("async()=>{const r=await fetch('/api/drafts/latest');const d=await r.json();return !!d.main_image}")
    expect(page.locator('#text-edit')).to_be_visible(timeout=15000)
    before=page.request.get(BASE+'/api/jobs').json()['items']
    page.locator('#text-edit').click()
    expect(page.locator('#text-edit-dialog')).to_be_visible(timeout=90000)
    rows=page.locator('[data-text-row]')
    expect(rows).to_have_count(3)
    originals=rows.locator('[data-original]').evaluate_all("els=>els.map(e=>e.value)")
    assert originals==['DesignKit','随时随地随行好声音','精工金属提扣配搭声学织物网面，一手掌握的澎湃音浪'], originals
    rows.nth(0).locator('[data-replacement]').fill('拾影 Design')
    rows.nth(1).locator('[data-replacement]').fill('随身好声音')
    rows.nth(0).hover()
    expect(page.locator('.text-highlight-layer i')).to_be_visible()
    page.screenshot(path=str(OUT/'text-edit-recognition.png'),full_page=True)
    page.locator('#commit-text-edits').click()
    expect(page.locator('.composer-fragment.text-edit')).to_have_count(2)
    expect(page.locator('#generate')).to_be_enabled()
    assert job_posts==[],job_posts
    assert page.request.get(BASE+'/api/jobs').json()['items']==before
    draft=page.request.get(BASE+'/api/drafts/latest').json()
    assert len(draft['text_edits'])==2 and draft['mappings']==[] and draft['references']==[]
    page.screenshot(path=str(OUT/'text-edit-composer.png'),full_page=True)
    page.locator('#generate').click()
    page.wait_for_url('**/history/**',timeout=20000)
    page.wait_for_timeout(1000)
    assert len(job_posts)==1,job_posts
    jobs=page.request.get(BASE+'/api/jobs').json()['items']
    assert len(jobs)==len(before)+1 and jobs[0]['status']=='simulated',jobs
    job_id=jobs[0]['id']; detail=page.request.get(BASE+'/api/jobs/'+job_id).json()
    assert len(detail['snapshot']['state']['text_edits'])==2
    assert [b['kind'] for b in detail['snapshot']['compiled']['bindings']]==['text-edit','text-edit']
    page.locator('#restore').click()
    page.wait_for_url(BASE+'/',timeout=10000)
    restored=page.request.get(BASE+'/api/drafts/latest').json()
    assert len(restored['text_edits'])==2
    expect(page.locator('.composer-fragment.text-edit')).to_have_count(2)
    result={'ocr_originals':originals,'draft_text_edits':len(draft['text_edits']),'job_posts':len(job_posts),'job_status':jobs[0]['status'],'compiled_kinds':[b['kind'] for b in detail['snapshot']['compiled']['bindings']],'restored_text_edits':len(restored['text_edits']),'screenshots':[str(OUT/'text-edit-recognition.png'),str(OUT/'text-edit-composer.png')]}
    (OUT/'text-edit-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    browser.close()
