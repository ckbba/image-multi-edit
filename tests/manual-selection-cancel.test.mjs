import test from 'node:test';
import assert from 'node:assert/strict';
import {shouldClearManualSelection} from '../前端代码/core.js';

test('only an unmodified click outside the manual mask clears it',()=>{
  const inside=()=>true,outside=()=>false;
  assert.equal(shouldClearManualSelection({manual:true,point:{x:.8,y:.8},contains:outside,moved:false}),true);
  assert.equal(shouldClearManualSelection({manual:true,point:{x:.3,y:.3},contains:inside,moved:false}),false);
  assert.equal(shouldClearManualSelection({manual:true,point:{x:.8,y:.8},contains:outside,moved:true}),false);
  assert.equal(shouldClearManualSelection({manual:false,point:{x:.8,y:.8},contains:outside,moved:false}),false);
  assert.equal(shouldClearManualSelection({manual:true,point:null,contains:outside,moved:false}),false);
});
