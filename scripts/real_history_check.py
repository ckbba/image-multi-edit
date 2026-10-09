"""Two phases around an actual server restart; no generation calls.
Run --phase before, restart the server, then --phase after.
Restores research records into new drafts without changing immutable history.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'后端代码'))
import config,store
parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['before','after'],required=True);args=parser.parse_args()
OUT=ROOT/'evidence';BASE='http://127.0.0.1:8787'
def digest(value):return hashlib.sha256(value).hexdigest()
with store.db() as con:
    rows=con.execute('SELECT id,snapshot,result FROM jobs WHERE deleted=0 ORDER BY id').fetchall()
baseline={r['id']:{'snapshot_sha256':digest(r['snapshot'].encode()),'result_sha256':digest(r['result'].encode())} for r in rows}
if args.phase=='before':
    (OUT/'real-history-before.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
    print('Captured immutable hashes for',len(baseline),'histories');sys.exit()
assert baseline==json.loads((OUT/'real-history-before.json').read_text()),'History changed across restart'
checks=[]
with httpx.Client(base_url=BASE,trust_env=False,timeout=120) as client:
    client.post('/api/login',json={'password':config.PASSWORD}).raise_for_status()
    for row in rows:
        jid=row['id'];job=client.get('/api/jobs/'+jid).json();state=job['snapshot']['state']
        assets={state['main_image'],*state['references'],*job['result']['assets']}
        for mapping in state['mappings']:
            for side in ('source','target'):
                assets.add(mapping[side]['mask_id'])
        for aid in assets:
            r=client.get('/api/assets/'+aid+'?download=true');r.raise_for_status()
            assert digest(r.content)==store.asset(aid)['sha256']
        restored=client.post('/api/jobs/'+jid+'/restore',json={});restored.raise_for_status();draft=restored.json()
        assert draft['id']!=state['id'] and draft['main_image']==state['main_image']
        assert [m['id'] for m in draft['mappings']]==[m['id'] for m in state['mappings']]
        checks.append({'history_id':jid,'assets_verified':len(assets),'new_draft_id':draft['id']})
    chosen=json.loads((OUT/'real/04-two-bag-shoes.json').read_text(encoding='utf-8'))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1100},accept_downloads=True)
        errors=[];generation_requests=[];external_requests=[]
        def restrict(route):
            if not route.request.url.startswith(BASE):external_requests.append(route.request.url);route.abort()
            else:route.continue_()
        context.route('**/*',restrict)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:generation_requests.append(r.url) if r.method=='POST' and r.url==BASE+'/api/jobs' else None)
        page.goto(BASE+'/history/'+chosen['history_id'])
        page.locator('input[name=password]').fill(config.PASSWORD);page.get_by_role('button',name='进入工作室 →').click()
        expect(page.locator('.status-badge')).to_have_text('已完成')
        page.reload();expect(page.locator('#result-image')).to_be_visible()
        page.locator('#zoom').click();expect(page.locator('#image-viewer')).to_be_visible();page.locator('#viewer-close').click()
        with page.expect_download() as event:page.locator('#download').click()
        download=event.value;download.save_as(str(OUT/'real-history-download.png'))
        assert digest((OUT/'real-history-download.png').read_bytes())==store.asset(chosen['result']['assets'][0])['sha256']
        page.screenshot(path=str(OUT/'real-history-detail.png'),full_page=True)
        page.locator('#continue').click();expect(page.locator('#main-canvas')).to_be_visible();expect(page.locator('.mapping')).to_have_count(0)
        latest=client.get('/api/drafts/latest').json();assert latest['main_image']==chosen['result']['assets'][0]
        page.goto(BASE+'/history/'+chosen['history_id']);page.locator('#restore').click();expect(page.locator('.mapping')).to_have_count(2)
        latest=client.get('/api/drafts/latest').json();assert latest['main_image']==chosen['state']['main_image']
        assert not generation_requests and not external_requests and not errors
        context.close();browser.close()
with store.db() as con:
    final=con.execute('SELECT id,snapshot,result FROM jobs WHERE deleted=0 ORDER BY id').fetchall()
assert {r['id']:{'snapshot_sha256':digest(r['snapshot'].encode()),'result_sha256':digest(r['result'].encode())} for r in final}==baseline
report={'history_count':len(checks),'checks':checks,'browser_console_errors':errors,
    'browser_generation_requests':generation_requests,'browser_external_requests':external_requests,
    'verified':['actual server restart / immutable snapshot and output metadata hashes',
        'all real inputs, references, masks and outputs served as local bytes with matching SHA256',
        'all real records restore into new valid drafts',
        'fresh browser context (no previous cache, cookies or local storage), new login',
        'stable detail reload, zoom and original output download',
        'result as new main with empty mappings; original restore with two mappings',
        'no new jobs and unchanged historical snapshots/results'],
    'limit':'Real upstream URLs were not forcibly expired. A controlled expiry/save-failure integration test covers that state; this check blocks browser external requests and verifies durable bytes.'}
(OUT/'real-history-check.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='checks'}))
