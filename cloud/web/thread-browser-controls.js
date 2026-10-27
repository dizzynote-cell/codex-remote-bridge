/* Sidebar ordering is based on recorded activity, never polling/sync/view time. */
(() => {
  const script = document.currentScript;
  const deepseek = script?.dataset.provider === 'deepseek-harness';
  const key = 'bridge-thread-view:' + (deepseek ? 'deepseek' : 'codex');
  let mode = 'recent', toolbar, dialog;
  try { if (localStorage.getItem(key) === 'projects') mode = 'projects'; } catch {}
  function epoch(value) {
    if (value == null || value === '' || typeof value === 'boolean') return 0;
    const n = Number(value);
    if (Number.isFinite(n)) return n > 0 ? (n < 1e11 ? n * 1000 : n) : 0;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  function activity(t) {return epoch(t.bridgeUpdatedAt ?? t.updatedAt ?? t.updated_at ?? t.bridgeCreatedAt ?? t.createdAt);}
  function sort(items) {return [...items].sort((a,b) => Number(!!b.pinned)-Number(!!a.pinned) || activity(b)-activity(a) || String(a.id).localeCompare(String(b.id)));}
  function stamp(t) {
    const value = activity(t);
    if (!value) return '活动时间未知';
    return new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
  }
  function mount() {
    if (toolbar) return;
    toolbar = document.createElement('div'); toolbar.className = 'thread-list-controls';
    toolbar.innerHTML = '<label>排序 <select aria-label="对话列表视图"><option value="recent">置顶＋最近活跃</option><option value="projects">按项目查看</option></select></label>' + (deepseek ? '<button type="button" data-show-hidden>已隐藏对话</button>' : '');
    els.threads.before(toolbar);
    const select=toolbar.querySelector('select'); select.value=mode;
    select.onchange=()=>{mode=select.value;try{localStorage.setItem(key,mode);}catch{}renderThreads();};
    toolbar.querySelector('[data-show-hidden]')?.addEventListener('click',showHidden);
  }
  function row(t, showProject) {
    const running=t.bridgeRunning===true;
    return `<div class="thread-list-row"><button class="thread ${selected===t.id?'active':''}" data-id="${esc(t.id)}"><div class="thread-title">${t.pinned?'<span class="thread-pin">置顶</span> ':''}${esc(t.name||'未命名对话')}</div><div class="thread-meta">${running?'运行中 · ':''}${showProject?esc(projectName(window.projectDisplay.key(t)))+' · ':''}<span title="最近记录的活动时间">${esc(stamp(t))}</span></div></button><button type="button" class="thread-menu" ${deepseek?'data-library-actions':'data-thread-actions'}="${esc(t.id)}" aria-label="整理对话：${esc(t.name||'未命名对话')}" title="置顶、隐藏等操作">•••</button></div>`;
  }
  function render() {
    mount();
    const q=els.search.value.trim().toLowerCase();
    const filtered=sort(threads.filter(t=>`${t.name} ${projectName(window.projectDisplay.key(t))} ${t.cwd||''} ${t.id||''}`.toLowerCase().includes(q)));
    const pinned=filtered.filter(t=>t.pinned), normal=filtered.filter(t=>!t.pinned), groups=new Map();
    for(const t of normal){const k=window.projectDisplay.key(t);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(t);}
    const projectCount=new Set(filtered.map(t=>window.projectDisplay.key(t))).size;
    els.count.textContent=`${filtered.length} 个对话 · ${projectCount} 个项目`;
    let html=pinned.length?`<section class="project-group"><div class="thread-section-title">置顶</div>${pinned.map(t=>row(t,true)).join('')}</section>`:'';
    if(mode==='recent') html+=`<section class="project-group"><div class="thread-section-title">最近活跃 · 已载入对话</div>${normal.map(t=>row(t,true)).join('')}</section>`;
    else html+=window.projectDisplay.groups(groups,managedProjects).map(([cwd,items])=>`<section class="project-group"><button class="project-heading" data-project-cwd="${esc(window.projectDisplay.cwd(cwd,managedProjects))}" data-project-kind="${cwd==='desktop:projectless'?'standalone':'existing'}" title="在此项目中新建对话"><span>${esc(projectName(cwd))}</span><small>${items.length} ＋</small></button>${items.map(t=>row(t,false)).join('')}</section>`).join('');
    els.threads.innerHTML=html;
    els.threads.querySelectorAll('.thread').forEach(b=>b.onclick=()=>{document.body.classList.remove('sidebar-open');loadThread(b.dataset.id);});
    els.threads.querySelectorAll('.project-heading').forEach(b=>b.onclick=()=>{
      if(typeof openNewThread==='function')openNewThread(b.dataset.projectKind||'existing',b.dataset.projectCwd);
      else window.openLocalNewThread?.(b.dataset.projectKind||'existing',b.dataset.projectCwd);
    });
    if(deepseek)els.threads.querySelectorAll('[data-library-actions]').forEach(b=>b.onclick=()=>showActions(b.dataset.libraryActions));
    else window.threadOrganizer?.bind();
    els.loadMore.hidden=!nextCursor;
  }
  function modal(title) {
    if(dialog)dialog.remove();
    dialog=document.createElement('dialog');dialog.className='thread-library-dialog';
    dialog.innerHTML='<header><strong></strong><button type="button" aria-label="关闭">×</button></header><div class="thread-library-body"></div><p class="thread-library-note" role="status"></p>';
    dialog.querySelector('strong').textContent=title;
    dialog.querySelector('header button').onclick=()=>dialog.close();document.body.append(dialog);dialog.showModal();return dialog;
  }
  async function request(patch) {
    const response=await bridgeFetch('/api/thread-library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'保存失败');return data;
  }
  function showActions(id) {
    const item=threads.find(t=>t.id===id);if(!item)return;
    const box=modal(item.name||'整理对话'),body=box.querySelector('.thread-library-body'),note=box.querySelector('.thread-library-note');
    note.textContent='隐藏只影响桥的列表，历史和正在运行的任务会保留。可从“已隐藏对话”恢复。';
    for(const [label,patch] of [[item.pinned?'取消置顶':'置顶这个对话',{pinned:!item.pinned}],['从列表隐藏',{hidden:true}]]){
      const button=document.createElement('button');button.type='button';button.textContent=label;body.append(button);
      button.onclick=async()=>{
        const buttons=body.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
        try{await request({threadId:id,name:item.name,...patch});Object.assign(item,patch);if(patch.hidden)threads=threads.filter(t=>t.id!==id);box.close();renderThreads();}
        catch(e){note.textContent=e.message;}finally{buttons.forEach(b=>b.disabled=false);}
      };
    }
  }
  async function showHidden() {
    const box=modal('已隐藏对话'),body=box.querySelector('.thread-library-body'),note=box.querySelector('.thread-library-note');note.textContent='正在读取…';
    try{
      const response=await bridgeFetch('/api/thread-library',{cache:'no-store'}),data=await response.json();if(!response.ok)throw new Error(data.error||'读取失败');
      const entries=Object.entries(data.threads||{}).filter(([,v])=>v.hidden);note.textContent=entries.length?'恢复不会重发消息，也不会启动任务。':'暂无已隐藏对话';
      for(const [id,item] of entries){
        const row=document.createElement('div');row.className='thread-hidden-row';const name=document.createElement('span');name.textContent=item.name||'未命名对话';
        const button=document.createElement('button');button.type='button';button.textContent='恢复';row.append(name,button);body.append(row);
        button.onclick=async()=>{button.disabled=true;try{await request({threadId:id,hidden:false});row.remove();await loadThreads(false);if(!body.children.length)note.textContent='暂无已隐藏对话';}catch(e){note.textContent=e.message;button.disabled=false;}};
      }
    }catch(e){note.textContent=e.message;}
  }
  window.threadBrowser={render,sort,activity,epoch};
})();
