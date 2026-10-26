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
import segmentation
import recognition
import auth
from app import app


@pytest.fixture(autouse=True)
def disable_recognition_by_default(monkeypatch):
    monkeypatch.setattr(config, 'GEMINI_KEY', '')
    recognition.clear()


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
        con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result,user_id) VALUES(?,?,?,?,?,?,?)',
            (jid,jid,time.time(),'succeeded',json.dumps(snapshot),json.dumps({'assets':[intermediate['id']],'calls':1}),auth.LEGACY_USER_ID))
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


def test_simulation_idempotency_does_not_shadow_live_submission(client,monkeypatch):
    state=ready(client)
    simulated=submit(client,state,'same-user-action-key')
    assert simulated['status']=='simulated'
    calls=[]
    monkeypatch.setattr(config,'MODE','live');monkeypatch.setattr(config,'EXPERIMENTAL',True)
    monkeypatch.setattr(config,'MODEL','gpt-image-2.5-flare')
    monkeypatch.setattr(provider,'preflight',lambda *args:{})
    monkeypatch.setattr(provider,'call',lambda compiled: calls.append(compiled) or (_ for _ in ()).throw(RuntimeError('injected unknown upstream result')))
    live=submit(client,state,'same-user-action-key')
    assert live['id']!=simulated['id']
    assert live['status']=='unknown'
    assert live['snapshot']['mode']=='live'
    assert len(calls)==1


def test_unknown_live_idempotency_is_never_resubmitted(client,monkeypatch):
    state=ready(client);calls=[]
    monkeypatch.setattr(config,'MODE','live');monkeypatch.setattr(config,'EXPERIMENTAL',True)
    monkeypatch.setattr(config,'MODEL','gpt-image-2.5-flare')
    monkeypatch.setattr(provider,'preflight',lambda *args:{})
    monkeypatch.setattr(provider,'call',lambda compiled: calls.append(compiled) or (_ for _ in ()).throw(RuntimeError('injected unknown upstream result')))
    first=submit(client,state,'unknown-paid-action')
    second=submit(client,state,'unknown-paid-action')
    assert first['status']==second['status']=='unknown'
    assert first['id']==second['id']
    assert len(calls)==1


def test_legacy_unknown_paid_idempotency_is_preserved(client,monkeypatch):
    state=ready(client);calls=[]
    monkeypatch.setattr(config,'MODE','live');monkeypatch.setattr(config,'EXPERIMENTAL',True)
    monkeypatch.setattr(config,'MODEL','gpt-image-2.5-flare')
    monkeypatch.setattr(provider,'preflight',lambda *args:{})
    compiled=provider.compile_request(state)
    snapshot={'state':state,'compiled':compiled,'mode':'live','model':config.MODEL,'created':time.time()}
    jid=store.uid()
    with store.db() as con:
        con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result,user_id) VALUES(?,?,?,?,?,?,?)',
                    (jid,'legacy-paid-key',time.time(),'unknown',json.dumps(snapshot),json.dumps({'error':'upstream unknown'}),auth.LEGACY_USER_ID))
    monkeypatch.setattr(provider,'call',lambda compiled:calls.append(compiled))
    repeated=submit(client,state,'legacy-paid-key')
    assert repeated['id']==jid and repeated['status']=='unknown'
    assert calls==[]


def test_sam_native_crash_does_not_take_down_api_or_generation(client,monkeypatch):
    isolated=segmentation.SamProcessClient(worker='fake_sam_worker:serve',timeout=2)
    attempts=iter(('crash','prepare'))
    monkeypatch.setattr(segmentation,'prepare',lambda aid: isolated.request(next(attempts),image_id=aid))
    try:
        failed=client.post('/api/segmentation/prepare',json={'image_id':'fault-injection'})
        assert failed.status_code==503
        assert client.get('/api/health').json()=={'ok':True}
        assert client.post('/api/drafts').status_code==200
        state=ready(client)
        assert submit(client,state,'generation-after-sam-crash')['status']=='simulated'
        recovered=client.post('/api/segmentation/prepare',json={'image_id':'fault-injection'})
        assert recovered.status_code==200
        assert recovered.json()['method']=='prepare'
    finally:
        isolated.close()


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
    monkeypatch.setattr(provider,'preflight',lambda *args:{})
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


