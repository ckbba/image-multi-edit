export const TOUR_STEPS=[
 {selector:'#reference-wrap',fallback:'.reference-panel',title:'把参考元素拖到主图',body:'鼠标移到参考图上，选中想要的物品，再拖到主图要替换的位置。'},
 {selector:'#selection-bar',fallback:'.workspaces',title:'按 Tab，换一个选区',body:'没选对？把鼠标放在要选的图片上，按 Tab 换一个选区。'},
 {selector:'.recognition-toggle',fallback:'#pre-recognition',title:'想选整件物品？开启 AI 预识别',body:'开启后，后台识别图片里的物品；关闭也能选区和画笔编辑。'},
 {selector:'.model-pill',fallback:'#generation-model',title:'选一个生成模型',body:'想轻快些，选 flare；想稳准些，选 sunburst。'},
 {selector:'#manual-reference',fallback:'.reference-panel',title:'没选准？用魔法画笔',body:'点击「魔法画笔」，自己圈出想要的区域；主图和参考图都能用。'},
 {selector:'#text-edit',fallback:'#main-wrap',title:'点击无痕改字，修改主图文字',body:'打开大图后，点击文字或用「圈选多行」选择区域；填写新文并点 ✓ 加入编辑，最后点「生成」才生效。'},
 {selector:'.bubble-layer button,.mapping-number',fallback:'.operations',title:'点编号，告诉 AI 怎么改',body:'点击主图上的编号写修改要求，带黄点的编号表示已经填写。'},
 {selector:'#mapping-list .mapping-edit-body',fallback:'#mapping-list',title:'填写主体名称',body:'主体名称只补充文字提示，不会新建或重新识别选区；选错时请纠正源选区。'},
 {selector:'#mapping-list .subject-focus-toggle',fallback:'#mapping-list',title:'按需开启蒙版效果',body:'它会在实际模型参考输入里突出已选主体并压暗周边，不是把背景变透明。'},
 {selector:'#composer-editor [data-mapping-preview]',fallback:'#composer-editor',title:'悬停查看元素输入',body:'悬停元素标记可预览这条操作的实际模型输入，不会触发识别、保存或生成。'},
 {selector:'#composer-editor .composer-fragment.text-edit .composer-token',fallback:'#composer-editor',title:'从改字标记返回修改',body:'点击改字标记可回到对应主图文字，旁边的 × 只取消这处待生成改字。'},
 {selector:'#mention',fallback:'.requirements',title:'用 @ 引用整张参考图',body:'想参考整张图？点「@ 引用整图 / 元素」选图，再写下你想怎么改。'},
 {selector:'nav a[href="/history"]',fallback:'header nav',title:'到生成历史看结果',body:'生成后在这里看结果，也能恢复当时的编辑，或接着修改结果图。'}
];
const STEPS=TOUR_STEPS;
let index=0,root=null,target=null;
const $=selector=>document.querySelector(selector);
function ensureButton(){if($('#product-tour-start'))return;const button=document.createElement('button');button.id='product-tour-start';button.className='text-btn';button.type='button';button.textContent='？ 操作引导';button.onclick=startTour;$('.header-right')?.prepend(button);}
function resolve(step){return $(step.selector)||$(step.fallback)||$('#page');}
function position(){if(!root||!target)return;const rect=target.getBoundingClientRect(),spot=root.querySelector('.product-tour-spot'),card=root.querySelector('.product-tour-card'),pad=8;spot.style.cssText=`left:${Math.max(4,rect.left-pad)}px;top:${Math.max(4,rect.top-pad)}px;width:${Math.min(innerWidth-8,rect.width+pad*2)}px;height:${Math.min(innerHeight-8,rect.height+pad*2)}px`;requestAnimationFrame(()=>{const cw=card.offsetWidth,ch=card.offsetHeight;let left=Math.min(innerWidth-cw-12,Math.max(12,rect.right-cw));let top=rect.bottom+18;if(top+ch>innerHeight-12)top=Math.max(12,rect.top-ch-18);card.style.left=left+'px';card.style.top=top+'px';});}
function show(next){index=Math.max(0,Math.min(STEPS.length-1,next));const step=STEPS[index];target=resolve(step);target?.scrollIntoView({behavior:'instant',block:'center',inline:'nearest'});root.querySelector('h2').textContent=step.title;root.querySelector('p').textContent=step.body;root.querySelector('.product-tour-count').textContent=`${index+1} / ${STEPS.length}`;root.querySelector('[data-tour-prev]').disabled=index===0;root.querySelector('[data-tour-next]').textContent=index===STEPS.length-1?'完成':'下一步';root.dataset.step=String(index+1);position();}
export function stopTour(){if(!root)return;removeEventListener('resize',position);removeEventListener('scroll',position,true);root.remove();root=null;target=null;}
export function startTour(){stopTour();root=document.createElement('div');root.className='product-tour';root.innerHTML='<div class="product-tour-shade"></div><div class="product-tour-spot" aria-hidden="true"></div><section class="product-tour-card" role="dialog" aria-modal="true" aria-label="操作引导"><button class="product-tour-close" type="button" aria-label="退出引导">×</button><h2></h2><p></p><footer><span class="product-tour-count"></span><div><button type="button" data-tour-prev>上一步</button><button type="button" class="primary" data-tour-next>下一步</button></div></footer></section>';document.body.append(root);root.querySelector('.product-tour-close').onclick=stopTour;root.querySelector('.product-tour-shade').onclick=stopTour;root.querySelector('[data-tour-prev]').onclick=()=>show(index-1);root.querySelector('[data-tour-next]').onclick=()=>index===STEPS.length-1?stopTour():show(index+1);addEventListener('resize',position);addEventListener('scroll',position,true);show(0);root.querySelector('.product-tour-close').focus();}
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&root){event.preventDefault();event.stopImmediatePropagation();stopTour();}},true);
export function mountTour(){ensureButton();}
