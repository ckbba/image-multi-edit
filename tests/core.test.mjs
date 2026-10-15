import test from 'node:test';
import assert from 'node:assert/strict';
import {imageRect,referenceImageRect,detectedSelectionStatus,toImage,createMapping,createMainEditMapping,createMainEditTransient,commitMainEditTransient,addMapping,removeEmptyDraftMapping,consumePreviewSuppression,SerialActionQueue,UndoStack,LatestRequest,COLORS,normalizeEditorState,applyRecognizedLabel,composerMappingToken,mappingPreviewAssets,mappingPreviewKey,historyFrozenMappingInput,historySelectedPreviewAssets,historyDayKey,historyDayLabel,mergeHistoryItems,updateMappingLabel,composerEntries,confirmRequirement,cancelRequirementDraft,composerFragmentText,applyComposerFragment,retryTransient,REFERENCE_UPLOAD_LIMIT,MAPPING_DRAFT_LIMIT,MODEL_REFERENCE_LIMIT,generationReferenceCount,assertGenerationReferenceLimit,candidateSide,isEditableTarget,imageFilesFromTransfer,dragPreviewSize,createTextEdit,createGroupedTextEdit,selectTextLinesInPolygon,upsertTextEdit,modifiedTextEdits,replaceMainImage,findTextRegion,mergeTypedCandidates,nextTypedCandidate,isEffectiveTextEdit} from '../前端代码/core.js';

