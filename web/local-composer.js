const localComposer=document.querySelector('#composer'),localPrompt=document.querySelector('#prompt'),localSend=document.querySelector('#send'),localFiles=document.querySelector('#files'),localFileList=document.querySelector('#file-list'),localTaskStrip=document.querySelector('#task-strip');
const localShowTask=(message,error=false)=>{localTaskStrip.hidden=!message;localTaskStrip.textContent=message||'';localTaskStrip.className=`task-strip${error?' error':''}`;};
const localFileData=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve({name:file.name,mime:file.type||'application/octet-stream',data:String(reader.result).split(',',2)[1]||''});reader.onerror=()=>reject(reader.error);reader.readAsDataURL(file);});
function clearLocalFiles(){localFiles.value='';localFileList.hidden=true;localFileList.innerHTML='';}
localFiles.onchange=()=>{const files=[...localFiles.files];localFileList.hidden=!files.length;if(!files.length)return;localFileList.innerHTML=`<span>待发送：${files.map(file=>`${esc(file.name)}（${(file.size/1024/1024).toFixed(1)} MB）`).join('、')} · 可继续填写描述</span><button type="button">取消附件</button>`;localFileList.querySelector('button').onclick=clearLocalFiles;};
localPrompt.oninput=()=>{localPrompt.style.height='auto';localPrompt.style.height=Math.min(localPrompt.scrollHeight,180)+'px';};
localPrompt.onkeydown=event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();localComposer.requestSubmit(localSend);}};
async function responseJson(response){const type=response.headers.get('content-type')||'';if(!type.includes('application/json'))throw new Error(response.status===404?'本地输入接口尚未加载，请重启桥后刷新网页':'本地桥返回了无法识别的响应');return response.json();}
const localTrackedTasks=new Map();
let localRenderedThread=null;
function localTerminal(turn){
  const status=typeof turn.status==='object'?turn.status?.type:turn.status;
  const hasFinal=(turn.items||[]).some(i=>i.type==='agentMessage'&&['final_answer','final'].includes(i.phase));
  return {status,message:({completed:'任务已完成',failed:'任务执行失败',cancelled:'任务已取消',interrupted:hasFinal?'本轮已中断 · 已有回复，请确认结果是否完整':'本轮已中断，未生成最终答案'})[status]||'Codex 正在处理'};
}
function renderLocalTracked(){
  const record=localTrackedTasks.get(selected);
  if(!record){if(localRenderedThread!==selected)localShowTask('');localRenderedThread=selected;return;}
  localRenderedThread=selected;
  localShowTask(record.message,record.status==='failed');
  if(['interrupted','cancelled'].includes(record.status))localTaskStrip.className='task-strip '+(record.status==='interrupted'?'interrupted':'cancelled');
}
async function pollLocalTask(taskId){
  let threadId=selected,followingSteer=false,trackedTurn=null,createdSelected=false;
  const record={id:taskId,message:'已提交到本机桥',status:'running'};
  if(threadId)localTrackedTasks.set(threadId,record);
  for(let count=0;count<1800;count++){
    await new Promise(resolve=>setTimeout(resolve,1000));
    try{
      const response=await fetch(`/api/local-task/${encodeURIComponent(taskId)}`,{cache:'no-store'}),task=await responseJson(response);
      if(!response.ok)throw new Error(task.error||'任务状态读取失败');
      if(task.threadId&&task.threadId!==threadId){
        if(localTrackedTasks.get(threadId)===record)localTrackedTasks.delete(threadId);
        threadId=task.threadId;localTrackedTasks.set(threadId,record);
        if(!createdSelected){createdSelected=true;selected=threadId;await loadThreads(false);}
      }
      if(localTrackedTasks.get(threadId)!==record)return;
      record.message=task.message||task.status;record.status=task.status;
      if(task.steered){followingSteer=true;trackedTurn=task.turnId;}
      if(followingSteer||['completed','failed','interrupted','cancelled'].includes(task.status)){
        const snapshot=await(await fetch(`/api/thread/${encodeURIComponent(threadId)}`,{cache:'no-store'})).json();
        const turns=snapshot.thread?.turns||[];
        let turn=turns.find(t=>t.id===(trackedTurn||task.turnId));
        if(turn){
          const index=turns.indexOf(turn),raw=localTerminal(turn);
          if(index<turns.length-1){turn=turns[turns.length-1];followingSteer=true;trackedTurn=turn.id;}
          Object.assign(record,localTerminal(turn));
        }else if(followingSteer){record.status='running';record.message='Codex 仍在处理 · 已追加引导';}
      }
      if(localTrackedTasks.get(threadId)!==record)return;
      if(selected===threadId){renderLocalTracked();loadThread(threadId,true);}
      if(['completed','failed','interrupted','cancelled'].includes(record.status))return;
    }catch(error){
      if(localTrackedTasks.get(threadId)!==record)return;
      record.message='任务状态暂时无法读取，正在重试…';record.status='unknown';
      if(selected===threadId)renderLocalTracked();
    }
  }
}
setInterval(renderLocalTracked,1000);
localComposer.onsubmit=async event=>{event.preventDefault();const text=localPrompt.value.trim(),chosen=[...localFiles.files];if(!selected){localShowTask('请先选择一个对话',true);return;}if(!text&&!chosen.length)return;if(chosen.length>3||chosen.some(file=>file.size>10*1024*1024)||chosen.reduce((sum,file)=>sum+file.size,0)>15*1024*1024){localShowTask('附件限制：最多3个，单文件10 MB，单次总计15 MB',true);return;}localSend.disabled=true;try{const threadId=selected,settings=window.modelPicker.capture(threadId);const files=await Promise.all(chosen.map(localFileData)),response=await fetch('/api/local-tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({threadId,...settings,text:text||'请查看并处理我从本地网页上传的附件。',files})}),data=await responseJson(response);if(!response.ok)throw new Error(data.error||'发送失败');window.modelPicker.accepted(threadId,settings);localPrompt.value='';localPrompt.style.height='';clearLocalFiles();localShowTask('已提交到本机桥');pollLocalTask(data.taskId);}catch(error){localShowTask(error.message,true);}finally{localSend.disabled=false;localPrompt.focus();}};

const localNewButton=document.querySelector('#new-thread'),localNewDialog=document.querySelector('#new-thread-dialog'),localNewForm=document.querySelector('#new-thread-form'),localNewProject=document.querySelector('#new-thread-project'),localNewProjectName=document.querySelector('#new-project-name'),localNewTitle=document.querySelector('#new-thread-title'),localNewText=document.querySelector('#new-thread-text'),localExistingRow=document.querySelector('#existing-project-row'),localProjectRow=document.querySelector('#new-project-row'),localNewLocation=document.querySelector('#new-thread-location');
let localBridgeConfig={projectsRoot:'',standaloneDir:''};
const localThreadKind=()=>new FormData(localNewForm).get('thread-kind')||'existing';
function refreshLocalNewForm(){const kind=localThreadKind();localExistingRow.hidden=kind!=='existing';localNewProject.disabled=kind!=='existing';localProjectRow.hidden=kind!=='project';const cwd=kind==='standalone'?localBridgeConfig.standaloneDir:kind==='project'?`${localBridgeConfig.projectsRoot.replace(/[\\/]+$/,'')}\\${localNewProjectName.value.trim()||'项目名称'}`:localNewProject.value;localNewLocation.textContent=`本机目录：${cwd||'请先选择项目'}`;}
window.openLocalNewThread=async function(kind='existing',cwd=null){try{localBridgeConfig=await(await fetch('/api/auth/config',{cache:'no-store'})).json();}catch{}const projects=[...new Set(threads.map(item=>item.cwd).filter(Boolean))];localNewProject.innerHTML=projects.map(path=>`<option value="${esc(path)}">${esc(projectName(path))} — ${esc(path)}</option>`).join('');const preferred=cwd||threads.find(item=>item.id===selected)?.cwd||projects[0]||'';if(preferred)localNewProject.value=preferred;localNewForm.querySelector(`input[name="thread-kind"][value="${kind}"]`).checked=true;localNewTitle.value='';localNewText.value='';localNewProjectName.value='';refreshLocalNewForm();localNewDialog.showModal();setTimeout(()=>localNewTitle.focus(),50);};
localNewForm.querySelectorAll('input[name="thread-kind"]').forEach(input=>input.onchange=refreshLocalNewForm);localNewProject.onchange=refreshLocalNewForm;localNewProjectName.oninput=refreshLocalNewForm;
document.querySelector('#close-new-thread').onclick=()=>localNewDialog.close();document.querySelector('#cancel-new-thread').onclick=()=>localNewDialog.close();localNewButton.onclick=()=>window.openLocalNewThread('existing');
localNewForm.onsubmit=async event=>{event.preventDefault();const kind=localThreadKind(),project=localNewProjectName.value.trim();if(kind==='project'&&(!project||/[<>:"/\\|?*]/.test(project))){localShowTask('项目名称不能为空，也不能包含路径特殊字符',true);return;}const cwd=kind==='standalone'?localBridgeConfig.standaloneDir:kind==='project'?`${localBridgeConfig.projectsRoot.replace(/[\\/]+$/,'')}\\${project}`:localNewProject.value,title=localNewTitle.value.trim(),text=localNewText.value.trim();if(!cwd||!title||!text)return;try{const settings=window.modelPicker.capture(null,true);const response=await fetch('/api/local-tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'new_thread',cwd,title,text,...settings})}),data=await responseJson(response);if(!response.ok)throw new Error(data.error||'创建失败');window.modelPicker.accepted(null,settings);localNewDialog.close();els.title.textContent=title;els.meta.textContent=`正在创建 · 项目：${projectName(cwd)}`;els.messages.innerHTML='<div class="loading">正在创建新对话并发送第一条消息…</div>';localShowTask('正在创建新对话');pollLocalTask(data.taskId);}catch(error){localShowTask(error.message,true);}};
