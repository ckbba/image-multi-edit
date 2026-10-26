const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

let deps;
let current='all';
const busyLikes=new Set();
const busyWorkspace=new Set();
let workspaceQueue=Promise.resolve();
let stickyCleanup=()=>{};
export function unmountInspiration(){stickyCleanup();stickyCleanup=()=>{};}
const run=action=>async()=>{try{await action();}catch(error){deps.toast(error.message||'操作失败，请重试');}};
const likeLabel=item=>`${item.liked?'❤️':'♡'} ${item.like_count||0}`;

function card(item){
  return `<article class="inspiration-card" data-id="${item.id}">
    <div class="inspiration-image" style="aspect-ratio:${item.width}/${item.height}">
      <button class="inspiration-open" data-open aria-label="查看 ${esc(item.title)}"><img src="/api/inspiration/${item.id}/image?thumbnail=true" alt="${esc(item.title)}" loading="lazy" decoding="async"></button>
      <button class="inspiration-favorite ${item.favorite?'active':''}" data-favorite aria-label="${item.favorite?'已收藏':'收藏到云盘'}" aria-pressed="${item.favorite}">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.8h12a1 1 0 0 1 1 1V21l-7-4-7 4V4.8a1 1 0 0 1 1-1Z"/></svg>
      </button>
      <button class="inspiration-use" data-workspace>添加到工作区</button>
    </div>
    <div class="inspiration-meta"><div><h3><button class="inspiration-title" data-open>${esc(item.title)}</button></h3><p>${esc(item.category)} · 可作为参考图使用</p></div><button class="inspiration-like ${item.liked?'active':''}" data-like aria-label="${item.liked?'取消点赞':'点赞'}" aria-pressed="${Boolean(item.liked)}">${likeLabel(item)}</button><button data-drive>${item.favorite?'已收藏':'收藏'}</button></div>
  </article>`;
}

async function load(){
  const data=await deps.publicApi('/inspiration?category='+encodeURIComponent(current));
  const tabs=document.querySelector('#inspiration-tabs');
  tabs.innerHTML=`<button data-category="all" class="${current==='all'?'active':''}">全部</button>${data.categories.map(category=>`<button data-category="${esc(category)}" class="${current===category?'active':''}">${esc(category)}</button>`).join('')}`;
  document.querySelector('#inspiration-grid').innerHTML=data.items.length?data.items.map(card).join(''):'<div class="inspiration-empty">这个分类暂时没有作品</div>';
  tabs.querySelectorAll('[data-category]').forEach(button=>button.onclick=async()=>{current=button.dataset.category;await load();});
  document.querySelectorAll('.inspiration-card').forEach(element=>bindCard(element,data.items.find(item=>item.id===element.dataset.id)));
}

function bindCard(element,item){
  element.querySelectorAll('[data-open]').forEach(button=>button.onclick=()=>openDetail(item));
  element.querySelector('[data-like]').onclick=run(()=>like(item));
  element.querySelector('[data-favorite]').onclick=run(()=>favorite(item,element));
  element.querySelector('[data-drive]').onclick=run(()=>favorite(item,element));
  element.querySelector('[data-workspace]').onclick=run(()=>workspace(item,element));
}