test('letterbox coordinates remain stable across viewport sizes; margins reject points',()=>{
 for(const [w,h] of [[500,400],[200,700],[1200,500]]){const r=imageRect(w,h,1200,800);const p=toImage(r.x+r.width*.25,r.y+r.height*.75,r);assert.ok(Math.abs(p.x-.25)<1e-10);assert.ok(Math.abs(p.y-.75)<1e-10);assert.equal(toImage(r.x-1,r.y,r),null);}
});
test('text brush selects intersecting lines in reading order and group replaces covered pending lines',()=>{
 const lines=[
  {id:'b',text:'KARINA',bbox:[.12,.31,.42,.39],polygon:[[.12,.31],[.42,.31],[.42,.39],[.12,.39]],confidence:.99},
  {id:'outside',text:'SENTINEL',bbox:[.7,.7,.9,.8],polygon:[[.7,.7],[.9,.7],[.9,.8],[.7,.8]]},
  {id:'a',text:'ANNA',bbox:[.1,.2,.32,.28],polygon:[[.1,.2],[.32,.2],[.32,.28],[.1,.28]],confidence:.98}];
 const brush=[[.05,.15],[.5,.15],[.5,.45],[.05,.45]];
 assert.deepEqual(selectTextLinesInPolygon(lines,brush).map(item=>item.id),['a','b']);
 const grouped=createGroupedTextEdit('main',1,selectTextLinesInPolygon(lines,brush),brush,'安娜\n卡里娜');
 assert.equal(grouped.original_text,'ANNA\nKARINA');
 assert.deepEqual(grouped.ocr_line_ids,['a','b']);
 assert.equal(grouped.source,'ocr-group');
 let state=normalizeEditorState({main_image:'main',text_edits:[createTextEdit('main',1,lines[0],'old pending'),createTextEdit('main',1,lines[2],'another pending'),{id:'unrelated',image_id:'main',image_version:1,source:'ocr',original_text:'SENTINEL',replacement:'keep',bbox:[.7,.7,.9,.8]}]});
 state=upsertTextEdit(state,grouped);
 assert.deepEqual(state.text_edits.map(item=>item.id),['unrelated',grouped.id]);
 const updated=createGroupedTextEdit('main',1,selectTextLinesInPolygon(lines,brush),brush,'ANNA K.');
 state=upsertTextEdit(state,updated);
 assert.deepEqual(state.text_edits.map(item=>item.id),['unrelated',grouped.id]);
 assert.equal(state.text_edits[1].replacement,'ANNA K.');
});
test('portrait reference fills available height when its aspect ratio fits and keeps exact coordinates',()=>{for(const [w,h] of [[430,415],[430,560]]){const r=referenceImageRect(w,h,900,1600);assert.ok(Math.abs(r.y)<1e-10);assert.ok(Math.abs(r.height-h)<1e-10);assert.ok(r.width<=w);const p=toImage(r.x+r.width*.37,r.y+r.height*.64,r);assert.ok(Math.abs(p.x-.37)<1e-10);assert.ok(Math.abs(p.y-.64)<1e-10);}});
test('zoom feedback uses only returned labels and otherwise stays truthful',()=>{assert.equal(detectedSelectionStatus({label:'包',candidates:[{},{}]},0),'包 · 候选 1 / 2 · Tab 切换候选 · 从高亮处拖到主图');assert.equal(detectedSelectionStatus({label:'',candidates:[{}]},0),'选区 · 从高亮处拖到主图');});
test('cached AI label fills only a blank name and never overwrites a user name',()=>{
 assert.deepEqual(applyRecognizedLabel({image_id:'ref'},'短发女性'),{image_id:'ref',label:'短发女性',label_source:'ai'});
 assert.deepEqual(applyRecognizedLabel({image_id:'ref'},''),{image_id:'ref'});
 assert.deepEqual(applyRecognizedLabel({image_id:'ref',label:'手填名',label_source:'user'},'AI新名'),{image_id:'ref',label:'手填名',label_source:'user'});
 assert.equal(applyRecognizedLabel({image_id:'ref'},'一二三四五六七八九十十一').label,'一二三四五六七八九十');
});
test('composer mapping token uses stable display index and color, with no blank-name fallback',()=>{
 const named=composerMappingToken({display_index:5,color:'#10b981',source:{image_id:'ref',label:'短发女性'}});
 assert.deepEqual(named,{displayIndex:5,color:'#10b981',label:'短发女性',imageId:'ref'});
 assert.equal(composerMappingToken({display_index:8,color:'#ec4899',source:{image_id:'ref',label:''}}).label,'');
});
test('mapping hover preview binds the stable mapping to its selected source or main-local mask',()=>{
 assert.deepEqual(mappingPreviewAssets({id:'source-map',source:{image_id:'ref',mask_id:'source-mask'},target:{image_id:'main',mask_id:'target-mask'}}),{mappingId:'source-map',imageId:'ref',maskId:'source-mask'});
 assert.deepEqual(mappingPreviewAssets({id:'local-map',source:null,target:{image_id:'main',mask_id:'local-mask'}}),{mappingId:'local-map',imageId:'main',maskId:'local-mask'});
});
test('actual model preview key refreshes for focus, label and source selection changes',()=>{
 const mapping={id:'m',source:{image_id:'ref',image_version:1,mask_id:'mask',label:'奖杯'},subject_focus:false};
 const original=mappingPreviewKey(mapping);
 assert.notEqual(mappingPreviewKey({...mapping,subject_focus:true}),original);
 assert.notEqual(mappingPreviewKey({...mapping,source:{...mapping.source,label:'海报'}}),original);
 assert.notEqual(mappingPreviewKey({...mapping,source:{...mapping.source,mask_id:'mask-2'}}),original);
});
test('history grouping uses one local-day heading and stable merged pagination',()=>{
 const items=[{id:'b',created:Date.UTC(2026,9,13,16,30)/1000},{id:'a',created:Date.UTC(2026,9,13,15,30)/1000}];
 assert.equal(historyDayKey(items[0].created),'2026-10-14');
 assert.equal(historyDayLabel(items[0].created),'2026年10月14日');
 assert.equal(historyDayKey(items[1].created),'2026-10-13');
 assert.deepEqual(mergeHistoryItems([items[0]],[items[0],items[1]]).map(item=>item.id),['b','a']);
});

