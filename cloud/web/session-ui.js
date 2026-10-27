/* Device class is a user choice, never an authentication signal from the UA. */
(() => {
  let current = null, choicePromise = null, entry;
  const local = ['localhost','127.0.0.1','[::1]'].includes(location.hostname);
  async function api(path, data) {
    const response = await fetch(path, data === undefined ? {cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)
    });
    const value = await response.json();
    if (!response.ok) { if(response.status===401) signedOut(); throw new Error(response.status === 401 ? '登录已失效，请重新登录' : (value.error || '操作失败')); }
    return value;
  }
  function box(title) {
    const dialog=document.createElement('dialog');dialog.className='session-dialog';
    dialog.innerHTML='<header><strong></strong><button type="button" aria-label="关闭">×</button></header><div class="session-body"></div><p class="session-message" role="status"></p>';
    dialog.querySelector('strong').textContent=title;
    dialog.querySelector('header button').onclick=()=>{dialog.close();dialog.remove();};
    document.body.append(dialog);return dialog;
  }
  function signedOut() { location.replace('/signed-out.html'); }
  async function logout() { await api('/api/auth/session/logout',{}); signedOut(); }
  async function ensureChoice(config) {
    if (local || !config?.authRequired) return;
    current=config.session;
    mount();
    if (!current?.deviceChoiceRequired) return;
    if (choicePromise) return choicePromise;
    choicePromise=new Promise(resolve=>{
      const dialog=box('选择这次登录的设备属性'),body=dialog.querySelector('.session-body'),message=dialog.querySelector('.session-message');
      dialog.querySelector('header button').hidden=true;
      dialog.addEventListener('cancel',event=>event.preventDefault());
      body.innerHTML='<p>借用设备请保持“临时设备”。设备类型不会影响身份验证。</p><label class="session-choice"><input type="radio" name="device-mode" value="temporary" checked> 临时设备 · 固定 1 小时</label><label class="session-choice"><input type="radio" name="device-mode" value="personal"> 我的个人设备 · 固定 7 天</label><label>设备名称（可选）<input name="device-name" maxlength="60" autocomplete="off" placeholder="例如：我的手机"></label><p class="session-help">有效期从本次登录算起，不自动续期。可从另一台设备撤销此登录。</p><footer><button type="button" data-logout>退出登录</button><button type="button" class="primary" data-save>确认并进入</button></footer>';
      const save=body.querySelector('[data-save]'),exit=body.querySelector('[data-logout]');
      save.onclick=async()=>{
        save.disabled=exit.disabled=true;message.textContent='正在保存…';
        try{
          const result=await api('/api/auth/session/device',{mode:body.querySelector('[name=device-mode]:checked').value,name:body.querySelector('[name=device-name]').value});
          current=result.session;dialog.close();dialog.remove();resolve();
        }catch(e){message.textContent=e.message;save.disabled=exit.disabled=false;}
      };
      exit.onclick=async()=>{exit.disabled=true;try{await logout();}catch(e){message.textContent=e.message;exit.disabled=false;}};
      dialog.showModal();
    });
    return choicePromise;
  }
  function time(value) { return new Date(value*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}); }
  function mount() {
    if (local || entry) return;
    const details=document.querySelector('#quota-details')||document.querySelector('#balance-details');
    if(!details)return;
    entry=document.createElement('button');entry.type='button';entry.className='session-entry';entry.textContent='登录设备管理';
    entry.onclick=()=>{
      details.hidden=true;
      document.querySelector(details.id==='balance-details'?'#balance':'#quota')?.setAttribute('aria-expanded','false');
      manage();
    };
    // Account data and voice settings can replace/append panel content later.
    // Reuse the same button and keep it last after both success and failure renders.
    const keepLast=()=>{if(entry.parentNode!==details||details.lastElementChild!==entry)details.append(entry);};
    new MutationObserver(keepLast).observe(details,{childList:true});
    keepLast();
  }
  async function manage() {
    const dialog=box('登录设备管理'),body=dialog.querySelector('.session-body'),message=dialog.querySelector('.session-message');dialog.showModal();
    const load=async()=>{
      const result=await api('/api/auth/sessions');body.replaceChildren();
      const help=document.createElement('p');help.className='session-help';help.textContent='设备名称和类型仅供参考。撤销登录会阻止后续访问，不会取消已经提交的任务。';body.append(help);
      for(const item of result.sessions||[]){
        const row=document.createElement('section');row.className='session-row';
        const info=document.createElement('div'),name=document.createElement('strong'),detail=document.createElement('small');
        name.textContent=item.name+(item.current?'（当前）':'');
        detail.textContent=`${item.mode==='personal'?'个人设备':'临时设备'} · 最近访问 ${time(item.lastSeenAt)} · 到期 ${time(item.expiresAt)}`;
        info.append(name,detail);const button=document.createElement('button');button.type='button';button.textContent=item.current?'退出当前登录':'撤销登录';
        button.onclick=async()=>{button.disabled=true;try{const result=await api('/api/auth/sessions/revoke',{id:item.id});if(result.loggedOut)signedOut();else await load();}catch(e){message.textContent=e.message;button.disabled=false;}};
        row.append(info,button);body.append(row);
      }
      const footer=document.createElement('footer'),others=document.createElement('button');others.type='button';others.textContent='退出所有其他设备';
      others.onclick=async()=>{others.disabled=true;try{await api('/api/auth/sessions/revoke-others',{});message.textContent='其他登录已撤销';await load();}catch(e){message.textContent=e.message;others.disabled=false;}};
      footer.append(others);body.append(footer);
    };
    message.textContent='正在读取…';try{await load();message.textContent='';}catch(e){message.textContent=e.message;}
  }
  window.sessionUI={ensureChoice,mount};
})();
