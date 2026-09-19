+// SPDX-License-Identifier: MIT
// Copyright (c) 2026 xiyannan
(() => {
  'use strict';
  const dialog=document.querySelector('#organize-thread-dialog'),form=document.querySelector('#organize-thread-form');
  if(!dialog||!form)return;
  const nameInput=document.querySelector('#organize-thread-name'),pinInput=document.querySelector('#organize-thread-pin'),projectSelect=document.querySelector('#organize-thread-project');
  let current=null;
  const api={
    project(thread){return thread.projectOverride||thread.cwd||'';},
    sort(items){return [...items].sort((a,b)=>Number(Boolean(b.pinned))-Number(Boolean(a.pinned)));},
    bind(){document.querySelectorAll('[data-thread-actions]').forEach(button=>button.onclick=event=>{event.stopPropagation();api.open(button.dataset.threadActions);});},
    open(id){
      current=threads.find(item=>item.id===id);if(!current)return;
      nameInput.value=current.name||'';pinInput.checked=Boolean(current.pinned);
      const projects=managedProjects||[];
      projectSelect.innerHTML='<option value="">自动按实际项目归类</option>'+projects.map(item=>`<option value="${esc(item.cwd)}">${esc(item.name||projectName(item.cwd))}</option>`).join('');
      projectSelect.value=current.projectOverride||'';dialog.showModal();nameInput.focus();nameInput.select();
    }
  };
  form.onsubmit=async event=>{
    event.preventDefault();if(!current)return;
    const name=nameInput.value.trim(),payload={threadId:current.id,pinned:pinInput.checked,project:projectSelect.value};
    if(!name){nameInput.setCustomValidity('请输入对话名称');nameInput.reportValidity();return;}
    nameInput.setCustomValidity('');if(name!==current.name)payload.name=name;
    const submit=form.querySelector('[type=submit]');submit.disabled=true;
    try{
      const response=await fetch('/api/thread-organizer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),data=await response.json();
      if(!response.ok)throw new Error(data.error||'保存失败');
      Object.assign(current,{name,pinned:pinInput.checked,projectOverride:projectSelect.value||null});dialog.close();renderThreads();
      if(selected===current.id){els.title.textContent=name;els.meta.textContent=els.meta.textContent.replace(/^项目：[^·]+/,`项目：${projectName(api.project(current))}`);}
      showTask(data.taskId?'整理已保存，重命名正发送到主力 PC':'对话整理已保存');setTimeout(()=>showTask(''),3000);
    }catch(error){showTask(error.message||'保存失败',true);}finally{submit.disabled=false;}
  };
  document.querySelector('#cancel-organize-thread').onclick=()=>dialog.close();
  document.querySelector('#close-organize-thread').onclick=()=>dialog.close();
  window.threadOrganizer=api;
})();