def test_history_rename_persists_without_mutating_generation_snapshot(client):
    state = ready(client); job = submit(client, state, 'rename-history')
    original_snapshot = copy.deepcopy(job['snapshot'])
    renamed = '8794 重命名样例'

    response = client.patch('/api/jobs/' + job['id'], json={'name': renamed})
    assert response.status_code == 200, response.text
    assert response.json()['name'] == renamed
    reread = client.get('/api/jobs/' + job['id']).json()
    assert reread['name'] == renamed
    assert reread['snapshot'] == original_snapshot
    assert reread['snapshot']['state']['name'] == '测试项目'
    restored = client.post('/api/jobs/' + job['id'] + '/restore', json={}).json()
    assert restored['name'] == '测试项目 · 恢复'
    assert reread['result']['calls'] == 0
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/jobs?q=8794').json()['items'][0]['id'] == job['id']
    assert client.get('/api/jobs?q=测试项目').json()['items'] == []


def test_history_rename_validation_and_deleted_scope(client):
    state = ready(client); job = submit(client, state, 'rename-validation')
    assert client.patch('/api/jobs/' + job['id'], json={'name': '   '}).status_code == 400
    assert client.patch('/api/jobs/' + job['id'], json={'name': 'x' * 101}).status_code == 400
    assert client.patch('/api/jobs/' + job['id'], json={}).status_code == 400
    assert client.get('/api/jobs/' + job['id']).json()['name'] == '测试项目'
    assert client.delete('/api/jobs/' + job['id']).status_code == 200
    assert client.patch('/api/jobs/' + job['id'], json={'name': '不能改'}).status_code == 404


def test_history_server_search_status_pagination_and_literal_wildcards(client):
    state = ready(client)
    jobs = []
    for index in range(23):
        item = submit(client, state, f'search-page-{index:02d}')
        name = f'跨页中文-{index:02d}' if index in (0, 22) else f'普通-{index:02d}'
        assert client.patch('/api/jobs/' + item['id'], json={'name': name}).status_code == 200
        jobs.append(item)
    assert client.patch('/api/jobs/' + jobs[10]['id'], json={'name': '百分号%下划线_'}).status_code == 200
    with store.db() as con:
        con.execute("UPDATE jobs SET status='failed' WHERE id=?", (jobs[22]['id'],))
        con.execute("UPDATE jobs SET created=? WHERE id=?", (jobs[0]['created'], jobs[1]['id']))

    first = client.get('/api/jobs?q=跨页中文').json()
    assert first['count'] == 2 and first['next_offset'] is None
    assert {item['id'] for item in first['items']} == {jobs[0]['id'], jobs[22]['id']}
    filtered = client.get('/api/jobs?q=跨页中文&status=failed').json()
    assert filtered['count'] == 1 and filtered['items'][0]['id'] == jobs[22]['id']
    assert client.get('/api/jobs?q=%').json()['items'][0]['id'] == jobs[10]['id']
    assert client.get('/api/jobs?q=_').json()['items'][0]['id'] == jobs[10]['id']
    all_first = client.get('/api/jobs').json()
    all_second = client.get('/api/jobs?offset=20').json()
    assert all_first['count'] == 23 and len(all_first['items']) == 20 and all_first['next_offset'] == 20
    assert len(all_second['items']) == 3 and all_second['count'] == 23 and all_second['next_offset'] is None
    assert not ({item['id'] for item in all_first['items']} & {item['id'] for item in all_second['items']})


def test_delete_keeps_shared_assets_other_history_and_refuses_active_jobs(client):
    state=ready(client);deleted=submit(client,state,'delete-one')
    restored=client.post('/api/jobs/'+deleted['id']+'/restore',json={}).json()
    other=submit(client,restored,'keep-other')
    shared_assets={state['main_image'],state['references'][0],state['mappings'][0]['source']['mask_id'],state['mappings'][0]['target']['mask_id']}

    assert client.delete('/api/jobs/'+deleted['id']).json()=={'ok':True}
    listed={item['id'] for item in client.get('/api/jobs').json()['items']}
    assert deleted['id'] not in listed and other['id'] in listed
    assert client.get('/api/jobs/'+deleted['id']).status_code==404
    assert all(client.get('/api/assets/'+aid).status_code==200 for aid in shared_assets)
    assert client.get('/api/drafts/'+restored['id']).status_code==200
    assert client.delete('/api/jobs/'+deleted['id']).status_code==404

    with store.db() as con:
        con.execute("UPDATE jobs SET status='running' WHERE id=?",(other['id'],))
    refused=client.delete('/api/jobs/'+other['id'])
    assert refused.status_code==409 and '执行中' in refused.json()['detail']
    assert client.get('/api/jobs/'+other['id']).status_code==200
    with store.db() as con:
        con.execute("UPDATE jobs SET deleted=1 WHERE id=?",(other['id'],))
    store.init();assert store.job(other['id'],True)['status']=='unknown'


