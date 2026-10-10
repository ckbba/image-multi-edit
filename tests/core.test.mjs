import test from 'node:test';
import assert from 'node:assert/strict';
import {imageRect,toImage,createMapping,addMapping,UndoStack,LatestRequest,COLORS,normalizeEditorState,composerEntries,confirmRequirement,cancelRequirementDraft,composerFragmentText,applyComposerFragment,retryTransient} from '../前端代码/core.js';

test('letterbox coordinates remain stable across viewport sizes; margins reject points',()=>{
 for(const [w,h] of [[500,400],[200,700],[1200,500]]){const r=imageRect(w,h,1200,800);const p=toImage(r.x+r.width*.25,r.y+r.height*.75,r);assert.ok(Math.abs(p.x-.25)<1e-10);assert.ok(Math.abs(p.y-.75)<1e-10);assert.equal(toImage(r.x-1,r.y,r),null);}
});
test('deletion, undo and redo preserve IDs, colors and monotonic display number',()=>{
 let s={mappings:[],next_display_index:1};const u=new UndoStack();for(let i=0;i<3;i++)s=addMapping(s,createMapping(s,{image_id:'ref'},{image_id:'main'}));const old=structuredClone(s);u.push(s);s.mappings.splice(1,1);const newMapping=createMapping(s,{},{});assert.equal(newMapping.display_index,4);s=addMapping(s,newMapping);assert.deepEqual(s.mappings.map(m=>m.display_index),[1,3,4]);s=u.undo(s);assert.deepEqual(s,old);s=u.redo(s);assert.equal(s.mappings[1].id,old.mappings[2].id);assert.equal(s.mappings[1].color,COLORS[2]);
});
test('late selection cannot replace newer image/point; old request is aborted',()=>{const req=new LatestRequest();const a=req.start(),b=req.start();assert.equal(a.signal.aborted,true);assert.equal(req.current(a.version),false);assert.equal(req.current(b.version),true);req.cancel();assert.equal(req.current(b.version),false);});

test('transient selection failure retries once then succeeds',async()=>{let attempts=0;const result=await retryTransient(async()=>{attempts++;if(attempts===1)throw Object.assign(new Error('restart'),{status:503});return 'candidate';},{delays:[0]});assert.equal(result,'candidate');assert.equal(attempts,2);});

test('abort and non-transient errors are never retried',async()=>{for(const error of [Object.assign(new Error('cancelled'),{name:'AbortError'}),Object.assign(new Error('bad point'),{status:400}),new Error('mask decode failed')]){let attempts=0;await assert.rejects(()=>retryTransient(async()=>{attempts++;throw error;},{delays:[0,0]}),error);assert.equal(attempts,1);}});

test('stale selection cancels retry backoff',async()=>{const controller=new AbortController();let attempts=0;const pending=retryTransient(async()=>{attempts++;throw new TypeError('Failed to fetch');},{delays:[50],signal:controller.signal});controller.abort();await assert.rejects(pending,error=>error.name==='AbortError');assert.equal(attempts,1);});

test('legacy state gains mixed-input fields without changing old content',()=>{
 const old={instructions:'保留光线',mappings:[{id:'m1',display_index:1,source:{label:'外套'}}]};
 const next=normalizeEditorState(old);
 assert.equal(next.instructions,'保留光线');assert.equal(next.mappings[0].requirement,'');assert.deepEqual(next.full_image_refs,[]);
 assert.notEqual(next,old);
});

test('composer exposes one structured entry per operation and explicit whole-image reference',()=>{
 const state=normalizeEditorState({instructions:'自然光',mappings:[{id:'m1',display_index:1,source:{image_id:'a',label:'外套'},requirement:'换上外套'}],full_image_refs:[{id:'r1',image_id:'a',label:'街景',purpose:'参考背景'}]});
 assert.deepEqual(composerEntries(state).map(x=>[x.kind,x.id,x.text]),[['mapping','m1','换上外套'],['full-image','r1','参考背景'],['global','global','自然光']]);
});

test('bubble confirmation replaces shared requirement and cancellation preserves confirmed value',()=>{
 const state=normalizeEditorState({mappings:[{id:'m1',display_index:1,source:{},requirement:'旧要求'}]});
 assert.equal(cancelRequirementDraft(state,'m1','未确认').mappings[0].requirement,'旧要求');
 assert.equal(confirmRequirement(state,'m1','新要求').mappings[0].requirement,'新要求');
 assert.equal(confirmRequirement(confirmRequirement(state,'m1','一次'),'m1','二次').mappings.length,1);
});

test('unified composer fragments update the same state fields without flattening bindings',()=>{
 const state=normalizeEditorState({instructions:'保留自然光',mappings:[{id:'m1',display_index:1,source:{},requirement:'换成坐姿'}],full_image_refs:[{id:'r1',image_id:'a',purpose:'参考街景'}]});
 assert.equal(composerFragmentText(state,'mapping','m1'),'换成坐姿');
 assert.equal(composerFragmentText(state,'full-image','r1'),'参考街景');
 assert.equal(composerFragmentText(state,'global','global'),'保留自然光');
 const changed=applyComposerFragment(state,'mapping','m1','已有句子中改写动作');
 assert.equal(changed.mappings[0].requirement,'已有句子中改写动作');
 assert.equal(changed.full_image_refs[0].purpose,'参考街景');
 assert.equal(changed.instructions,'保留自然光');
});