test('history preview separates frozen model input from selected-region UI preview',()=>{
 const state={main_image:'main',mappings:[
  {id:'source-map',kind:'reference-edit',source:{image_id:'source-full',mask_id:'source-mask'},target:{image_id:'main',mask_id:'target-a'}},
  {id:'local-map',kind:'main-edit',source:null,target:{image_id:'main',mask_id:'target-local'}}]};
 const compiled={inputs:['main','saved-source-crop','source-full'],bindings:[
  {kind:'element',mapping_id:'source-map',input_index:2,input_asset_id:'saved-source-crop'},
  {kind:'main-edit',mapping_id:'local-map',mask_id:'target-local'},
  {kind:'full-image',reference_id:'whole',input_index:3,original_id:'source-full'}]};
 assert.deepEqual(historyFrozenMappingInput(state,compiled,'source-map'),{kind:'reference-input',assetId:'saved-source-crop',inputIndex:2});
 assert.deepEqual(historyFrozenMappingInput(state,compiled,'local-map'),{kind:'main-image-no-separate-reference',assetId:'main',inputIndex:1});
 assert.deepEqual(historyFrozenMappingInput(state,{inputs:['main'],bindings:[]},'source-map'),{kind:'unavailable',assetId:null,inputIndex:null});
 assert.deepEqual(historySelectedPreviewAssets(state,'source-map'),{mappingId:'source-map',imageId:'source-full',maskId:'source-mask',role:'source'});
 assert.deepEqual(historySelectedPreviewAssets(state,'local-map'),{mappingId:'local-map',imageId:'main',maskId:'target-local',role:'target'});
});

