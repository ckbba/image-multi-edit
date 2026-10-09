import test from 'node:test';
import assert from 'node:assert/strict';
import {imageRect,toImage,createMapping,addMapping,UndoStack,LatestRequest,COLORS} from '../前端代码/core.js';

test('letterbox coordinates remain stable across viewport sizes; margins reject points',()=>{
 for(const [w,h] of [[500,400],[200,700],[1200,500]]){const r=imageRect(w,h,1200,800);const p=toImage(r.x+r.width*.25,r.y+r.height*.75,r);assert.ok(Math.abs(p.x-.25)<1e-10);assert.ok(Math.abs(p.y-.75)<1e-10);assert.equal(toImage(r.x-1,r.y,r),null);}
});
test('deletion, undo and redo preserve IDs, colors and monotonic display number',()=>{
 let s={mappings:[],next_display_index:1};const u=new UndoStack();for(let i=0;i<3;i++)s=addMapping(s,createMapping(s,{image_id:'ref'},{image_id:'main'}));const old=structuredClone(s);u.push(s);s.mappings.splice(1,1);const newMapping=createMapping(s,{},{});assert.equal(newMapping.display_index,4);s=addMapping(s,newMapping);assert.deepEqual(s.mappings.map(m=>m.display_index),[1,3,4]);s=u.undo(s);assert.deepEqual(s,old);s=u.redo(s);assert.equal(s.mappings[1].id,old.mappings[2].id);assert.equal(s.mappings[1].color,COLORS[2]);
});
test('late selection cannot replace newer image/point; old request is aborted',()=>{const req=new LatestRequest();const a=req.start(),b=req.start();assert.equal(a.signal.aborted,true);assert.equal(req.current(a.version),false);assert.equal(req.current(b.version),true);req.cancel();assert.equal(req.current(b.version),false);});
