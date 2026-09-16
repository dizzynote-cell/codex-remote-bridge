// Shared by loopback and hosted UIs. Never sends an API secret to the browser.
(()=>{
  const records=new Map(), snapshots=new Map();
  let prefs={voiceEnabled:false}, config={voice:'',resource:'',configured:false}, thread='', audio=null,settingsRefreshing=false;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const hosted=location.hostname!=='127.0.0.1'&&location.hostname!=='localhost';
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const storeKey=id=>'codex-voice-status:'+id;
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
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'服务暂时不可用');
    return data;
  }
  async function digest(text){
    const payload=JSON.stringify([text,config.voice,config.resource,'v3-sse-mp3']);
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
  function paint(ref,state){
    const button=[...document.querySelectorAll('.voice-button')].find(b=>b.dataset.voiceRef===ref);
    if(!button)return;
    button.classList.toggle('cached',state==='cached');
    button.classList.toggle('busy',state==='busy');
    button.disabled=state==='busy';
    button.title=state==='cached'?'已有语音，点击播放':state==='busy'?'正在合成语音':'未缓存，点击生成语音';
    button.textContent=state==='busy'?'◌':state==='cached'?'🔊':'🔈';
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
      if(item?.key)paint(ref,state.cached[item.key]?'cached':'uncached');
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
    if(thread===id)await refreshStatus(id,refs);
  }
  async function waitTask(taskId){
    for(let attempt=0;attempt<180;attempt++){
      const state=await json('/api/voice/task/'+encodeURIComponent(taskId));
      if(state.status==='completed')return state.key;
      if(['failed','expired','cancelled'].includes(state.status))
        throw new Error(state.error||'本机暂不可用，请稍后重试');
      await sleep(1000);
    }
    throw new Error('合成等待超时，请稍后重试');
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
      paint(ref,'uncached');player.remove();audio=null;
      button.title='缓存已过期，请再次点击补传';
    };
    player.onended=()=>{player.remove();audio=null;};
    player.play().catch(()=>{player.hidden=false;});
  }
  async function click(ref){
    const item=records.get(ref);
    if(!item||!item.key)return;
    const state=snapshot(item.threadId);
    if(state.cached[item.key]){play(ref,item.key);return;}
    paint(ref,'busy');
    try{
      if(hosted){
        const status=await json('/api/status');
        if(!status.online)throw new Error('本机离线，暂不能生成语音');
      }
      const response=await json('/api/voice/request',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({threadId:item.threadId,text:item.text,key:item.key})});
      const key=response.cached?response.key:hosted?await waitTask(response.taskId):response.key;
      if(key!==item.key)throw new Error('语音配置已变化，请刷新页面');
      state.cached[key]=true;save(item.threadId);paint(ref,'cached');play(ref,key);
    }catch(error){
      paint(ref,'uncached');
      const button=[...document.querySelectorAll('.voice-button')].find(b=>b.dataset.voiceRef===ref);
      if(button)button.title=error.message||'语音请求失败，请重试';
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
