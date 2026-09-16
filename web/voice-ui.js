// Shared by loopback and hosted UIs. Never sends an API secret to the browser.
(()=>{
  const records=new Map(), snapshots=new Map(), jobs=new Map(), polling=new Set(), reconciling=new Set(), requests=new Set();
  let prefs={voiceEnabled:false}, config={voice:'',resource:'',configured:false}, thread='', audio=null,settingsRefreshing=false;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const hosted=location.hostname!=='127.0.0.1'&&location.hostname!=='localhost';
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const storeKey=id=>'codex-voice-status:'+id;
  const jobKey=item=>item.threadId+':'+item.key;
  const taskStoreKey=item=>'codex-voice-task:'+jobKey(item);
  const explain=message=>({voice_reply_not_finalized_or_history_stale:'云端历史尚未确认这条回复，请稍后刷新再试',voice_key_mismatch_refresh_page:'语音配置已变化，请刷新网页',voice_disabled:'语音开关已关闭',voice_not_configured:'本机语音尚未配置',invalid_voice_request:'语音请求无效',voice_provider_unavailable:'语音服务暂时不可用'})[message]||message||'语音请求失败';
  function job(item){
    const id=jobKey(item);
    if(jobs.has(id))return jobs.get(id);
    let saved;
    try{saved=JSON.parse(sessionStorage.getItem(taskStoreKey(item))||'null');}catch{}
    const value=saved&&saved.key===item.key&&saved.threadId===item.threadId&&
      Date.now()-saved.updatedAt<24*3600*1000?saved:{key:item.key,threadId:item.threadId,status:'idle',taskId:null,message:'',updatedAt:Date.now()};
    jobs.set(id,value);return value;
  }
  function update(item,status,message='',taskId=null){
    const value=job(item);
    Object.assign(value,{status,message,taskId:taskId||value.taskId,updatedAt:Date.now()});
    try{sessionStorage.setItem(taskStoreKey(item),JSON.stringify(value));}catch{}
    for(const [ref,record] of records)if(jobKey(record)===jobKey(item))paint(ref,status,message);
  }
  function snapshot(id){
    if(snapshots.has(id)){
      const value=snapshots.get(id);
      if(Date.now()-value.checkedAt<24*3600*1000)return value;
      snapshots.delete(id);
    }
    let saved;
    try{saved=JSON.parse(sessionStorage.getItem(storeKey(id))||'null');}catch{}
    const result=saved&&Date.now()-saved.checkedAt<24*3600*1000?saved:{checkedAt:0,cached:{}};
    snapshots.set(id,result);return result;
  }
  function save(id){
    const state=snapshot(id);
    try{sessionStorage.setItem(storeKey(id),JSON.stringify(state));}catch{}
  }
  async function json(url,options){
    const response=await fetch(url,{cache:'no-store',...options});
    const data=await response.json().catch(()=>({error:'服务返回格式错误，请稍后重试'}));
    if(!response.ok)throw new Error(explain(data.error||'服务暂时不可用'));
    return data;
  }
  async function digest(text){
    const payload=JSON.stringify([text,config.voice,config.resource,'v3-sse-mp3-rate25']);
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(payload));
    return [...new Uint8Array(bytes)].map(n=>n.toString(16).padStart(2,'0')).join('');
  }
  function record(turn,item,text,kind){
    if(!prefs.voiceEnabled||!config.configured||turn.status!=='completed'||!text.trim())return'';
    const ref=String(turn.id||'')+':'+String(item.id||kind);
    records.set(ref,{text:text.trim(),threadId:thread,kind,key:null});
    return `<button class="voice-button" type="button" data-voice-ref="${esc(ref)}" title="检查语音缓存" aria-label="朗读${kind==='final'?'最终回复':'推理摘要'}">🔊</button>`;
  }
  function clear(id){thread=id;records.clear();}
  function paint(ref,state,message=''){
    const button=[...document.querySelectorAll('.voice-button')].find(b=>b.dataset.voiceRef===ref);
    if(!button)return;
    const waiting=['requesting','queued','claimed','running','unknown'].includes(state);
    button.classList.toggle('cached',state==='cached');
    button.classList.toggle('busy',waiting);
    button.classList.toggle('voice-failed',state==='failed');
    button.disabled=waiting&&state!=='unknown';
    button.title=message|| (state==='cached'?'已有语音，点击播放':waiting?'正在等待语音任务':'未缓存，点击生成语音');
    button.textContent=state==='unknown'?'?':waiting?'◌':state==='cached'?'🔊':state==='failed'?'!':'🔈';
    const wrapper=button.closest('.voice-actions')||button.parentElement;
    if(wrapper){
      let notice=wrapper.querySelector('.voice-feedback');
      if(!notice){notice=document.createElement('span');notice.className='voice-feedback';notice.setAttribute('role','status');wrapper.append(notice);}
      notice.textContent=waiting?(message||'正在等待语音任务…'):state==='failed'?message:'';
      notice.hidden=!notice.textContent;
    }
  }
  async function refreshStatus(id,refs,force=false){
    if(!refs.length)return;
    const state=snapshot(id);
    const keys=[...new Set(refs.map(ref=>records.get(ref)?.key).filter(Boolean))]
      .filter(key=>force||!(key in state.cached));
    if(keys.length){
      try{
        const data=await json('/api/voice/status?keys='+encodeURIComponent(keys.join(',')));
        if(thread!==id)return;
        Object.assign(state.cached,data.cached||{});state.checkedAt=Date.now();save(id);
      }catch{return;}
    }
    for(const ref of refs){
      const item=records.get(ref);
      if(item?.key){const current=job(item);paint(ref,
        ['requesting','queued','claimed','running','unknown','failed'].includes(current.status)?current.status:
          state.cached[item.key]?'cached':'uncached',current.message);}
    }
  }
  async function bind(id){
    thread=id;
    const refs=[...records.keys()];
    await Promise.all(refs.map(async ref=>{
      const item=records.get(ref);
      if(item&&!item.key)item.key=await digest(item.text);
      const button=[...document.querySelectorAll('.voice-button')].find(b=>b.dataset.voiceRef===ref);
      if(button)button.onclick=()=>click(ref);
    }));
    if(thread===id){
      await refreshStatus(id,refs);
      for(const ref of refs){const item=records.get(ref);if(!item?.key)continue;
        const current=job(item);
        if(hosted&&['queued','claimed','running','unknown','requesting'].includes(current.status)){
          if(current.taskId)monitor(item,ref);else if(!requests.has(jobKey(item)))reconcile(item,ref);
        }
      }
    }
  }
  async function lookup(item){return json('/api/voice/lookup/'+encodeURIComponent(item.key));}
  async function reconcile(item,ref){
    const id=jobKey(item);if(reconciling.has(id))return;
    reconciling.add(id);
    try{
      const result=await lookup(item);
      if(result.cached){complete(item,ref);return;}
      if(result.taskId&&['queued','claimed','running'].includes(result.status)){
        update(item,result.status,'正在继续等待原语音任务…',result.taskId);monitor(item,ref);return;
      }
      if(['failed','expired','cancelled'].includes(result.status)){
        update(item,'failed',explain(result.error||'原任务已失败，请点击重试'),result.taskId);return;
      }
      update(item,'failed','云端没有确认收到语音请求；没有自动重发，点击可手动重试');
    }catch{update(item,'unknown','暂时无法查到原任务，点击问号可再检查；不会自动重发');}
    finally{reconciling.delete(id);}
  }
  function complete(item,ref,playNow=false){
    const state=snapshot(item.threadId);state.cached[item.key]=true;save(item.threadId);
    update(item,'cached','');if(playNow&&thread===item.threadId)play(ref,item.key);
  }
  async function monitor(item,ref,playNow=false){
    const id=jobKey(item);if(polling.has(id))return;
    polling.add(id);
    try{
      for(let attempt=0;attempt<150;attempt++){
        const current=job(item);if(!current.taskId)return;
        try{
          const result=await json('/api/voice/task/'+encodeURIComponent(current.taskId));
          if(result.status==='completed'){
            if(result.key!==item.key)throw new Error('语音任务与回复不匹配，请刷新网页');
            complete(item,ref,playNow);return;
          }
          if(['failed','expired','cancelled'].includes(result.status)){
            update(item,'failed',explain(result.error||'语音任务失败，请点击重试'));return;
          }
          update(item,result.status,'正在'+(result.status==='queued'?'等待本机接收':'合成或上传')+'语音…');
        }catch(error){update(item,'unknown','暂时未收到任务状态，仍在查询原任务…');}
        await sleep(2000);
      }
      update(item,'unknown','任务仍未确认结果；不会自动重新合成，请稍后再查看');
    }finally{polling.delete(id);}
  }
  async function waitReset(taskId){
    for(let attempt=0;attempt<40;attempt++){
      const result=await json('/api/reset-credit/task/'+encodeURIComponent(taskId));
      if(result.status==='completed')return result.outcome;
      if(['failed','expired'].includes(result.status))throw new Error(result.error||'使用失败');
      await sleep(1000);
    }
    throw new Error('等待重置卡结果超时');
  }
  function play(ref,key){
    if(audio){audio.pause();audio=null;}
    const item=records.get(ref);
    const button=[...document.querySelectorAll('.voice-button')].find(b=>b.dataset.voiceRef===ref);
    if(!button||!item)return;
    const player=document.createElement('audio');
    player.src='/api/voice/audio/'+encodeURIComponent(key);
    player.preload='auto';player.controls=true;player.className='voice-player';
    button.after(player);audio=player;
    player.onerror=()=>{
      const state=snapshot(item.threadId);state.cached[key]=false;save(item.threadId);
      update(item,'failed','语音文件无法播放或缓存已过期；请检查登录，再点击重试');player.remove();audio=null;
    };
    player.onended=()=>{player.remove();audio=null;};
    player.play().catch(()=>{paint(ref,'cached','浏览器阻止自动播放，请点旁边的播放器播放键');});
  }
  async function click(ref){
    const item=records.get(ref);
    if(!item||!item.key)return;
    const state=snapshot(item.threadId);
    const current=job(item);
    if(state.cached[item.key]){play(ref,item.key);return;}
    if(['requesting','queued','claimed','running'].includes(current.status))return;
    if(current.status==='unknown'){await reconcile(item,ref);return;}
    if(current.status==='failed'&&current.taskId&&hosted&&!confirm('原语音任务失败，重新合成可能再次消耗 TTS 额度。确定重试吗？'))return;
    requests.add(jobKey(item));
    update(item,'requesting','正在确认云端已收到语音请求…');
    try{
      if(hosted){
        const status=await json('/api/status');
        if(!status.online)throw new Error('本机离线，暂不能生成语音');
      }
      const response=await json('/api/voice/request',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({threadId:item.threadId,text:item.text,key:item.key})});
      if(response.cached||!hosted){
        if(response.key!==item.key)throw new Error('语音配置已变化，请刷新页面');
        complete(item,ref,true);return;
      }
      if(!response.taskId)throw new Error('云端未确认任务编号，请稍后检查状态');
      update(item,'queued','云端已收到语音任务，正在等待本机…',response.taskId);
      monitor(item,ref,true);
    }catch(error){
      if(hosted&&error instanceof TypeError){
        update(item,'unknown','网络中断，先检查原请求是否已入队，不会自动重复合成');
        await reconcile(item,ref);
      }else update(item,'failed',explain(error.message||'语音请求失败，请重试'));
    }finally{requests.delete(jobKey(item));
    }
  }
  async function resetCredit(){
    if(!confirm('确定使用一张 Codex 重置卡吗？使用后无法撤销。'))return;
    const button=document.querySelector('#use-reset-credit');
    if(button)button.disabled=true;
    try{
      const key=crypto.randomUUID();
      const result=await json('/api/reset-credit',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({confirmed:true,idempotencyKey:key})});
      const outcome=hosted?(await waitReset(result.taskId)):result.outcome;
      alert(outcome==='reset'||outcome==='alreadyRedeemed'?'已使用重置卡。':'没有可重置的额度窗口：'+outcome);
      await settings();
    }catch(error){alert('重置卡请求失败：'+error.message);}
    finally{if(button)button.disabled=false;}
  }
  async function settings(){
    if(settingsRefreshing)return;
    settingsRefreshing=true;
    try{prefs=await json('/api/preferences');config=await json('/api/voice/config');}
    catch{settingsRefreshing=false;return;}
    const quota=await json('/api/quota').catch(()=>({}));
    const details=document.querySelector('#quota-details');
    if(!details){settingsRefreshing=false;return;}
    details.querySelector('#voice-settings')?.remove();
    const panel=document.createElement('div');panel.id='voice-settings';
    const count=quota.resetCredits;
    panel.innerHTML=`<hr><strong>网页设置</strong>
      <label class="voice-setting"><input id="show-voice" type="checkbox" ${prefs.voiceEnabled?'checked':''}>
      显示语音朗读按钮</label>
      <small>${config.configured?'TTS 已配置':'未配置 TTS，启用前请在本机安装引导中填写密钥'}</small>
      <small>默认加载轮数：6（查看更早或全部不受限制）</small>
      <hr><strong>Codex 重置卡</strong>
      <span>可用：${count===null||count===undefined?'暂不可用':esc(count)+' 张'}</span>
      <button id="use-reset-credit" type="button" ${!Number.isInteger(count)||count<1?'disabled':''}>使用一张</button>`;
    details.append(panel);
    panel.querySelector('#show-voice').onchange=async event=>{
      const enabled=event.target.checked;
      try{
        prefs=await json('/api/preferences',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({voiceEnabled:enabled})});
        location.reload();
      }catch(error){event.target.checked=!enabled;alert('设置保存失败：'+error.message);}
    };
    panel.querySelector('#use-reset-credit').onclick=resetCredit;
    settingsRefreshing=false;
  }
  function boot(){
    const details=document.querySelector('#quota-details');
    if(details)new MutationObserver(()=>{if(!settingsRefreshing&&!details.querySelector('#voice-settings'))settings();})
      .observe(details,{childList:true});
    settings();
  }
  window.voiceUI={record,clear,bind,boot,settings};
})();
