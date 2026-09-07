/* Shared model/effort picker. Runtime settings never belong in source control. */
(() => {
  const composer=document.querySelector('#composer'),newForm=document.querySelector('#new-thread-form');
  const row=document.createElement('section');
  row.className='model-bar';
  row.innerHTML='<label>下次模型 <select id="bridge-model" aria-label="下次模型"></select></label><label>强度 <select id="bridge-effort" aria-label="推理强度"></select></label><button type="button" id="model-follow">跟随客户端默认</button><span id="model-running" role="status"></span>';
  composer.before(row);
  const newRow=document.createElement('label');
  newRow.textContent='模型与推理强度';
  const newModel=document.createElement('select'),newEffort=document.createElement('select');
  newModel.id='new-thread-model';newEffort.id='new-thread-effort';
  newRow.append(newModel,newEffort);newForm.querySelector('footer').before(newRow);
  const model=row.querySelector('#bridge-model'),effort=row.querySelector('#bridge-effort'),status=row.querySelector('span'),follow=row.querySelector('button');
  const names={none:'不推理',minimal:'最低',low:'轻度',medium:'中',high:'高',xhigh:'极高',max:'最大',ultra:'Ultra（自动委派）'};
  let models=[],choices={},defaults={},current=null,currentId=null,pending=0,loading=false,error='',newManual=false;
  const ended=new Set(['completed','failed','interrupted','cancelled']);
  const entry=id=>models.find(m=>m.model===id);
  const defaultEffort=id=>id===defaults.model?defaults.effort||entry(id)?.defaultReasoningEffort:entry(id)?.defaultReasoningEffort;
  const label=turn=>{
    const record=turn?.bridgeModel,m=turn?.model||record?.actual||record?.requested;
    return m?m+' · '+(names[record?.effort]||record?.effort||'强度未记录')+(record?.requested&&!record.actual?'（请求设置）':''):'模型未记录';
  };
  function merge(incoming){for(const [id,value] of Object.entries(incoming||{})){if(value&&value.updated>(choices[id]?.updated||0))choices[id]=value;}}
  function fill(target,items,value){
    const sig=JSON.stringify(items);
    if(target.dataset.catalog!==sig){target.replaceChildren(...items.map(([id,name])=>new Option(name,id)));target.dataset.catalog=sig;}
    target.value=value||'';
  }
  function fillPair(m,e,mv,ev){
    fill(m,models.map(x=>[x.model,x.displayName||x.model]),mv);
    fill(e,(entry(mv)?.supportedReasoningEfforts||[]).map(x=>[x.reasoningEffort,names[x.reasoningEffort]||x.reasoningEffort]),ev);
  }
  function paint(){
    const choice=choices[currentId],manual=Boolean(choice?.model),mv=manual?choice.model:defaults.model;
    fillPair(model,effort,mv,manual?choice.effort||defaultEffort(mv):defaultEffort(mv));
    const nm=newManual?newModel.value:defaults.model,ne=newManual?newEffort.value:defaultEffort(nm);
    fillPair(newModel,newEffort,nm,ne);
    model.disabled=effort.disabled=!models.length||!current||pending>0;
    follow.disabled=!current||pending>0||!manual;
    newModel.disabled=newEffort.disabled=!models.length;
    const active=[...(current?.turns||[])].reverse().find(t=>{const s=typeof t.status==='object'?t.status?.type:t.status;return s&&!ended.has(s);});
    const mode=manual?'本会话已记住':'跟随客户端默认';
    status.textContent=error||(pending?'正在保存…':active?'本轮：'+label(active)+' · 追加不切换；新设置下一轮生效':!defaults.model?'等待本机 Codex 默认配置':!currentId?'选择对话后可设置模型与强度':mode+' · '+(effort.value==='ultra'?'Ultra 可自动委派任务，消耗波动较大':'新一轮生效'));
    row.classList.toggle('model-error',Boolean(error));
  }
  async function refresh(){
    if(loading)return;loading=true;
    try{
      const response=await fetch('/api/models',{cache:'no-store'});
      if(!response.ok)throw Error('模型设置暂不可用，请确认桥已升级并重启');
      const data=await response.json();models=data.models||[];defaults=data.defaults||{};merge(data.choices);
      if(!pending)error='';
    }catch(e){error=e.message;}finally{loading=false;paint();}
  }
  async function save(m,e){
    const id=currentId,previous=choices[id];pending++;error='';
    choices[id]={model:m,effort:e,updated:Date.now()/1000};paint();
    try{
      const response=await fetch('/api/model-choice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({threadId:id,model:m,effort:e})});
      const data=await response.json();if(!response.ok)throw Error(data.message||data.error||'设置保存失败');
      if(data.choices?.[id])choices[id]=data.choices[id];merge(data.choices);
    }catch(e){choices[id]=previous;error=e.message;}finally{pending--;paint();}
  }
  model.onchange=()=>save(model.value,defaultEffort(model.value));
  effort.onchange=()=>save(model.value,effort.value);
  follow.onclick=()=>save(null,null);
  newModel.onchange=()=>{newManual=true;fillPair(newModel,newEffort,newModel.value,defaultEffort(newModel.value));};
  newEffort.onchange=()=>{newManual=true;};
  window.modelPicker={
    begin(id){if(currentId!==id){currentId=id;current=null;error='';paint();}},
    thread(thread){if(thread.id!==currentId)return;current=thread;if(thread.bridgeModelChoice)merge({[thread.id]:thread.bridgeModelChoice});paint();},
    capture(id,isNew=false){
      if(pending)throw Error('设置仍在保存，请稍后发送');
      if(!isNew&&(id!==currentId||!current))throw Error('正在读取此对话，请稍后发送');
      const m=isNew?newModel.value:model.value,e=isNew?newEffort.value:effort.value;
      if(!entry(m)||(entry(m).supportedReasoningEfforts||[]).every(x=>x.reasoningEffort!==e))throw Error('请等待模型与强度加载，或重新选择');
      return {model:m,effort:e,followDefaults:isNew?!newManual:!choices[id]?.model};
    },
    label,refresh
  };
  paint();refresh();setInterval(refresh,10000);
})();
