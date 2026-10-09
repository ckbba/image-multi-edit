import copy
import io
import json
import sys
import time
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '后端代码'))
import config
import store
import provider
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'PASSWORD', 'test-private-password')
    monkeypatch.setattr(config, 'MODE', 'simulation')
    monkeypatch.setattr(config, 'SOURCE_STRATEGY', 'full')
    with TestClient(app) as c:
        assert c.post('/api/login', json={'password': config.PASSWORD}).status_code == 200
        yield c


def upload(client, color='blue', size=(120, 80)):
    output = io.BytesIO(); Image.new('RGB', size, color).save(output, 'PNG')
    r = client.post('/api/assets', files={'file': ('fixture.png', output.getvalue(), 'image/png')})
    assert r.status_code == 200, r.text
    return r.json()


def mask(client, aid, x=.1, y=.1, w=.2, h=.2):
    response = client.post('/api/masks', json={'image_id': aid, 'points': [[x,y],[x+w,y],[x+w,y+h],[x,y+h]]})
    assert response.status_code == 200, response.text
    return response.json()


def ready(client):
    a,b=upload(client),upload(client,'red')
    ma,mb=mask(client,a['id']),mask(client,b['id'])
    state=client.post('/api/drafts').json()
    state.update(name='测试项目', main_image=a['id'], references=[b['id']], next_display_index=2,
        mappings=[{'id':'stable-id','display_index':1,'color':store.COLORS[0],'mode':'replace',
          'source':{'image_id':b['id'],'image_version':1,'mask_id':mb['id'],'anchor':{'x':.2,'y':.2},'label':'帽子'},
          'target':{'image_id':a['id'],'image_version':1,'mask_id':ma['id'],'edit_region_id':ma['id'],'anchor':{'x':.2,'y':.2}}}])
    response=client.put('/api/drafts/'+state['id'],json=state)
    assert response.status_code==200,response.text
    state['revision']=response.json()['revision']
    return state


def submit(client,state,key='submission-key-001'):
    r=client.post('/api/jobs',json={'draft_id':state['id'],'revision':state['revision'],'idempotency_key':key})
    assert r.status_code==200,r.text
    jid=r.json()['id']
    for _ in range(100):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] not in ('queued','running','saving'):return job
        time.sleep(.02)
    pytest.fail('Job did not finish')


def test_auth_all_assets_and_history(client):
    state=ready(client);job=submit(client,state)
    client.post('/api/logout')
    for route in ['/api/jobs','/api/jobs/'+job['id'],'/api/assets/'+state['main_image'],'/api/drafts/latest']:
        assert client.get(route).status_code==401
    assert client.post('/api/jobs/'+job['id']+'/restore',json={}).status_code==401
    assert client.get('/history/'+job['id']).status_code==200 # Shell contains no private content.


def test_research_restore_rebinds_old_serial_geometry_only_in_new_draft(client):
    state=ready(client)
    intermediate=upload(client,'green')
    state['main_image']=intermediate['id']
    snapshot={'state':state,'model':'test-model','research_case':'compare-serial-2','compiled':{'strategy':'full'}}
    jid=store.uid()
    with store.db() as con:
        con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result) VALUES(?,?,?,?,?,?)',
            (jid,jid,time.time(),'succeeded',json.dumps(snapshot),json.dumps({'assets':[intermediate['id']],'calls':1})))
    r=client.post('/api/jobs/'+jid+'/restore',json={})
    assert r.status_code==200,r.text
    draft=r.json();store.validate(draft,True)
    assert draft['mappings'][0]['id']==state['mappings'][0]['id']
    assert draft['mappings'][0]['target']['mask_id']!=state['mappings'][0]['target']['mask_id']
    assert client.get('/api/jobs/'+jid).json()['snapshot']==snapshot
    assert len(client.get('/api/jobs').json()['items'])==1


