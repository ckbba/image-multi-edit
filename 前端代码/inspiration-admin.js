const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const endpoint='/admin/inspiration';

export async function mountInspirationAdmin(deps){
  deps.shell('admin',{publicPage:true});
  const root=document.querySelector('#page');
  root.innerHTML='<section class="admin-page"><h1>灵感管理</h1><p>正在读取管理权限…</p></section>';
  let data;
  try{data=await deps.api(endpoint);}catch(error){root.querySelector('p').textContent=error.message;return;}
  let filter='active',category='',query='';
  const attempt=action=>async()=>{try{await action();}catch(error){deps.toast(error.message||'操作失败');}};
  const refresh=async()=>{data=await deps.api(endpoint);render();};
  const options=value=>data.categories.map(c=>`<option value="${esc(c.name)}" ${c.name===value?'selected':''}>${esc(c.name)}</option>`).join('');
  function render(){
    const counts={published:data.items.filter(x=>x.published).length,trash:data.items.filter(x=>x.deleted_at!=null).length};
    root.innerHTML=`<section class="admin-page"><div class="admin-heading"><div><span>STUDIO / ADMIN</span><h1>灵感管理</h1><p>已发布 ${counts.published} 张 · 回收站 ${counts.trash} 张</p></div><div><button id="admin-categories">管理分类</button><button class="primary" id="admin-upload">＋ 上传图片</button></div></div>
      <div class="admin-filters"><label>搜索<input id="admin-search" placeholder="搜索标题或简介" value="${esc(query)}"></label><label>分类<select id="admin-category"><option value="">全部分类</option>${options(category)}</select></label><label>状态<select id="admin-filter"><option value="active">全部图片</option><option value="published">已发布</option><option value="draft">未发布</option><option value="trash">回收站</option></select></label></div><div id="admin-items" class="admin-items"></div></section>`;
    root.querySelector('#admin-filter').value=filter;
    root.querySelector('#admin-search').oninput=e=>{query=e.target.value;renderItems();};
    root.querySelector('#admin-category').onchange=e=>{category=e.target.value;renderItems();};
    root.querySelector('#admin-filter').onchange=e=>{filter=e.target.value;renderItems();};
    root.querySelector('#admin-upload').onclick=()=>edit();
    root.querySelector('#admin-categories').onclick=()=>categories();
    renderItems();deps.bindNav();
  }
  function renderItems(){
    const items=data.items.filter(x=>(filter==='trash'?x.deleted_at!=null:x.deleted_at==null)&&(!category||x.category===category)&&(!query||(x.title+' '+x.description).toLowerCase().includes(query.toLowerCase()))&&(filter!=='published'||x.published)&&(filter!=='draft'||!x.published));
    const list=root.querySelector('#admin-items');
    list.innerHTML=items.length?items.map(x=>`<article class="admin-item"><img src="/api${endpoint}/items/${x.id}/image" alt="${esc(x.title)}" loading="lazy"><div><span class="admin-status">${x.deleted_at!=null?'回收站':x.published?'已发布':'未发布'}</span><h3>${esc(x.title)}</h3><p>${esc(x.category)} · ❤️ ${x.like_count}</p><div class="admin-item-actions">${x.deleted_at!=null?`<button data-restore="${x.id}">恢复为未发布</button>`:`<button data-edit="${x.id}">编辑</button><button data-publish="${x.id}">${x.published?'下架':'发布'}</button><button class="danger" data-trash="${x.id}">删除</button>`}</div></div></article>`).join(''):'<p class="admin-empty">没有符合条件的图片</p>';
    list.querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>edit(data.items.find(x=>x.id===b.dataset.edit)));
    list.querySelectorAll('[data-publish]').forEach(b=>b.onclick=attempt(async()=>{const x=data.items.find(x=>x.id===b.dataset.publish);await deps.api(`${endpoint}/items/${x.id}`,{method:'PUT',body:metadata(x,!x.published)});await refresh();}));
    list.querySelectorAll('[data-trash]').forEach(b=>b.onclick=attempt(async()=>{if(!confirm('将这张图片移入回收站？灵感页会立即隐藏，已有收藏副本不会被删除。'))return;await deps.api(`${endpoint}/items/${b.dataset.trash}`,{method:'DELETE'});await refresh();deps.toast('已移入回收站，可恢复');}));
    list.querySelectorAll('[data-restore]').forEach(b=>b.onclick=attempt(async()=>{await deps.api(`${endpoint}/items/${b.dataset.restore}/restore`,{method:'POST'});await refresh();deps.toast('已恢复，请在未发布中检查并发布');}));
  }
  function metadata(x,published=Boolean(x.published)){return {title:x.title,category:x.category,description:x.description||'',source:x.source||'',source_url:x.source_url||'',published};}
  function modal(title,body){
    const d=document.createElement('dialog');d.className='admin-dialog';d.setAttribute('aria-label',title);
    d.innerHTML=`<button class="admin-close" type="button" aria-label="关闭管理弹窗">×</button><h2>${title}</h2>${body}`;
    document.body.append(d);d.querySelector('.admin-close').onclick=()=>d.close();d.addEventListener('close',()=>d.remove());d.showModal();return d;
  }
  function edit(item){
    if(!data.categories.length){deps.toast('请先新增分类');categories();return;}
    const d=modal(item?'编辑图片':'上传图片',`<form class="admin-form">${item?`<img class="admin-edit-preview" src="/api${endpoint}/items/${item.id}/image" alt="${esc(item.title)}">`:'<label>图片（可多选）<input name="files" type="file" accept="image/png,image/jpeg,image/webp" multiple required></label><small>PNG / JPEG / WebP · 单张 ≤ 20 MB；多张图片使用各自文件名作为标题</small><div class="admin-upload-previews"></div>'}
      <label>标题<input name="title" maxlength="160" value="${esc(item?.title||'')}" ${item?'required':''} placeholder="单张可自定义；留空使用文件名"></label>
      <label>分类<select name="category" required>${options(item?.category||category)}</select></label>
      <label>简介<textarea name="description" maxlength="3000" rows="4">${esc(item?.description||'')}</textarea></label>
      <label>来源说明<input name="source" maxlength="200" value="${esc(item?.source||'')}" placeholder="例如：本人拍摄、供应商素材"></label>
      <label>来源链接（选填）<input name="source_url" type="url" maxlength="2000" value="${esc(item?.source_url||'')}"></label>
      <label class="admin-check"><input name="published" type="checkbox" ${item?.published?'checked':''}>发布到灵感页</label>
      <p class="admin-feedback" role="status"></p><button class="primary" type="submit">${item?'保存修改':'开始上传'}</button></form>`);
    const form=d.querySelector('form'),feedback=d.querySelector('.admin-feedback');let urls=[],succeeded=new Set(),working=false;
    d.addEventListener('close',()=>urls.forEach(URL.revokeObjectURL));
    d.addEventListener('cancel',e=>{if(working)e.preventDefault();});
    if(!item)form.elements.files.onchange=()=>{urls.forEach(URL.revokeObjectURL);succeeded.clear();urls=[...form.elements.files.files].map(file=>URL.createObjectURL(file));d.querySelector('.admin-upload-previews').innerHTML=urls.map(url=>`<img src="${url}" alt="待上传图片">`).join('');};
    form.onsubmit=async event=>{
      event.preventDefault();if(working)return;
      const values=new FormData(form),body={title:String(values.get('title')).trim(),category:values.get('category'),description:values.get('description'),source:values.get('source'),source_url:values.get('source_url'),published:values.has('published')};
      const files=item?[]:[...form.elements.files.files];
      if(files.some(f=>f.size>20*1024*1024)){feedback.textContent='有图片超过 20 MB，请缩小后重试';return;}
      working=true;d.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=true);
      try{
        if(item){await deps.api(`${endpoint}/items/${item.id}`,{method:'PUT',body});}
        else{
          for(let i=0;i<files.length;i++){
            if(succeeded.has(i))continue;
            const file=files[i],payload=new FormData();
            for(const [key,value] of Object.entries({...body,title:files.length===1&&body.title?body.title:file.name.replace(/\.[^.]+$/,'').slice(0,160)}))payload.append(key,String(value));
            payload.append('file',file);feedback.textContent=`正在上传 ${i+1}/${files.length}：${file.name}`;
            await deps.api(`${endpoint}/items`,{method:'POST',body:payload});succeeded.add(i);
          }
        }
        d.close();await refresh();deps.toast(item?'修改已保存':`已上传 ${files.length} 张图片`);
      }catch(error){feedback.textContent=`${error.message}。${succeeded.size?`已成功 ${succeeded.size} 张，重试会跳过成功项。`:''}`;}
      finally{working=false;d.querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=false);}
    };
  }
  function categories(){
    const d=modal('分类管理','<form class="admin-category-add"><input name="name" maxlength="40" required placeholder="新分类名称" aria-label="新分类名称"><button class="primary">新增分类</button></form><p class="admin-feedback" role="status"></p><div class="admin-category-list"></div>');
    const feedback=d.querySelector('.admin-feedback');
    const execute=action=>async event=>{event?.preventDefault();try{await action();data=await deps.api(endpoint);render();draw();feedback.textContent='已保存';}catch(error){feedback.textContent=error.message;}};
    function draw(){
      const list=d.querySelector('.admin-category-list');
      list.innerHTML=data.categories.map((c,i)=>`<form data-category-index="${i}"><input name="name" aria-label="分类名称 ${esc(c.name)}" maxlength="40" value="${esc(c.name)}" required><span>${c.item_count} 张</span><button>重命名</button><button type="button" class="danger" data-delete ${c.item_count?'disabled title="分类中还有图片"':''}>删除空分类</button></form>`).join('');
      list.querySelectorAll('form').forEach(f=>{const c=data.categories[Number(f.dataset.categoryIndex)];f.onsubmit=execute(()=>deps.api(`${endpoint}/categories/${encodeURIComponent(c.name)}`,{method:'PUT',body:{name:f.elements.name.value}}));f.querySelector('[data-delete]').onclick=execute(()=>deps.api(`${endpoint}/categories/${encodeURIComponent(c.name)}`,{method:'DELETE'}));});
    }
    d.querySelector('.admin-category-add').onsubmit=execute(async event=>{const form=d.querySelector('.admin-category-add');await deps.api(`${endpoint}/categories`,{method:'POST',body:{name:form.elements.name.value}});form.reset();});
    draw();
  }
  render();
}
