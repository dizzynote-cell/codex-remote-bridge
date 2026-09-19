// SPDX-License-Identifier: MIT
// Copyright (c) 2026 xiyannan
/* Shared reversible visibility controls for both webpages. */
(() => {
  const organizer=document.querySelector('#organize-thread-dialog');
  if(!organizer||!window.threadOrganizer)return;
  let currentId=null;
  const originalOpen=window.threadOrganizer.open;
  window.threadOrganizer.open=id=>{currentId=id;originalOpen(id);};
  const section=document.createElement('div');
  section.className='visibility-danger-zone';
  const hide=document.createElement('button');
  hide.type='button';hide.className='visibility-hide-button';hide.textContent='从网页列表隐藏';section.append(hide);
  organizer.querySelector('form').append(section);
  const entry=document.createElement('button');
  entry.type='button';entry.className='hidden-threads-entry';entry.textContent='已隐藏对话';entry.title='查看和恢复已隐藏的对话';
  els.threads.before(entry);
  const dialog=document.createElement('dialog');
  dialog.className='organize-thread-dialog hidden-threads-dialog';
  dialog.innerHTML='<div class="hidden-dialog-body"><header><strong>已隐藏对话</strong><button type="button" data-close aria-label="关闭">×</button></header><p class="hidden-dialog-help">恢复后会重新显示在网页列表，Codex 对话和历史始终保留。</p><div class="hidden-thread-list" data-hidden-list></div></div>';
  document.body.append(dialog);
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  const notice=document.createElement('div');
  notice.className='visibility-toast';
  notice.hidden=true;document.body.append(notice);
  function message(text,undo){
    notice.replaceChildren(document.createTextNode(text+' '));notice.hidden=false;
    if(undo){const button=document.createElement('button');button.className='visibility-toast-action';button.textContent='撤销';button.onclick=async()=>{button.disabled=true;try{await undo();notice.hidden=true;}catch(error){message(error.message);}finally{button.disabled=false;}};notice.append(button);}
    const close=document.createElement('button');close.className='visibility-toast-close';close.textContent='×';close.setAttribute('aria-label','关闭');close.onclick=()=>notice.hidden=true;notice.append(close);
  }
  async function change(id,hidden,name){
    const response=await fetch('/api/threads/'+(hidden?'hide':'unhide'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({threadId:id,name})});
    if(!response.ok)throw new Error('操作失败，请检查服务是否已更新后重试');
    if(hidden){threads=threads.filter(item=>item.id!==id);renderThreads();}
    else await loadThreads(false);
  }
  hide.onclick=async()=>{
    const id=currentId,item=threads.find(t=>t.id===id);
    if(!item||!confirm('隐藏“'+item.name+'”？\n只从本地和公网网页列表隐藏，不删除 Codex 对话或历史，可随时恢复。'))return;
    hide.disabled=true;
    try{
      await change(id,true,item.name);organizer.close();
      message('已隐藏，可在“已隐藏对话”中恢复。',()=>change(id,false,item.name));
    }catch(error){message(error.message);}finally{hide.disabled=false;}
  };
  async function refreshHidden(){
    const list=dialog.querySelector('[data-hidden-list]');list.textContent='正在加载…';
    try{
      const response=await fetch('/api/threads/hidden',{cache:'no-store'});
      if(!response.ok)throw new Error('读取失败，请检查服务是否已更新');
      const data=await response.json();list.replaceChildren();
      for(const item of data.threads||[]){
        const row=document.createElement('div');row.className='hidden-thread-row';
        const name=document.createElement('span');name.textContent=item.name||'未命名对话';
        const restore=document.createElement('button');restore.className='hidden-thread-restore';restore.textContent='恢复';
        restore.onclick=async()=>{restore.disabled=true;try{await change(item.id,false,item.name);await refreshHidden();}catch(error){message(error.message);restore.disabled=false;}};
        row.append(name,restore);list.append(row);
      }
      if(!list.children.length)list.textContent='没有已隐藏的对话';
    }catch(error){list.textContent=error.message;}
  }
  entry.onclick=()=>{dialog.showModal();refreshHidden();};
})();
