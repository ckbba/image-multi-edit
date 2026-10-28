const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindLabel={welcome:'注册赠送',generation:'图片生成',admin_adjustment:'管理员调整'};
let cleanupAccountControls=()=>{};
let accountMountVersion=0;

export async function mountAccountControls({api,user,navigate,onLogout}){
  const header=document.querySelector('.header-right');
  if(!header||!user)return;
  const mountVersion=++accountMountVersion;
  cleanupAccountControls();
  const sheetController=new AbortController();
  const credits=await api('/account/credits?limit=30');
  if(mountVersion!==accountMountVersion||!header.isConnected)return;
  const trigger=document.createElement('button');
  trigger.id='account-trigger';trigger.className='account-trigger';trigger.type='button';
  trigger.setAttribute('aria-label','打开账户中心');trigger.setAttribute('aria-expanded','false');
  trigger.innerHTML=`<span class="credit-chip" title="可用积分">✦ ${credits.available}</span><span class="account-avatar">${esc(user.email.slice(0,1).toUpperCase())}</span>`;
  header.append(trigger);
  const backdrop=document.createElement('div');backdrop.className='account-sheet-backdrop';backdrop.hidden=true;
  const sheet=document.createElement('aside');sheet.className='account-sheet';sheet.hidden=true;sheet.setAttribute('aria-label','账户中心');
  sheet.innerHTML=`<div class="account-sheet-handle"></div><header><div class="account-avatar large">${esc(user.email.slice(0,1).toUpperCase())}</div><div><strong>${esc(user.email)}</strong><small>${user.role==='admin'?'管理员账户':'个人账户'}</small></div><button type="button" class="account-sheet-close" aria-label="关闭账户中心">×</button></header>
    <section class="account-credit-card"><div><small>可用积分</small><b>${credits.available}</b><span>成功生成一张图片消耗 1 积分</span></div>${credits.reserved?`<em>${credits.reserved} 分生成中</em>`:''}</section>
    <nav class="account-sheet-nav"><button type="button" data-account-view="ledger"><span>积分明细</span><small>查看每次获取与消耗</small><b>›</b></button><button type="button" data-guide><span>使用指南</span><small>重新查看操作引导</small><b>›</b></button>${user.role==='admin'?'<a href="/admin/inspiration" data-nav><span>灵感管理</span><small>素材、分类与发布</small><b>›</b></a><a href="/admin/credits" data-nav><span>用户积分管理</span><small>查看明细并调整积分</small><b>›</b></a>':''}</nav>
    <section class="account-ledger" hidden><div class="account-section-title"><button type="button" data-account-back>‹</button><div><h2>积分明细</h2><p>余额变化清晰可查</p></div></div><div class="ledger-table">${credits.items.length?credits.items.map(item=>`<article><span class="ledger-icon ${item.amount>0?'gain':'spend'}">${item.amount>0?'＋':'−'}</span><div><strong>${esc(item.title||kindLabel[item.kind]||'积分变动')}</strong><small>${new Date(item.created*1000).toLocaleString('zh-CN')}${item.operator_email?` · ${esc(item.operator_email)}`:''}</small>${item.note&&!item.title?`<p>${esc(item.note)}</p>`:''}</div><b class="${item.amount>0?'gain':'spend'}">${item.amount>0?'+':''}${item.amount}</b><em>余额 ${item.balance_after}</em></article>`).join(''):'<p class="ledger-empty">还没有积分明细</p>'}</div></section>
    <button class="account-logout" type="button">退出登录</button>`;
  document.body.append(backdrop,sheet);
  cleanupAccountControls=()=>{sheetController.abort();backdrop.remove();sheet.remove();document.body.classList.remove('account-sheet-open');};
  const open=()=>{backdrop.hidden=sheet.hidden=false;requestAnimationFrame(()=>{backdrop.classList.add('open');sheet.classList.add('open');});trigger.setAttribute('aria-expanded','true');document.body.classList.add('account-sheet-open');};
  const close=()=>{backdrop.classList.remove('open');sheet.classList.remove('open');trigger.setAttribute('aria-expanded','false');document.body.classList.remove('account-sheet-open');setTimeout(()=>{if(!sheet.classList.contains('open'))backdrop.hidden=sheet.hidden=true;},220);};
  trigger.onclick=open;backdrop.onclick=close;sheet.querySelector('.account-sheet-close').onclick=close;
  sheet.querySelector('[data-account-view]').onclick=()=>{sheet.classList.add('show-ledger');sheet.querySelector('.account-ledger').hidden=false;};
  sheet.querySelector('[data-account-back]').onclick=()=>{sheet.classList.remove('show-ledger');sheet.querySelector('.account-ledger').hidden=true;};
  sheet.querySelectorAll('[data-nav]').forEach(link=>link.onclick=event=>{event.preventDefault();close();navigate(link.getAttribute('href'));});
  sheet.querySelector('[data-guide]').onclick=async()=>{close();if(!document.querySelector('#product-tour-start'))await navigate('/');setTimeout(()=>document.querySelector('#product-tour-start')?.click(),250);};
  sheet.querySelector('.account-logout').onclick=async()=>{await api('/logout',{method:'POST'});close();cleanupAccountControls();onLogout();};
  const escape=event=>{if(event.key==='Escape'&&!sheet.hidden)close();};document.addEventListener('keydown',escape,{signal:sheetController.signal});
}