def test_csrf_and_invalid_upload(client):
    assert client.post('/api/drafts',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/assets',files={'file':('x.svg',b'<svg></svg>','image/svg+xml')}).status_code==400
    f=io.BytesIO();Image.new('RGB',(10,10)).save(f,'WEBP',save_all=True,append_images=[Image.new('RGB',(10,10),'red')])
    assert client.post('/api/assets',files={'file':('animated.webp',f.getvalue(),'image/webp')}).status_code==400


def test_snapshot_independent_idempotency_restore(client):
    state=ready(client);job=submit(client,state)
    assert job['status']=='simulated' and job['result']['calls']==0 and not job['result'].get('assets')
    repeat=submit(client,state)
    assert repeat['id']==job['id']
    restored=client.post('/api/jobs/'+job['id']+'/restore',json={}).json()
    assert restored['id']!=state['id'] and restored['mappings']==state['mappings']
    restored['mappings'][0]['source']['label']='新名字'
    assert client.put('/api/drafts/'+restored['id'],json=restored).status_code==200
    assert client.get('/api/jobs/'+job['id']).json()['snapshot']['state']['mappings'][0]['source']['label']=='帽子'
    other=submit(client,client.get('/api/drafts/'+restored['id']).json(),'submission-key-002')
    assert other['id']!=job['id']
    assert len(client.get('/api/jobs').json()['items'])==2


def test_conflicts_and_version_mismatch(client):
    state=ready(client);m=copy.deepcopy(state['mappings'][0]);m.update(id='second',display_index=2,color=store.COLORS[1]);state['mappings'].append(m);state['next_display_index']=3
    r=client.post('/api/validate',json=state);assert r.json()['conflicts'][0]['duplicate']
    r=client.put('/api/drafts/'+state['id'],json=state);assert r.status_code==200
    state['revision']=r.json()['revision']
    r=client.post('/api/jobs',json={'draft_id':state['id'],'revision':state['revision'],'idempotency_key':'invalid-submit-01'})
    assert r.status_code==409 and r.json()['detail']['code']=='target_overlap_confirmation_required'
    assert not client.get('/api/jobs').json()['items']
    confirmed={'draft_id':state['id'],'revision':state['revision'],'idempotency_key':'invalid-submit-01','allow_overlap':True}
    r=client.post('/api/jobs',json=confirmed);assert r.status_code==200,r.text
    job=r.json();assert job['snapshot']['overlap_confirmation']['accepted'] is True
    assert job['snapshot']['overlap_confirmation']['conflicts'][0]['duplicate']
    assert client.post('/api/jobs',json=confirmed).json()['id']==job['id']
    assert len(client.get('/api/jobs').json()['items'])==1
    restored=client.post('/api/jobs/'+job['id']+'/restore',json={}).json()
    assert 'allow_overlap' not in restored
    assert client.post('/api/jobs',json={'draft_id':restored['id'],'revision':0,'idempotency_key':'restore-confirm-01'}).status_code==409
    state['mappings'][0]['source']['image_version']=2
    assert client.post('/api/validate',json=state).status_code==400
    # Explicit overlap consent never bypasses asset/version validity.
    with store.db() as con:
        con.execute('UPDATE drafts SET state=? WHERE id=?',(json.dumps(state),state['id']))
    confirmed['idempotency_key']='invalid-version-confirm'
    assert client.post('/api/jobs',json=confirmed).status_code==400


def test_overlap_consent_still_requires_main_and_mappings(client):
    state=client.post('/api/drafts').json()
    response=client.post('/api/jobs',json={'draft_id':state['id'],'revision':0,
        'idempotency_key':'empty-confirm-submit','allow_overlap':True})
    assert response.status_code==400 and '至少一条' in response.json()['detail']
    assert not client.get('/api/jobs').json()['items']


def test_nonoverlap_and_optimistic_lock(client):
    state=ready(client);old=copy.deepcopy(state);state['name']='new'
    assert client.put('/api/drafts/'+state['id'],json=state).status_code==200
    assert client.put('/api/drafts/'+state['id'],json=old).status_code==409
    assert client.get('/api/drafts/'+state['id']).json()['name']=='new'
    state=client.get('/api/drafts/'+state['id']).json();second=copy.deepcopy(state['mappings'][0]);second.update(id='second',display_index=3,color=store.COLORS[2]);ma=mask(client,state['main_image'],.7,.6)
    second['target'].update(mask_id=ma['id'],edit_region_id=ma['id'],anchor={'x':.8,'y':.7});state['mappings'].append(second);state['next_display_index']=4
    assert client.post('/api/validate',json=state).json()['conflicts']==[]


def test_save_retry_expired_url_and_continue(client,monkeypatch):
    state=ready(client);calls=[];downloads=[]
    monkeypatch.setattr(config,'MODE','live');monkeypatch.setattr(config,'EXPERIMENTAL',True)
    monkeypatch.setattr(provider,'preflight',lambda:{})
    def fake_call(compiled):
        calls.append(compiled);return {'outputs':[{'url':'https://temporary.example/result.png'}],'calls':1,'elapsed_s':.2,'cost_usd':None}
    monkeypatch.setattr(provider,'call',fake_call)
    def broken_download(url):
        downloads.append(url);raise OSError('disk/network failure')
    monkeypatch.setattr(provider,'download',broken_download)
    job=submit(client,state);assert job['status']=='save_failed' and len(calls)==1
    data=io.BytesIO();Image.new('RGB',(120,80),'green').save(data,'PNG')
    monkeypatch.setattr(provider,'download',lambda u:data.getvalue())
    assert client.post('/api/jobs/'+job['id']+'/retry-save').status_code==200
    for _ in range(100):
        job=client.get('/api/jobs/'+job['id']).json()
        if job['status']=='succeeded':break
        time.sleep(.02)
    aid=job['result']['assets'][0];assert len(calls)==1
    monkeypatch.setattr(provider,'download',lambda u:(_ for _ in ()).throw(RuntimeError('URL expired')))
    store.init() # Restart storage, no reliance on browser or upstream.
    assert client.get('/api/assets/'+aid).status_code==200
    assert client.get('/api/assets/'+aid+'?download=true').headers['content-type']=='image/png'
    restored=client.post('/api/jobs/'+job['id']+'/restore',json={'use_result':True,'asset_id':aid}).json()
    assert restored['main_image']==aid and restored['mappings']==[] and restored['next_display_index']==1
    assert restored['origin_history_id']==job['id']
    assert len(calls)==1
    client.post('/api/logout');client.cookies.clear();assert client.get('/api/jobs').status_code==401
    client.post('/api/login',json={'password':config.PASSWORD})
    assert client.get('/api/assets/'+aid).content==data.getvalue()


def test_delete_keeps_shared_assets_and_restart_unknown(client):
    state=ready(client);job=submit(client,state)
    restored=client.post('/api/jobs/'+job['id']+'/restore',json={}).json()
    assert client.delete('/api/jobs/'+job['id']).status_code==200
    assert client.get('/api/jobs/'+job['id']).status_code==404
    assert client.get('/api/assets/'+restored['main_image']).status_code==200
    assert client.get('/api/drafts/'+restored['id']).status_code==200
    with store.db() as con:con.execute("UPDATE jobs SET status='running' WHERE id=?",(job['id'],))
    store.init();assert store.job(job['id'],True)['status']=='unknown'


def test_context_crop_complete_and_only_referenced(client):
    state=ready(client);unused=upload(client,'yellow');state['references'].append(unused['id'])
    compiled=provider.compile_request(state,'context-crop')
    assert unused['id'] not in compiled['inputs'] and len(compiled['inputs'])==2
    binding=compiled['bindings'][0];crop=binding['crop'];original=store.asset(state['references'][0])
    assert crop['origin']['image_id']==original['id']
    x1,y1,x2,y2=crop['origin']['box_pixels'];assert x1<=12 and y1<=8 and x2>=36 and y2>=24
    assert store.asset(state['mappings'][0]['source']['mask_id'])['origin']['method']=='manual-polygon'


def test_overlapping_targets_keep_distinct_anchor_intent(client):
    state=ready(client)
    second=copy.deepcopy(state['mappings'][0]);second.update(id='other-point',display_index=2,color=store.COLORS[1])
    second['target']['anchor']={'x':.25,'y':.25}
    state['mappings'].append(second);state['next_display_index']=3
    assert store.validate(state,True,True)[0]['duplicate']
    compiled=provider.compile_request(state,'full')
    assert compiled['bindings'][0]['target_anchor']=={'x':.2,'y':.2}
    assert compiled['bindings'][1]['target_anchor']=={'x':.25,'y':.25}
    assert '(0.2, 0.2)' in compiled['prompt'] and '(0.25, 0.25)' in compiled['prompt']