function workspaceFeedback(item,origin,count){
  const target=document.querySelector('#app> .inspiration-header-slot header nav a[href="/"]');
  if(!target)return;
  let badge=target.querySelector('.workspace-count');
  if(!badge){badge=document.createElement('span');badge.className='workspace-count';target.append(badge);}
  badge.textContent=count;badge.setAttribute('aria-label',`${count} 张参考图`);
  const arrive=()=>{
    if(!target.isConnected)return;
    target.classList.remove('workspace-received');void target.offsetWidth;target.classList.add('workspace-received');
    target.onanimationend=()=>target.classList.remove('workspace-received');
  };
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){arrive();return;}
  const source=origin?.isConnected?origin:document.querySelector(`.inspiration-card[data-id="${item.id}"]`);
  const from=source?.querySelector('img')?.getBoundingClientRect();
  if(!from){arrive();return;}
  const to=target.getBoundingClientRect(),size=52;
  const x=Math.max(0,Math.min(innerWidth-size,from.left+from.width/2-size/2));
  const y=Math.max(to.bottom+12,Math.min(innerHeight-size,from.top+Math.min(from.height,160)/2-size/2));
  const fly=document.createElement('img');fly.className='workspace-flying-image';fly.alt='';
  fly.src=`/api/inspiration/${item.id}/image?thumbnail=true`;fly.style.left=`${x}px`;fly.style.top=`${y}px`;document.body.append(fly);
  const dx=to.left+to.width/2-size/2-x,dy=to.top+to.height/2-size/2-y;
  const animation=fly.animate([{transform:'translate(0,0) scale(1)',opacity:1},{transform:`translate(${dx*.45}px,${dy*.65-30}px) scale(.8)`,opacity:1,offset:.55},{transform:`translate(${dx}px,${dy}px) scale(.2)`,opacity:0}],{duration:650,easing:'cubic-bezier(.22,.68,.36,1)'});
  animation.finished.then(arrive).finally(()=>fly.remove());
}

async function workspace(item,origin){
  await deps.requireAuth(async()=>{
    if(busyWorkspace.has(item.id))return;
    busyWorkspace.add(item.id);
    const buttons=[...document.querySelectorAll(`[data-id="${item.id}"] [data-workspace]`)];
    buttons.forEach(b=>{b.disabled=true;b.textContent='添加中…';});
    const task=workspaceQueue.then(async()=>{
      const result=await deps.api(`/inspiration/${item.id}/workspace`,{method:'POST'});
      deps.setEditorState(result.draft,result.asset.id);
      const detail=document.querySelector('.inspiration-detail');
      if(detail){origin=document.querySelector(`.inspiration-card[data-id="${item.id}"]`);detail.close();}
      buttons.forEach(b=>{b.textContent='✓ 已添加';});
      workspaceFeedback(item,origin,result.draft.references.length);
      deps.toast('已添加到上方「编辑工作区」，可以继续挑选素材');
    });
    workspaceQueue=task.catch(()=>{});
    try{await task;}catch(error){buttons.forEach(b=>b.textContent='添加到工作区');throw error;}
    finally{busyWorkspace.delete(item.id);buttons.forEach(b=>b.disabled=false);}
  });
}

async function like(item){
  await deps.requireAuth(async()=>{
    if(busyLikes.has(item.id))return;
    busyLikes.add(item.id);
    try{
      Object.assign(item,await deps.api(`/inspiration/${item.id}/like`,{method:'PUT',body:{liked:!item.liked}}));
      document.querySelectorAll(`[data-id="${item.id}"] [data-like]`).forEach(button=>{
        button.textContent=likeLabel(item);button.classList.toggle('active',item.liked);
        button.setAttribute('aria-pressed',String(item.liked));
        button.setAttribute('aria-label',item.liked?'取消点赞':'点赞');
      });
    }finally{busyLikes.delete(item.id);}
  });
}