test('manual name remains text guidance and reports that selected region was not relocated',()=>{
 const state=normalizeEditorState({mappings:[{id:'m',source:{image_id:'ref',mask_id:'mask',label:'女人',label_source:'ai'},target:{}}]});
 const result=updateMappingLabel(state,'m','奖杯');
 assert.equal(result.state.mappings[0].source.label,'奖杯');
 assert.equal(result.state.mappings[0].source.mask_id,'mask');
 assert.equal(result.feedback,'主体名称仅作文字提示，未定位到新区域；如选区不符请纠正源选区');
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

test('legacy eco drafts normalize to supported model names',()=>{
 assert.equal(normalizeEditorState({}).generation_model,'gpt-image-2.5-flare');
 assert.equal(normalizeEditorState({generation_model:'gpt-image-2.5-flare-eco'}).generation_model,'gpt-image-2.5-flare');
 assert.equal(normalizeEditorState({generation_model:'gpt-image-2.5-sunburst'}).generation_model,'gpt-image-2.5-sunburst');
 assert.equal(normalizeEditorState({generation_model:'gpt-image-2.5-sunburst-eco'}).generation_model,'gpt-image-2.5-sunburst');
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

test('product limits allow 12 uploads and 20 mapping drafts',()=>{
 assert.equal(REFERENCE_UPLOAD_LIMIT,12);
 assert.equal(MAPPING_DRAFT_LIMIT,20);
 assert.equal(MODEL_REFERENCE_LIMIT,12);
});

test('generation reference guard counts mixed element and whole-image inputs but not main image',()=>{
 const state={main_image:'main',mappings:Array.from({length:11},(_,i)=>({id:`m${i}`})),full_image_refs:[{id:'whole'}]};
 assert.equal(generationReferenceCount(state),12);
 assert.doesNotThrow(()=>assertGenerationReferenceLimit(state));
 state.full_image_refs.push({id:'whole-2'});
 assert.throws(()=>assertGenerationReferenceLimit(state),/当前共 13 个实际参考输入，最多 12 个/);
});

test('candidate cycling follows canvas context and main wins while source is dragged',()=>{
 assert.equal(candidateSide({activeSide:'main',mainSelected:true,referenceSelected:true}),'main');
 assert.equal(candidateSide({activeSide:'reference',mainSelected:true,referenceSelected:true}),'reference');
 assert.equal(candidateSide({activeSide:'reference',draggingSource:true,mainSelected:true,referenceSelected:true}),'main');
 assert.equal(candidateSide({activeSide:null,mainSelected:false,referenceSelected:true}),'reference');
});

test('editable targets keep native Tab behavior including contenteditable descendants',()=>{
 assert.equal(isEditableTarget({tagName:'TEXTAREA',isContentEditable:false,closest:()=>null}),true);
 assert.equal(isEditableTarget({tagName:'SPAN',isContentEditable:false,closest:s=>s==='[contenteditable="true"]'?{}:null}),true);
 assert.equal(isEditableTarget({tagName:'CANVAS',isContentEditable:false,closest:()=>null}),false);
});

test('clipboard and drop extraction accepts only supported image bytes and deduplicates files',()=>{
 const png={name:'a.png',type:'image/png',size:10,lastModified:1},jpeg={name:'b.jpg',type:'image/jpeg',size:11,lastModified:2},gif={name:'c.gif',type:'image/gif',size:12,lastModified:3};
 const transfer={files:[png,jpeg,gif],items:[{kind:'file',getAsFile:()=>png},{kind:'string',type:'text/plain',getAsFile:()=>null}]};
 assert.deepEqual(imageFilesFromTransfer(transfer),[png,jpeg]);
 assert.deepEqual(imageFilesFromTransfer({files:[],items:[{kind:'string',type:'text/uri-list',getAsFile:()=>null}]}),[]);
});

test('masked drag preview preserves crop aspect ratio within its bounds',()=>{
 assert.deepEqual(dragPreviewSize([.1,.2,.9,.6],1000,500,120,96),{width:120,height:30});
 assert.deepEqual(dragPreviewSize([.2,.1,.4,.9],500,1000,120,96),{width:12,height:96});
});

test('main hover selection stays transient until non-empty text is confirmed',()=>{
 const state={mappings:[],next_display_index:4};
 const target={image_id:'main',image_version:1,mask_id:'mask',edit_region_id:'mask',anchor:{x:.4,y:.6}};
 const transient=createMainEditTransient(target,'recognized');
 assert.equal(transient.kind,'main-edit-transient');
 assert.equal(transient.label,'+');
 assert.equal(state.mappings.length,0);
 assert.equal(state.next_display_index,4);
 assert.deepEqual(commitMainEditTransient(state,transient,'  '),state);
 const committed=commitMainEditTransient(state,transient,'改成蓝色');
 assert.equal(committed.mappings.length,1);
 assert.equal(committed.mappings[0].kind,'main-edit');
 assert.equal(committed.mappings[0].requirement,'改成蓝色');
 assert.equal(committed.mappings[0].draft,false);
 assert.equal(committed.next_display_index,5);
});

test('main-image mapping remains a local square-bubble edit',()=>{
 const state={mappings:[],next_display_index:4};
 const target={image_id:'main',image_version:1,mask_id:'mask',edit_region_id:'mask',anchor:{x:.4,y:.6}};
 const mapping=createMainEditMapping(state,target,'recognized');
 assert.equal(mapping.kind,'main-edit');
 assert.equal(mapping.selection_method,'recognized');
 assert.equal(mapping.source,null);
 assert.equal(mapping.display_index,4);
});

test('main-image selection interaction consumes its click instead of opening preview',()=>{
 assert.deepEqual(consumePreviewSuppression({suppressNextPreviewClick:true}),{openPreview:false,suppressNextPreviewClick:false});
 assert.deepEqual(consumePreviewSuppression({suppressNextPreviewClick:false}),{openPreview:true,suppressNextPreviewClick:false});
});

test('empty unsent local edit is removed while confirmed and reference edits stay',()=>{
 const local={id:'local',kind:'main-edit',draft:true,requirement:'',display_index:1};
 const kept={id:'kept',kind:'main-edit',draft:false,requirement:'改成蓝色',display_index:2};
 const reference={id:'ref',kind:'reference-edit',draft:true,requirement:'',display_index:3};
 assert.deepEqual(removeEmptyDraftMapping({mappings:[local,kept,reference]},'local').mappings,[kept,reference]);
 assert.equal(removeEmptyDraftMapping({mappings:[local]},'local','移除').mappings.length,1);
});

test('serial action queue preserves invocation order across different completion delays',async()=>{
 const queue=new SerialActionQueue(),events=[];
 const first=queue.run(async()=>{events.push('first:start');await new Promise(r=>setTimeout(r,20));events.push('first:end');return 1;});
 const second=queue.run(async()=>{events.push('second:start');events.push('second:end');return 2;});
 assert.deepEqual(await Promise.all([first,second]),[1,2]);
 assert.deepEqual(events,['first:start','first:end','second:start','second:end']);
});

test('recognized text edits have stable identity and duplicate regions update instead of append',()=>{
 const detected={id:'ocr-7',text:'DesignKit',bbox:[.2,.3,.6,.4],confidence:.94};
 const first=createTextEdit('main',1,detected,'新品牌');
 assert.deepEqual({id:first.id,image_id:first.image_id,image_version:first.image_version,source:first.source,original_text:first.original_text,replacement:first.replacement,bbox:first.bbox},{id:'text:main:1:ocr-7',image_id:'main',image_version:1,source:'ocr',original_text:'DesignKit',replacement:'新品牌',bbox:[.2,.3,.6,.4]});
 let state=upsertTextEdit(normalizeEditorState({main_image:'main'}),first);
 state=upsertTextEdit(state,{...first,replacement:'DesignKit Pro'});
 assert.equal(state.text_edits.length,1);
 assert.equal(state.text_edits[0].replacement,'DesignKit Pro');
 assert.deepEqual(modifiedTextEdits({...state,text_edits:[...state.text_edits,{...first,id:'empty',replacement:'  '}]}),state.text_edits);
});

test('text edits appear in unified composer but do not count as image references',()=>{
 const state=normalizeEditorState({main_image:'main',text_edits:[{id:'t1',image_id:'main',image_version:1,source:'ocr',original_text:'旧字',replacement:'新字',bbox:[.1,.2,.3,.4]}]});
 assert.equal(generationReferenceCount(state),0);
 assert.deepEqual(composerEntries(state).map(x=>[x.kind,x.id,x.text]),[['text-edit','t1','旧字 → 新字'],['global','global','']]);
});

test('changing the main image clears text edits while unrelated reset paths can preserve snapshots',()=>{
 const old=normalizeEditorState({main_image:'old',mappings:[{id:'m'}],text_edits:[{id:'t'}]});
 const next=replaceMainImage(old,'new');
 assert.equal(next.main_image,'new');
 assert.deepEqual(next.mappings,[]);
 assert.deepEqual(next.text_edits,[]);
});

test('OCR hit testing uses the text polygon and prefers the smallest overlapping line',()=>{
 const broad={id:'broad',bbox:[.1,.1,.8,.4],polygon:[[.1,.1],[.8,.1],[.8,.4],[.1,.4]]};
 const line={id:'line',bbox:[.2,.2,.6,.3],polygon:[[.2,.2],[.6,.2],[.55,.3],[.2,.3]]};
 assert.equal(findTextRegion([broad,line],{x:.3,y:.25}).id,'line');
 assert.equal(findTextRegion([line],{x:.59,y:.29}),null);
 assert.equal(findTextRegion([line],{x:.3,y:.8}),null);
});

test('overlapping main candidates cycle text to every SAM mask and back without async result stealing text',()=>{
 const text={id:'line',text:'误识原文',bbox:[.2,.2,.6,.3]};
 let merged=mergeTypedCandidates(text,[],null);
 assert.deepEqual(merged.map(x=>x.kind),['text']);
 const selected=merged[0].key;
 merged=mergeTypedCandidates(text,[{id:'m1'},{id:'m2'},{id:'m3'}],selected);
 assert.equal(merged.find(x=>x.selected).kind,'text');
 let index=0;const kinds=[];
 for(let i=0;i<4;i++){index=nextTypedCandidate(merged,index);kinds.push(merged[index].kind);}
 assert.deepEqual(kinds,['segment','segment','segment','text']);
 assert.equal(mergeTypedCandidates(null,[{id:'m1'}],null).some(x=>x.kind==='text'),false);
});

test('effective text edit requires non-empty replacement different from confirmed original',()=>{
 assert.equal(isEffectiveTextEdit({original_text:' Café! ',replacement:'Café!'}),false);
 assert.equal(isEffectiveTextEdit({original_text:'Café!',replacement:'Cafe!'}),true);
 assert.equal(isEffectiveTextEdit({original_text:'Café!',replacement:'   '}),false);
 let state=normalizeEditorState({text_edits:[{id:'t',original_text:'旧字',replacement:'新字'}]});
 assert.equal(modifiedTextEdits(state).length,1);
 state=upsertTextEdit(state,{id:'t',original_text:'旧字',replacement:'旧字'});
 assert.equal(state.text_edits.length,0);
});