def test_context_crop_complete_and_only_referenced(client):
    state=ready(client);unused=upload(client,'yellow');state['references'].append(unused['id'])
    compiled=provider.compile_request(state,'context-crop')
    assert unused['id'] not in compiled['inputs'] and len(compiled['inputs'])==2
    binding=compiled['bindings'][0];crop=binding['crop'];original=store.asset(state['references'][0])
    assert crop['origin']['image_id']==original['id']
    x1,y1,x2,y2=crop['origin']['box_pixels'];assert x1<=12 and y1<=8 and x2>=36 and y2>=24
    assert store.asset(state['mappings'][0]['source']['mask_id'])['origin']['method']=='manual-polygon'


def test_default_compile_uses_element_context_crop_even_for_legacy_full_state(client):
    state=ready(client);state['source_strategy']='full'
    compiled=provider.compile_request(state)
    assert compiled['strategy']=='context-crop'
    assert compiled['bindings'][0]['crop'] is not None


def test_reference_preview_bytes_equal_compiled_input_without_creating_job(client):
    state=ready(client)
    mapping=state['mappings'][0]
    before_jobs=client.get('/api/jobs').json()['items']
    with store.db() as con:
        before_assets={row['id'] for row in con.execute('SELECT id FROM assets')}
    preview=client.post('/api/reference-preview',json={'mapping':mapping,'strategy':state['source_strategy']})
    assert preview.status_code==200,preview.text
    assert preview.headers['x-reference-preview-kind']=='model-reference-input'
    assert preview.headers['x-subject-focus']=='off'
    assert client.get('/api/jobs').json()['items']==before_jobs
    with store.db() as con:
        after_assets={row['id'] for row in con.execute('SELECT id FROM assets')}
    assert after_assets==before_assets
    compiled=provider.compile_request(state)
    sent=client.get('/api/assets/'+compiled['bindings'][0]['input_asset_id'])
    assert preview.content==sent.content

def test_scale_aligned_reference_matches_target_footprint_and_preview(client):
    state=ready(client);state['source_strategy']='scale-aligned';mapping=state['mappings'][0]
    preview=client.post('/api/reference-preview',json={'mapping':mapping,'strategy':'scale-aligned'})
    assert preview.status_code==200,preview.text
    compiled=provider.compile_request(state)
    binding=compiled['bindings'][0]
    assert binding['crop']['origin']['strategy']=='scale-aligned'
    assert preview.content==client.get('/api/assets/'+binding['input_asset_id']).content
    image=Image.open(io.BytesIO(preview.content)).convert('RGB')
    assert image.size==(120,80)
    assert image.getpixel((0,0))==(128,128,128)
    assert image.getpixel((24,16))==(255,0,0)
    assert image.getpixel((110,70))==(128,128,128)
    assert 'neutral canvas is not part of the scene' in compiled['prompt']

def test_element_prompt_uses_target_fraction_without_enforcing_human_into_small_mask(client):
    state=ready(client);state['source_strategy']='scale-aligned'
    state['mappings'][0]['source']['label']='男人'
    state['mappings'][0]['requirement']='让人物站在上层平台地面抱着孩子'
    compiled=provider.compile_request(state)
    assert 'target footprint about 20.8% of IMAGE 1 width and 21.2% of its height' in compiled['prompt']
    assert 'head/body and limb proportions' in compiled['prompt']
    assert 'feet on the intended ground' in compiled['prompt']
    assert 'do not force a full person to fit a small selection' in compiled['prompt']
    assert compiled['bindings'][0]['target_bbox']==store.asset(state['mappings'][0]['target']['mask_id'])['bbox']

def test_new_draft_defaults_to_scale_alignment_without_changing_legacy_drafts(client):
    fresh=client.post('/api/drafts').json()
    assert fresh['source_strategy']=='scale-aligned'
    older=ready(client)
    older['source_strategy']='context-crop'
    assert provider.compile_request(older)['strategy']=='context-crop'

