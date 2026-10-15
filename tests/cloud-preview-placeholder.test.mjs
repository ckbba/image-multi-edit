import fs from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
const source=fs.readFileSync(new URL('../前端代码/cloud-preview.js',import.meta.url),'utf8');
test('five image tools have distinct named icons and one disabled video placeholder',()=>{
  const definitions=source.match(/const tools=\[(.*?)\];/s)?.[1]||'';
  for(const [key,icon] of [['remove-background','removeBg'],['expand','expand'],['deblur','deblur'],['magic-eraser','erase'],['magic-redraw','redraw'],['image-to-video','video']])assert.ok(definitions.includes(`['${key}'`)&&definitions.includes(`glyph.${icon}`),key);
  assert.ok(source.includes("key==='image-to-video'?'disabled':''"));
  assert.ok(source.includes('data-apply disabled')&&source.includes('data-save disabled'));
  assert.ok(source.includes('此工具尚未接入真实图片处理服务'));
});
