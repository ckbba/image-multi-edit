import test from 'node:test';
import assert from 'node:assert/strict';
import {removeReference,referenceUsage,UndoStack} from '../前端代码/core.js';
test('reference deletion cascades only its bindings and preserves stable numbering, undo restores',()=>{
 const s={references:['a','b'],mappings:[{id:'m1',display_index:1,source:{image_id:'a'}},{id:'m4',display_index:4,source:{image_id:'b'}},{id:'m5',display_index:5,source:null}],full_image_refs:[{id:'r1',image_id:'a'}],text_edits:[{id:'t'}],next_display_index:6};
 assert.deepEqual(referenceUsage(s,'a'),{elements:1,whole:1});
 const undo=new UndoStack();undo.push(s);const next=removeReference(s,'a');
 assert.deepEqual(next.references,['b']);assert.deepEqual(next.mappings.map(m=>m.display_index),[4,5]);assert.equal(next.next_display_index,6);assert.equal(next.text_edits.length,1);assert.equal(next.full_image_refs.length,0);assert.deepEqual(undo.undo(next),s);
});