def test_scale_aligned_preview_rejects_unknown_strategy(client):
    state=ready(client)
    response=client.post('/api/reference-preview',json={'mapping':state['mappings'][0],'strategy':'nonsense'})
    assert response.status_code==400


def test_subject_focus_is_explicit_mask_processing_and_preview_is_fresh(client):
    state=ready(client)
    mapping=state['mappings'][0]
    raw=client.post('/api/reference-preview',json={'mapping':mapping,'strategy':state['source_strategy']})
    mapping['subject_focus']=True
    focused=client.post('/api/reference-preview',json={'mapping':mapping,'strategy':state['source_strategy']})
    assert focused.status_code==200,focused.text
    assert focused.headers['x-subject-focus']=='selected-mask'
    assert focused.content!=raw.content
    state['mappings'][0]=mapping
    compiled=provider.compile_request(state)
    binding=compiled['bindings'][0]
    assert binding['subject_focus']=='selected-mask'
    assert focused.content==client.get('/api/assets/'+binding['input_asset_id']).content
    assert 'existing selected source mask' in compiled['prompt']


def test_main_edit_preview_is_truthful_main_input_and_never_a_reference_crop(client):
    state=ready(client);state['mappings']=[];state['references']=[]
    selected=mask(client,state['main_image'],.2,.2)
    mapping={'id':'main-local','kind':'main-edit','display_index':1,'color':store.COLORS[0],'mode':'replace','requirement':'提亮主体','source':None,
        'target':{'image_id':state['main_image'],'image_version':1,'mask_id':selected['id'],'edit_region_id':selected['id'],'anchor':{'x':.3,'y':.3}}}
    response=client.post('/api/reference-preview',json={'mapping':mapping})
    assert response.status_code==200
    assert response.headers['x-reference-preview-kind']=='main-image-no-separate-reference'
    assert response.content==client.get('/api/assets/'+state['main_image']).content


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


def test_main_image_mask_edits_compile_in_stable_user_order_without_reference_inputs(client):
    state=ready(client);state['mappings']=[];state['references']=[]
    first=mask(client,state['main_image'],.1,.1);second=mask(client,state['main_image'],.5,.5)
    state['mappings']=[
        {'id':'local-7','kind':'main-edit','display_index':7,'color':store.COLORS[1],'mode':'replace','requirement':'移除路牌','source':None,
         'target':{'image_id':state['main_image'],'image_version':1,'mask_id':first['id'],'edit_region_id':first['id'],'anchor':{'x':.2,'y':.2}}},
        {'id':'local-8','kind':'main-edit','display_index':8,'color':store.COLORS[2],'mode':'replace','requirement':'改成蓝色','source':None,
         'target':{'image_id':state['main_image'],'image_version':1,'mask_id':second['id'],'edit_region_id':second['id'],'anchor':{'x':.6,'y':.6}}}]
    state['next_display_index']=9
    store.validate(state,True,True)
    compiled=provider.compile_request(state)
    assert compiled['inputs']==[state['main_image']]
    assert [b['mapping_id'] for b in compiled['bindings']]==['local-7','local-8']
    assert compiled['mask_asset_ids']==[first['id'],second['id']]
    assert compiled['prompt'].index('Operation 7') < compiled['prompt'].index('Operation 8')
    assert '移除路牌' in compiled['prompt'] and '改成蓝色' in compiled['prompt']


def test_native_edit_mask_combines_all_local_regions_with_transparent_edit_pixels(client):
    state=ready(client);first=mask(client,state['main_image'],.1,.1);second=mask(client,state['main_image'],.6,.5)
    content=provider.native_edit_mask([first['id'],second['id']],state['main_image'])
    image=Image.open(io.BytesIO(content)).convert('RGBA')
    assert image.getpixel((18,12))[3]==0
    assert image.getpixel((78,48))[3]==0
    assert image.getpixel((110,70))[3]==255


