"""Isolated zero-cost browser acceptance for history UI changes."""
import io, json, os, subprocess, sys, time
from pathlib import Path
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'history-ui-8794'; DATA=OUT/'data'; BASE='http://127.0.0.1:8794'; PASSWORD='history-ui-isolated-password'
ENV={**os.environ,'DATA_DIR':str(DATA),'SITE_PASSWORD':PASSWORD,'PORT':'8794','GENERATION_MODE':'simulation','TZ':'Asia/Shanghai'}
OUT.mkdir(parents=True,exist_ok=True)
log=(OUT/'server.log').open('w',encoding='utf-8')
proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=ENV,stdout=log,stderr=log)

def wait_server():
    for _ in range(120):
        try:
            if httpx.get(BASE+'/api/health',trust_env=False,timeout=1).status_code==200:return
        except Exception:pass
        time.sleep(.1)
    raise RuntimeError('8794 server did not start')

def upload(client,color):
    buf=io.BytesIO();Image.new('RGB',(96,72),color).save(buf,'PNG')
    response=client.post('/api/assets',files={'file':('fixture.png',buf.getvalue(),'image/png')});response.raise_for_status();return response.json()['id']

def job(client,name,main,ref,key):
    state=client.post('/api/drafts').json();state.update(name=name,main_image=main,references=[ref],instructions='零付费验收',full_image_refs=[{'id':'whole-'+key,'image_id':ref,'label':'验收图','purpose':'构图参考'}])
    saved=client.put('/api/drafts/'+state['id'],json=state);saved.raise_for_status()
    response=client.post('/api/jobs',json={'draft_id':state['id'],'revision':saved.json()['revision'],'idempotency_key':key});response.raise_for_status();return response.json()['id']

try:
    wait_server()
    with httpx.Client(base_url=BASE,trust_env=False) as api:
        api.post('/api/login',json={'password':PASSWORD}).raise_for_status();main=upload(api,'navy');ref=upload(api,'orange')
        ids=[job(api,f'8794 历史 {i:02d}',main,ref,f'fixture-{i:02d}') for i in range(22)]
        now=time.time();
        with __import__('sqlite3').connect(DATA/'editor.sqlite') as db:
            for i,jid in enumerate(ids): db.execute('UPDATE jobs SET created=? WHERE id=?',(now-(86400 if i>=20 else 0)-i,jid))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1050});page=context.new_page();errors=[];requests=[]
        page.on('console',lambda msg: errors.append(msg.text) if msg.type=='error' else None)
        page.on('request',lambda req: requests.append((req.method,req.url,req.post_data)))
        page.goto(BASE);page.get_by_role('textbox',name='空间密码').fill(PASSWORD);page.get_by_role('button',name='进入工作室 →').click();page.goto(BASE+'/history');errors.clear()
        expect(page.locator('.history-card-shell')).to_have_count(20);expect(page.locator('.history-day')).to_have_count(1)
        target=page.locator(f'.history-card-shell[data-job-id="{ids[0]}"]');rename=target.get_by_role('button',name='重命名历史「8794 历史 00」');rename.click();field=target.get_by_role('textbox',name='历史名称');field.fill('不应保存');field.press('Escape');expect(target.get_by_role('heading',name='8794 历史 00')).to_be_visible();assert not [r for r in requests if r[0]=='PATCH']
        rename.click();field=target.get_by_role('textbox',name='历史名称');field.fill('8794 重命名确认');field.press('Enter');expect(target.get_by_role('heading',name='8794 重命名确认')).to_be_visible()
        patch_calls=[r for r in requests if r[0]=='PATCH'];assert len(patch_calls)==1 and json.loads(patch_calls[0][2])=={'name':'8794 重命名确认'}
        search=page.get_by_role('searchbox',name='搜索历史标题');search.fill('8794 重命名确认');search.press('Enter');expect(page.locator('.history-card-shell')).to_have_count(1);assert ids[0] in page.locator('.history-card-shell').get_attribute('data-job-id')
        search.fill('8794 历史 00');search.press('Enter');expect(page.locator('.history-card-shell')).to_have_count(0)
        search.fill('');search.press('Enter');expect(page.locator('.history-card-shell')).to_have_count(20);page.get_by_role('button',name='加载更多（共 22 条）').click();expect(page.locator('.history-card-shell')).to_have_count(22);expect(page.locator('.history-day')).to_have_count(2)
        page.screenshot(path=str(OUT/'history-grouped-renamed.png'),full_page=True)
        target_delete=page.locator(f'.history-card-shell[data-job-id="{ids[1]}"]');delete=target_delete.get_by_role('button',name='删除历史「8794 历史 01」');target_delete.hover();page.once('dialog',lambda d:d.dismiss());delete.click();expect(page).to_have_url(BASE+'/history')
        with httpx.Client(base_url=BASE,trust_env=False) as verify:
            verify.post('/api/login',json={'password':PASSWORD}).raise_for_status();detail=verify.get('/api/jobs/'+ids[0]).json();found=verify.get('/api/jobs',params={'q':'8794 重命名确认'}).json()
            result={'rename_exact_patch':len(patch_calls)==1,'cancel_zero_patch':True,'display_name':detail['name'],'immutable_snapshot_name':detail['snapshot']['state']['name'],'search_new_count':found['count'],'search_old_count':verify.get('/api/jobs',params={'q':'8794 历史 00'}).json()['count'],'calls':detail['result']['calls'],'date_groups':page.locator('.history-day').count(),'cards_after_load_more':page.locator('.history-card-shell').count(),'delete_cancel_no_navigation':page.url==BASE+'/history','console_errors':errors,'screenshot':str(OUT/'history-grouped-renamed.png')}
        assert result['display_name']=='8794 重命名确认' and result['immutable_snapshot_name']=='8794 历史 00' and result['search_new_count']==1 and result['search_old_count']==0 and result['calls']==0 and result['date_groups']==2 and not errors,result
        (OUT/'evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));browser.close()
finally:
    proc.terminate()
    try:proc.wait(timeout=15)
    except subprocess.TimeoutExpired:proc.kill()
    log.close()
