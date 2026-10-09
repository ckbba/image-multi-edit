// History is read-only; workspace can provide a manual-selection callback.
export function openPreview(items, initial=0, marked=false, options={}){
  document.querySelector('.image-viewer')?.close();
  const dialog=document.createElement('dialog');dialog.className='image-viewer';dialog.id='image-viewer';
  dialog.setAttribute('aria-label','图片预览');
  dialog.innerHTML=`<header class="viewer-head"><strong id="viewer-title"></strong><div class="viewer-tools"><button id="viewer-out" aria-label="缩小图片">−</button><output id="viewer-scale"></output><button id="viewer-in" aria-label="放大图片">＋</button><button id="viewer-fit">适应窗口</button><button id="viewer-close">关闭 ×</button></div></header><div class="viewer-options"><label><input id="viewer-regions" type="checkbox">显示当时编辑区域</label><span id="viewer-note"></span></div><div class="viewer-stage"><canvas aria-label="放大图片画布"></canvas><p class="viewer-loading" role="status">正在加载原图…</p></div><nav class="viewer-gallery" aria-label="切换预览图片"></nav><footer class="viewer-foot">滚轮缩放 · 按住图片拖动 · Esc 关闭</footer>`;
  const find=s=>dialog.querySelector(s),stage=find('.viewer-stage'),canvas=find('canvas'),ctx=canvas.getContext('2d');
  let index=initial,im=null,regions=[],version=0,scale=1,x=0,y=0,panning=null,regionDrag=null;
  const cache=new Map();
  function load(id){if(!cache.has(id))cache.set(id,new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('图片加载失败，请关闭后重试'));image.src='/api/assets/'+id;}));return cache.get(id);}
  function transform(){
    if(!im)return;
    const w=stage.clientWidth,h=stage.clientHeight,dw=im.width*scale,dh=im.height*scale;
    x=dw<w?(w-dw)/2:Math.max(w-dw,Math.min(0,x));y=dh<h?(h-dh)/2:Math.max(h-dh,Math.min(0,y));
    canvas.style.transform=`translate(${x}px,${y}px) scale(${scale})`;
    find('#viewer-scale').value=Math.round(scale*100)+'%';canvas.dataset.scale=String(scale);
  }
  function fit(){if(!im)return;scale=Math.min(stage.clientWidth/im.width,stage.clientHeight/im.height,1);x=0;y=0;transform();}
  function zoom(factor,px=stage.clientWidth/2,py=stage.clientHeight/2){
    if(!im)return;const next=Math.max(.03,Math.min(16,scale*factor));x=px-(px-x)*next/scale;y=py-(py-y)*next/scale;scale=next;transform();
  }
  function paint(){
    if(!im)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(im,0,0);
    const show=find('#viewer-regions').checked;canvas.dataset.regions=show?regions.map(r=>r.number).join(','):'';
    if(!show)return;
    for(const region of regions){
      ctx.globalAlpha=.25;ctx.drawImage(region.tint,0,0,im.width,im.height);ctx.globalAlpha=1;
    }
    for(const region of regions){
      const radius=Math.max(im.width,im.height)*.023,px=region.anchor.x*im.width,py=region.anchor.y*im.height;
      ctx.fillStyle=region.color;ctx.beginPath();ctx.arc(px,py,radius,0,Math.PI*2);ctx.fill();
      ctx.fillStyle='white';ctx.font=`bold ${Math.round(radius*1.15)}px system-ui`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(String(region.number),px,py);
    }
  }
  async function select(next){
    index=next;const token=++version,item=items[index];im=null;regions=[];canvas.hidden=true;
    find('#viewer-title').textContent=item.title;find('.viewer-loading').hidden=false;find('.viewer-loading').textContent='正在加载原图…';
    find('#viewer-regions').parentElement.hidden=!item.regions?.length;
    find('#viewer-note').textContent=item.regions?.length?'保存的输入选区，不代表模型实际修改边界':'';
    for(const [i,button] of [...find('.viewer-gallery').children].entries())button.setAttribute('aria-pressed',String(i===index));
    try{
      const image=await load(item.id);
      const masks=await Promise.all((item.regions||[]).map(async region=>{
        const mask=await load(region.mask_id),tint=document.createElement('canvas');tint.width=mask.width;tint.height=mask.height;
        const c=tint.getContext('2d');c.drawImage(mask,0,0);c.globalCompositeOperation='source-in';c.fillStyle=region.color;c.fillRect(0,0,tint.width,tint.height);return {...region,tint};
      }));
      if(token!==version||!dialog.open)return;im=image;regions=masks;canvas.width=im.width;canvas.height=im.height;canvas.dataset.assetId=item.id;canvas.hidden=false;find('.viewer-loading').hidden=true;paint();fit();
    }catch(error){if(token===version&&dialog.open)find('.viewer-loading').textContent=error.message;}
  }
  items.forEach((item,i)=>{const button=document.createElement('button');button.textContent=item.title;button.onclick=()=>select(i);find('.viewer-gallery').append(button);});
  find('.viewer-gallery').hidden=items.length<2;
  if(items[initial].detailHref){const link=document.createElement('a');link.href=items[initial].detailHref;link.textContent='查看历史详情 →';find('.viewer-foot').append(link);}
  find('#viewer-regions').checked=marked;find('#viewer-regions').onchange=paint;
  find('#viewer-in').onclick=()=>zoom(1.25);find('#viewer-out').onclick=()=>zoom(.8);find('#viewer-fit').onclick=fit;find('#viewer-close').onclick=()=>dialog.close();
  stage.addEventListener('wheel',event=>{event.preventDefault();const box=stage.getBoundingClientRect(),delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?stage.clientHeight:1);zoom(Math.exp(-Math.max(-300,Math.min(300,delta))*.002),event.clientX-box.left,event.clientY-box.top);},{passive:false});
  stage.onpointerdown=event=>{if(event.button!==0||!im)return;event.preventDefault();const box=stage.getBoundingClientRect(),ix=(event.clientX-box.left-x)/scale/im.width,iy=(event.clientY-box.top-y)/scale/im.height,region=options.onRegionDrop&&regions.find(r=>Math.hypot(ix-r.anchor.x,iy-r.anchor.y)<.07);if(region){regionDrag={region,sx:event.clientX,sy:event.clientY,moved:false};stage.setPointerCapture(event.pointerId);return;}panning={px:event.clientX,py:event.clientY,x,y};stage.setPointerCapture(event.pointerId);stage.classList.add('panning');};
  stage.onpointermove=event=>{if(regionDrag){if(Math.hypot(event.clientX-regionDrag.sx,event.clientY-regionDrag.sy)>6){regionDrag.moved=true;dialog.classList.add('drag-fading');}return;}if(!panning)return;x=panning.x+event.clientX-panning.px;y=panning.y+event.clientY-panning.py;transform();};
  stage.onpointerup=event=>{if(regionDrag){const active=regionDrag;regionDrag=null;dialog.classList.remove('drag-fading');if(active.moved){dialog.close();options.onRegionDrop(active.region,event.clientX,event.clientY);}return;}panning=null;stage.classList.remove('panning');};stage.onpointercancel=()=>{regionDrag=null;dialog.classList.remove('drag-fading');panning=null;stage.classList.remove('panning');};
  const resize=new ResizeObserver(fit);
  if(options.minimal){
    dialog.classList.add('minimal-viewer');
    const tools=document.createElement('div');tools.className='magic-tools';
    tools.innerHTML='<button id="magic-out" aria-label="缩小图片">−</button><button id="magic-brush" aria-pressed="false" aria-label="魔法画笔" title="魔法画笔">✦</button><button id="magic-in" aria-label="放大图片">＋</button><button id="magic-close" aria-label="关闭图片">×</button><span class="magic-status" role="status">滚轮缩放 · 拖动查看</span>';dialog.append(tools);
    const brush=tools.querySelector('#magic-brush'),close=tools.querySelector('#magic-close'),status=tools.querySelector('[role="status"]');
    const cursor=document.createElement('i');cursor.className='magic-cursor';cursor.innerHTML='<span></span>';cursor.setAttribute('aria-hidden','true');dialog.append(cursor);
    let drawing=false,points=null,pointerId=null,busy=false;
    const panDown=stage.onpointerdown,panMove=stage.onpointermove,panUp=stage.onpointerup;
    function position(event){const b=stage.getBoundingClientRect();return [(event.clientX-b.left-x)/scale/im.width,(event.clientY-b.top-y)/scale/im.height];}
    function trace(){paint();if(!points?.length)return;ctx.strokeStyle='#b7fa73';ctx.lineWidth=2/scale;ctx.lineJoin='round';ctx.lineCap='round';ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p[0]*im.width,p[1]*im.height):ctx.moveTo(p[0]*im.width,p[1]*im.height));ctx.stroke();}
    brush.onclick=()=>{if(busy)return;drawing=!drawing;points=null;paint();brush.setAttribute('aria-pressed',String(drawing));stage.classList.toggle('magic-drawing',drawing);cursor.classList.toggle('active',drawing);status.textContent=drawing?'按住圈画 · 松开完成 · Esc 取消':'滚轮缩放 · 拖动查看';};
    tools.querySelector('#magic-in').onclick=()=>zoom(1.25);tools.querySelector('#magic-out').onclick=()=>zoom(.8);
    close.onclick=()=>dialog.close();
    stage.onpointerdown=event=>{if(busy)return;if(!drawing){panDown(event);return;}if(event.button!==0||!im)return;const p=position(event);if(p.some(v=>v<0||v>1))return;event.preventDefault();pointerId=event.pointerId;points=[p];stage.setPointerCapture(pointerId);};
    stage.onpointermove=event=>{cursor.style.transform=`translate3d(${event.clientX}px,${event.clientY}px,0) rotate(-28deg)`;if(!drawing){panMove(event);return;}if(!points||event.pointerId!==pointerId)return;const p=position(event).map(v=>Math.max(0,Math.min(1,v))),last=points.at(-1);if(Math.hypot((p[0]-last[0])*im.width*scale,(p[1]-last[1])*im.height*scale)<2)return;if(points.length>=499)points=points.filter((_,i)=>i%2===0);points.push(p);trace();};
    stage.onpointerup=async event=>{if(!drawing){panUp(event);return;}if(!points||event.pointerId!==pointerId)return;stage.onpointermove(event);const selected=points;points=null;pointerId=null;if(stage.hasPointerCapture(event.pointerId))stage.releasePointerCapture(event.pointerId);let area=0;selected.forEach((a,i)=>{const b=selected[(i+1)%selected.length];area+=a[0]*b[1]-b[0]*a[1];});if(selected.length<3||Math.abs(area)*im.width*im.height*scale*scale/2<16){paint();status.textContent='请圈出一个区域，松开完成';return;}busy=true;brush.disabled=true;status.textContent='正在保存选区…';try{await options.onDraw(selected);if(dialog.open)dialog.close();}catch(error){if(dialog.open){status.textContent=error.message;paint();}}finally{busy=false;brush.disabled=false;}};
    stage.onpointercancel=()=>{points=null;pointerId=null;panUp();paint();};stage.onpointerleave=()=>cursor.classList.remove('visible');stage.onpointerenter=()=>cursor.classList.add('visible');
    stage.addEventListener('wheel',()=>{if(points){points=null;pointerId=null;paint();status.textContent='缩放后请重新圈画';}},{passive:true});
    dialog.addEventListener('cancel',event=>{if(points){event.preventDefault();points=null;pointerId=null;paint();status.textContent='已取消本次圈画';}});
  }
  const previousFocus=document.activeElement;
  dialog.addEventListener('pointerdown',event=>{if(event.target===dialog)dialog.close();});
  dialog.addEventListener('close',()=>{version++;resize.disconnect();options.onClose?.();dialog.remove();if(previousFocus?.isConnected)previousFocus.focus();},{once:true});
  document.body.append(dialog);dialog.showModal();resize.observe(stage);select(initial);
}