def test_mixed_whole_image_and_element_compile_as_distinct_inputs(client):
    state=ready(client)
    source=state['mappings'][0]['source']['image_id']
    state['mappings'][0]['requirement']='把人物改成坐姿并穿上这件衣服'
    state['full_image_refs']=[{'id':'whole-1','image_id':source,'label':'街景','purpose':'仅参考整图背景'}]
    compiled=provider.compile_request(state,'context-crop')
    assert len(compiled['inputs'])==3
    assert compiled['inputs'][2]==source
    assert compiled['bindings'][0]['kind']=='element'
    assert compiled['bindings'][1]['kind']=='full-image'
    assert compiled['bindings'][0]['original_id']==compiled['bindings'][1]['original_id']==source
    assert compiled['bindings'][0]['input_asset_id']!=compiled['bindings'][1]['original_id']
    assert '坐姿并穿上' in compiled['prompt']
    assert '仅参考整图背景' in compiled['prompt']
    assert 'Preserve the base camera framing, aspect ratio, identity, pose' not in compiled['prompt']


def test_unmentioned_uploaded_reference_is_not_input_but_explicit_whole_image_is(client):
    state=ready(client);unused=upload(client,'yellow');state['references'].append(unused['id'])
    first=provider.compile_request(state,'context-crop')
    assert unused['id'] not in first['inputs']
    state['full_image_refs']=[{'id':'whole-2','image_id':unused['id'],'label':'黄色图','purpose':'参考整体色调'}]
    second=provider.compile_request(state,'context-crop')
    assert unused['id'] in second['inputs']


def test_whole_image_only_submission_and_snapshot_restore(client):
    main,ref=upload(client),upload(client,'red')
    state=client.post('/api/drafts').json()
    state.update(main_image=main['id'],references=[ref['id']],instructions='让画面更自然',
        full_image_refs=[{'id':'whole-only','image_id':ref['id'],'label':'参考图 1','purpose':'参考背景氛围'}])
    saved=client.put('/api/drafts/'+state['id'],json=state);assert saved.status_code==200,saved.text
    state['revision']=saved.json()['revision'];job=submit(client,state,'whole-only-submit')
    assert job['snapshot']['state']['full_image_refs'][0]['id']=='whole-only'
    restored=client.post('/api/jobs/'+job['id']+'/restore',json={}).json()
    assert restored['full_image_refs']==state['full_image_refs']
    assert client.get('/api/jobs/'+job['id']).json()['snapshot']['state']['full_image_refs']==state['full_image_refs']


def test_main_image_global_prompt_only_submission_compiles_and_restores(client):
    main = upload(client)
    state = client.post('/api/drafts').json()
    state.update(main_image=main['id'], instructions='保留原人物姿势、构图和光影，只把整体色调改得更温暖')
    saved = client.put('/api/drafts/'+state['id'], json=state)
    assert saved.status_code == 200, saved.text
    state['revision'] = saved.json()['revision']

    job = submit(client, state, 'main-global-prompt-only')
    compiled = job['snapshot']['compiled']
    assert job['status'] == 'simulated' and job['result']['calls'] == 0
    assert compiled['inputs'] == [main['id']]
    assert compiled['base_input'] == {'kind':'base','input_index':1,'input_asset_id':main['id'],'label':'主图'}
    assert 'IMAGE 1 is the user’s 主图' in compiled['prompt']
    assert state['instructions'] in compiled['prompt']
    restored = client.post('/api/jobs/'+job['id']+'/restore', json={}).json()
    assert restored['instructions'] == state['instructions']


def test_empty_main_image_submission_stays_blocked(client):
    main = upload(client)
    state = client.post('/api/drafts').json()
    state.update(main_image=main['id'], instructions='   ')
    saved = client.put('/api/drafts/'+state['id'], json=state)
    assert saved.status_code == 200, saved.text
    response = client.post('/api/jobs', json={'draft_id':state['id'],'revision':saved.json()['revision'],
        'idempotency_key':'empty-main-only'})
    assert response.status_code == 400
    assert '至少一条' in response.json()['detail']


def test_continue_from_result_clears_old_regions_and_references(client,monkeypatch):
    state=ready(client);state['mappings'][0]['requirement']='旧图局部要求';state['full_image_refs']=[{'id':'whole','image_id':state['references'][0],'label':'整图','purpose':'背景'}]
    # A simulated job has no output, so attach an immutable local output to exercise continuation.
    job=submit(client,state,'continue-mixed');out=upload(client,'green')['id']
    with store.db() as con:
        con.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps({'assets':[out],'calls':0}),job['id']))
    continued=client.post('/api/jobs/'+job['id']+'/restore',json={'use_result':True,'asset_id':out}).json()
    assert continued['main_image']==out and continued['mappings']==[]
    assert continued['full_image_refs']==[] and continued['references']==[]
    assert continued['instructions']=='' and continued['next_display_index']==1