function openDetail(item){
  document.querySelector('.inspiration-detail')?.remove();
  const dialog=document.createElement('dialog');
  dialog.className='inspiration-detail';dialog.dataset.id=item.id;
  dialog.setAttribute('aria-labelledby','inspiration-detail-title');
  const sourceUrl=/^https:\/\//i.test(item.source_url||'')?item.source_url:'';
  dialog.innerHTML=`<button class="inspiration-detail-close" aria-label="关闭图片详情">×</button>
    <div class="inspiration-detail-layout"><div class="inspiration-detail-image"><img src="/api/inspiration/${item.id}/image" alt="${esc(item.title)}"></div>
    <section class="inspiration-detail-info"><span class="inspiration-detail-category">${esc(item.category)}</span><h2 id="inspiration-detail-title">${esc(item.title)}</h2>
    <p class="inspiration-description">${esc(item.description||'可用于构图、配色和素材融合参考。')}</p>
    <p class="inspiration-source">${esc(item.source||'精选灵感')} · ${item.width} × ${item.height}</p>
    ${sourceUrl?`<a class="inspiration-source-link" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a>`:''}
    <div class="inspiration-detail-actions"><button class="inspiration-like ${item.liked?'active':''}" data-like aria-label="${item.liked?'取消点赞':'点赞'}" aria-pressed="${Boolean(item.liked)}">${likeLabel(item)}</button><button data-save>${item.favorite?'已收藏到云盘':'收藏到云盘'}</button><button class="primary" data-workspace>添加到工作区</button></div></section></div>`;
  document.body.append(dialog);
  dialog.querySelector('.inspiration-detail-close').onclick=()=>dialog.close();
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  dialog.addEventListener('close',()=>dialog.remove());
  dialog.querySelector('[data-like]').onclick=run(()=>like(item));
  dialog.querySelector('[data-workspace]').onclick=run(()=>workspace(item,dialog));
  dialog.querySelector('[data-save]').onclick=run(async()=>{await favorite(item,document.querySelector(`.inspiration-card[data-id="${item.id}"]`));if(item.favorite)dialog.querySelector('[data-save]').textContent='已收藏到云盘';});
  dialog.showModal();
}

async function favorite(item,element){
  await deps.requireAuth(async()=>{
    if(item.favorite){deps.toast('已收藏到云盘');return;}
    await deps.api(`/inspiration/${item.id}/drive`,{method:'POST'});
    await deps.api(`/inspiration/${item.id}/favorite`,{method:'PUT',body:{favorite:true}});
    item.favorite=true;
    element=document.querySelector(`.inspiration-card[data-id="${item.id}"]`);
    if(!element)return;
    element.outerHTML=card(item);
    const next=document.querySelector(`.inspiration-card[data-id="${item.id}"]`);bindCard(next,item);
    deps.toast('已收藏到云盘');
  });
}

export async function mountInspiration(options){
  deps=options;
  deps.shell('inspiration',{publicPage:true});
  document.querySelector('#page').innerHTML=`<section class="inspiration-hero"><span>DISCOVER · REMIX · CREATE</span><h1>先看见，再想象。</h1><p>从精选视觉中找到你的下一个画面。收藏到云盘，或直接带进工作区继续创作。</p><a href="/" data-nav>开始自由创作 →</a></section><nav id="inspiration-tabs" class="inspiration-tabs" aria-label="灵感分类"></nav><section id="inspiration-grid" class="inspiration-grid" aria-live="polite"></section>`;
  deps.bindNav();
  const header=document.querySelector('#app>header'),page=document.querySelector('#page'),hero=page.querySelector('.inspiration-hero');
  const expandedHeight=header.getBoundingClientRect().height;
  const slot=document.createElement('div');slot.className='inspiration-header-slot';header.before(slot);slot.append(header);
  slot.style.height=`${expandedHeight}px`;
  let frame;
  const update=()=>{frame=null;slot.classList.toggle('is-compact',hero.getBoundingClientRect().bottom<=expandedHeight);};
  const onScroll=()=>{if(!frame)frame=requestAnimationFrame(update);};
  const resize=new ResizeObserver(()=>page.style.setProperty('--inspiration-header-height',`${header.getBoundingClientRect().height}px`));
  resize.observe(header);window.addEventListener('scroll',onScroll,{passive:true});window.addEventListener('resize',onScroll);
  stickyCleanup=()=>{resize.disconnect();window.removeEventListener('scroll',onScroll);window.removeEventListener('resize',onScroll);cancelAnimationFrame(frame);document.querySelectorAll('.workspace-flying-image').forEach(el=>el.remove());};
  update();
  await load();
}