def test_reference_upload_limit_accepts_12_and_rejects_13(client):
    main=upload(client)
    refs=[upload(client, f'#{i:02x}0000')['id'] for i in range(1,14)]
    state=client.post('/api/drafts').json();state.update(main_image=main['id'],references=refs[:12])
    accepted=client.put('/api/drafts/'+state['id'],json=state)
    assert accepted.status_code==200,accepted.text
    state=client.get('/api/drafts/'+state['id']).json();state['references']=refs
    rejected=client.put('/api/drafts/'+state['id'],json=state)
    assert rejected.status_code==400
    assert '最多 12 张参考图' in rejected.json()['detail']


def test_mapping_draft_limit_accepts_20_and_rejects_21(client):
    state=ready(client);base=state['mappings'][0]
    state['mappings']=[]
    for i in range(20):
        item=copy.deepcopy(base);item.update(id=f'mapping-{i+1}',display_index=i+1,color=store.COLORS[i%5])
        state['mappings'].append(item)
    state['next_display_index']=21
    assert client.post('/api/validate',json=state).status_code==200
    extra=copy.deepcopy(base);extra.update(id='mapping-21',display_index=21,color=store.COLORS[0])
    state['mappings'].append(extra);state['next_display_index']=22
    rejected=client.post('/api/validate',json=state)
    assert rejected.status_code==400
    assert '最多 20 条元素草稿' in rejected.json()['detail']


def test_submit_guard_rejects_more_than_12_actual_mixed_references(client):
    state=ready(client);base=state['mappings'][0]
    state['mappings']=[]
    for i in range(11):
        item=copy.deepcopy(base);item.update(id=f'active-{i+1}',display_index=i+1,color=store.COLORS[i%5])
        state['mappings'].append(item)
    state['next_display_index']=12
    source=state['references'][0]
    state['full_image_refs']=[{'id':'whole-1','image_id':source,'label':'参考图 1','purpose':'参考背景'}]
    store.validate(state,True,True)
    state['full_image_refs'].append({'id':'whole-2','image_id':source,'label':'参考图 1','purpose':'参考色调'})
    with pytest.raises(Exception) as error:
        store.validate(state,True,True)
    assert getattr(error.value,'status_code',None)==400
    assert '当前共 13 个实际参考输入，最多 12 个' in error.value.detail


def test_text_only_edit_validates_compiles_and_restores_without_reference_input(client):
    state = ready(client); state['mappings'] = []; state['references'] = []; state['full_image_refs'] = []
    state['text_edits'] = [{'id':'text-main-v1-1','image_id':state['main_image'],'image_version':1,'source':'ocr',
        'original_text':'DesignKit','replacement':'拾影设计','bbox':[.2,.3,.7,.4]}]
    store.validate(state, True, True)
    compiled = provider.compile_request(state)
    assert compiled['inputs'] == [state['main_image']]
    assert compiled['bindings'] == [{'kind':'text-edit','text_edit_id':'text-main-v1-1','original_text':'DesignKit',
        'replacement':'拾影设计','bbox':[.2,.3,.7,.4]}]
    assert 'DesignKit' in compiled['prompt'] and '拾影设计' in compiled['prompt']
    assert 'preserve all other text' in compiled['prompt']
    saved = client.put('/api/drafts/' + state['id'], json=state); assert saved.status_code == 200
    state['revision'] = saved.json()['revision']
    job = submit(client, state, 'text-only-history')
    restored = client.post('/api/jobs/' + job['id'] + '/restore', json={}).json()
    assert restored['text_edits'] == state['text_edits']


def test_compile_filters_noop_text_edits_and_never_leaks_unmodified_ocr_text(client):
    state = ready(client); state['mappings'] = []; state['references'] = []; state['full_image_refs'] = []
    effective = {'id':'changed','image_id':state['main_image'],'image_version':1,'source':'ocr','original_text':'旧字','replacement':'新字','bbox':[.1,.1,.3,.2]}
    sentinel = {'id':'sentinel','image_id':state['main_image'],'image_version':1,'source':'ocr','original_text':'NEVER_SEND_THIS_OCR_TEXT','replacement':' NEVER_SEND_THIS_OCR_TEXT ','bbox':[.4,.4,.6,.5]}
    state['text_edits'] = [effective, sentinel]
    compiled = provider.compile_request(state)
    assert [b['text_edit_id'] for b in compiled['bindings']] == ['changed']
    assert 'NEVER_SEND_THIS_OCR_TEXT' not in compiled['prompt']
    with pytest.raises(Exception):
        store.validate({**state, 'text_edits':[sentinel]}, True, True)


def test_grouped_text_region_validates_and_compiles_as_one_binding_with_linebreaks(client):
    state = ready(client); state['mappings'] = []; state['references'] = []; state['full_image_refs'] = []
    state['text_edits'] = [{'id':'text-group-main-anna-karina','image_id':state['main_image'],'image_version':1,
        'source':'ocr-group','original_text':'ANNA\nKARINA','replacement':'安娜\n卡里娜','bbox':[.1,.2,.5,.4],
        'polygon':[[.08,.18],[.52,.18],[.52,.42],[.08,.42]],'ocr_line_ids':['line-anna','line-karina']}]
    store.validate(state, True, True)
    compiled = provider.compile_request(state)
    assert len(compiled['bindings']) == 1
    assert compiled['bindings'][0]['ocr_line_ids'] == ['line-anna','line-karina']
    assert compiled['bindings'][0]['polygon'] == state['text_edits'][0]['polygon']
    assert 'ANNA\nKARINA' in compiled['prompt'] and '安娜\n卡里娜' in compiled['prompt']


def test_text_edit_validation_rejects_wrong_image_empty_or_invalid_bbox(client):
    state = ready(client); state['mappings'] = []
    base = {'id':'t1','image_id':'wrong','image_version':1,'source':'ocr','original_text':'旧字','replacement':'新字','bbox':[.1,.2,.3,.4]}
    for change in ({}, {'image_id':state['main_image'],'replacement':'  '}, {'image_id':state['main_image'],'bbox':[.4,.2,.3,.4]}):
        state['text_edits'] = [{**base, **change}]
        with pytest.raises(Exception): store.validate(state)


def test_ocr_endpoint_returns_real_adapter_output_without_creating_job(client, monkeypatch):
    import text_recognition
    asset = upload(client)
    expected = {'engine':'rapidocr','items':[{'id':'line-1','text':'DesignKit','confidence':.98,'bbox':[.1,.2,.4,.3]}]}
    monkeypatch.setattr(text_recognition, 'recognize', lambda aid: expected)
    before = client.get('/api/jobs').json()['items']
    response = client.post('/api/text-recognition/' + asset['id'])
    assert response.status_code == 200 and response.json() == expected
    assert client.get('/api/jobs').json()['items'] == before


def test_ocr_worker_output_is_read_as_bytes_so_non_utf8_stderr_cannot_discard_valid_json(client, monkeypatch):
    import subprocess
    import text_recognition
    asset = upload(client)
    payload = json.dumps({'items':[{'text':'呵护健康','confidence':.99,'bbox':[.1,.2,.5,.3]}]}, ensure_ascii=False).encode('utf-8')

    def worker_run(*args, **kwargs):
        if kwargs.get('text') or kwargs.get('encoding'):
            raise UnicodeDecodeError('utf-8', b'\xba', 0, 1, 'invalid start byte')
        return subprocess.CompletedProcess(args[0], 0, stdout=payload + b'\r\n', stderr=b'\xba worker log')

    monkeypatch.setattr(text_recognition.subprocess, 'run', worker_run)
    result = text_recognition._recognize_uncached(asset['id'])
    assert result['items'][0]['text'] == '呵护健康'


def test_ocr_endpoint_reuses_image_version_cache(client, monkeypatch):
    import text_recognition
    asset = upload(client)
    calls = []
    monkeypatch.setattr(text_recognition, '_recognize_uncached', lambda aid: calls.append(aid) or {'engine':'rapidocr','items':[]})
    text_recognition.clear_cache()
    first = client.post('/api/text-recognition/' + asset['id'])
    second = client.post('/api/text-recognition/' + asset['id'])
    assert first.status_code == second.status_code == 200
    assert calls == [asset['id']]
    assert first.json()['cached'] is False
    assert second.json()['cached'] is True


def test_generation_model_allowlist_default_snapshot_restore_and_adapter(client, monkeypatch):
    state = ready(client)
    assert state.get('generation_model') == 'gpt-image-2.5-flare'
    state['generation_model'] = 'gpt-image-2.5-sunburst'
    saved = client.put('/api/drafts/' + state['id'], json=state)
    assert saved.status_code == 200, saved.text
    state['revision'] = saved.json()['revision']
    job = submit(client, state, 'sunburst-model-snapshot')
    assert job['snapshot']['model'] == 'gpt-image-2.5-sunburst'
    assert job['snapshot']['compiled']['model'] == 'gpt-image-2.5-sunburst'
    restored = client.post('/api/jobs/' + job['id'] + '/restore', json={}).json()
    assert restored['generation_model'] == 'gpt-image-2.5-sunburst'
    restored['generation_model'] = 'made-up-model'
    assert client.put('/api/drafts/' + restored['id'], json=restored).status_code == 400


def test_live_submit_sends_selected_exact_model_to_provider(client, monkeypatch):
    state = ready(client); state['generation_model'] = 'gpt-image-2.5-sunburst'
    saved = client.put('/api/drafts/' + state['id'], json=state); state['revision'] = saved.json()['revision']
    calls = []
    monkeypatch.setattr(config, 'MODE', 'live'); monkeypatch.setattr(config, 'EXPERIMENTAL', True)
    monkeypatch.setattr(provider, 'preflight', lambda model: {})
    monkeypatch.setattr(provider, 'call', lambda compiled: calls.append(compiled['model']) or (_ for _ in ()).throw(RuntimeError('stub stop')))
    job = submit(client, state, 'selected-model-provider-stub')
    assert job['status'] == 'unknown'
    assert calls == ['gpt-image-2.5-sunburst']


def test_legacy_eco_draft_models_migrate_without_rewriting_history(client):
    state = ready(client)
    state['generation_model'] = 'gpt-image-2.5-sunburst-eco'
    with store.db() as con:
        con.execute('UPDATE drafts SET state=? WHERE id=?', (json.dumps(state), state['id']))
    migrated = client.get('/api/drafts/' + state['id']).json()
    assert migrated['generation_model'] == 'gpt-image-2.5-sunburst'
    old_snapshot = {'state': state, 'compiled': {'model': 'gpt-image-2.5-sunburst-eco', 'compiler_version': 'old'},
                    'mode': 'simulation', 'model': 'gpt-image-2.5-sunburst-eco', 'created': time.time()}
    jid = store.uid()
    with store.db() as con:
        con.execute('INSERT INTO jobs(id,idem,created,status,snapshot,result,user_id) VALUES(?,?,?,?,?,?,?)',
                    (jid, 'old-history-model', time.time(), 'simulated', json.dumps(old_snapshot), '{}', auth.LEGACY_USER_ID))
    history = client.get('/api/jobs/' + jid).json()
    assert history['snapshot']['model'] == 'gpt-image-2.5-sunburst-eco'
    restored = client.post('/api/jobs/' + jid + '/restore', json={}).json()
    assert restored['generation_model'] == 'gpt-image-2.5-sunburst'


def test_provider_multipart_uses_exact_model_image_array_and_single_output(client, monkeypatch):
    state = ready(client)
    state['generation_model'] = 'gpt-image-2.5-flare'
    compiled = provider.compile_request(state)
    captured = {}
    class Response:
        status_code = 400
        text = 'stub stop'
    class StubClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, data, files):
            captured.update(url=url, data=data, files=files)
            return Response()
    monkeypatch.setattr(provider.httpx, 'Client', StubClient)
    with pytest.raises(ValueError, match='stub stop'):
        provider.call(compiled)
    assert captured['data']['model'] == 'gpt-image-2.5-flare'
    assert captured['data']['n'] == '1'
    assert captured['files'] and all(item[0] == 'image[]' for item in captured['files'])


def test_runtime_legacy_eco_model_setting_maps_to_matching_model():
    assert config.normalize_model_setting('gpt-image-2.5-flare-eco') == 'gpt-image-2.5-flare'
    assert config.normalize_model_setting('gpt-image-2.5-sunburst-eco') == 'gpt-image-2.5-sunburst'
    assert config.normalize_model_setting('unknown-model') == 'unknown-model'
