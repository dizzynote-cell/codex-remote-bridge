// SPDX-License-Identifier: MIT
// Copyright (c) 2026 xiyannan
// Project: Codex Remote Bridge
// PAIRED UI CONTRACT: keep conversation loading and interaction behavior aligned with the sibling web app.
// PAIRED UI CONTRACT: keep conversation loading and interaction behavior aligned with the sibling web app.
const els={threads:document.querySelector('#threads'),search:document.querySelector('#search'),count:document.querySelector('#count'),title:document.querySelector('#title'),meta:document.querySelector('#meta'),messages:document.querySelector('#messages'),refresh:document.querySelector('#refresh'),mode:document.querySelector('#mode'),loadMore:document.querySelector('#load-more'),quota:document.querySelector('#quota'),quotaDetails:document.querySelector('#quota-details'),menu:document.querySelector('#menu'),backdrop:document.querySelector('#sidebar-backdrop'),authGate:document.querySelector('#auth-gate'),authMessage:document.querySelector('#auth-message'),authRetry:document.querySelector('#auth-retry')};
let threads=[],managedProjects=[],selected=null,threadLoading=false,lastThreadSignature='',nextCursor=null,threadVisibleCounts=new Map(),threadRequestSerial=0,threadController=null;
window.addEventListener('bridge-voice-ready',()=>{lastThreadSignature='';});
const mobileDevice=/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)||navigator.maxTouchPoints>1&&Math.min(screen.width,screen.height)<900;
document.body.classList.toggle('mobile-ui',mobileDevice);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pathPattern=/[A-Za-z]:\\[^\r\n<>"|?*]+/g,imageExtensions=new Set(['jpg','jpeg','png','webp','gif','bmp','ico','tiff','heic']);

function projectName(cwd){return window.projectDisplay.name(cwd,managedProjects);}
function statusLabel(status){let value=status;if(typeof value==='string'&&value.trim().startsWith('{')){try{value=JSON.parse(value);}catch{}}const type=typeof value==='object'&&value?value.type:value;return({active:'当前已加载',notLoaded:'空闲',completed:'已完成',failed:'失败',interrupted:'已中断'}[type]||type||'未知');}
function renderThreads(){return window.threadBrowser.render();}
async function loadThreads(append=false){window.bridgeLoading?.begin();els.refresh.disabled=true;els.loadMore.disabled=true;try{const url=`/api/threads?limit=50${append&&nextCursor?`&cursor=${encodeURIComponent(nextCursor)}`:''}`,d=await(await fetch(url)).json();const incoming=d.threads||[];threads=append?[...threads,...incoming.filter(t=>!threads.some(old=>old.id===t.id))]:incoming;managedProjects=Array.isArray(d.projects)?d.projects:managedProjects;nextCursor=d.nextCursor||null;renderThreads();}finally{els.refresh.disabled=false;els.loadMore.disabled=false;window.bridgeLoading?.end();}}
async function loadStatus(){if(window.bridgeLoading&&!window.bridgeLoading.allowed())return;try{const d=await(await fetch('/api/status')).json();els.mode.textContent=d.label;els.mode.className=`mode ${d.mode}`;}catch{els.mode.textContent='模式状态不可用';els.mode.className='mode detecting';}}
const quotaPercent=value=>Math.max(0,Math.min(100,Number(value)||0));
const quotaTime=value=>value?new Date(value*1000).toLocaleString('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'short',hour:'2-digit',minute:'2-digit'}):'未知';
function quotaSection(label,remaining,used,reset,weekly=false){return`<section class="quota-detail-section${weekly?' weekly':''}"><div class="quota-detail-heading"><b>${label}</b><span>剩余 ${remaining}% · 已使用 ${used}%</span></div><div class="quota-detail-bar"><i style="width:${remaining}%"></i></div><div class="quota-detail-reset">刷新时间：${esc(reset)}</div></section>`;}
async function loadQuota(){if(window.bridgeLoading&&!window.bridgeLoading.allowed())return;const primaryLabel=els.quota.querySelector('[data-quota-primary]'),weeklyLabel=els.quota.querySelector('[data-quota-weekly]'),primaryBar=els.quota.querySelector('[data-quota-primary-bar]'),weeklyBar=els.quota.querySelector('[data-quota-weekly-bar]');try{const d=await(await fetch('/api/quota')).json();if(!d.available)throw new Error();const primary=quotaPercent(d.remainingPercent),primaryUsed=quotaPercent(d.usedPercent),hasWeekly=Boolean(d.weeklyAvailable),weekly=hasWeekly?quotaPercent(d.weeklyRemainingPercent):0,weeklyUsed=hasWeekly?quotaPercent(d.weeklyUsedPercent):0;primaryLabel.textContent=`额度${primary}%`;weeklyLabel.textContent=hasWeekly?`周额度${weekly}%`:'周额度--%';primaryBar.style.width=`${primary}%`;weeklyBar.style.width=`${weekly}%`;els.quotaDetails.innerHTML=`<strong>Codex 额度详情</strong><span>当前套餐：${esc(String(d.planType||'未知').toUpperCase())}</span>${quotaSection('5 小时额度',primary,primaryUsed,quotaTime(d.resetsAt))}${hasWeekly?quotaSection('周额度',weekly,weeklyUsed,quotaTime(d.weeklyResetsAt),true):'<section class="quota-detail-section weekly"><div class="quota-detail-heading"><b>周额度</b><span>暂未提供</span></div></section>'}`;}catch{primaryLabel.textContent='额度--%';weeklyLabel.textContent='周额度--%';primaryBar.style.width='0';weeklyBar.style.width='0';els.quotaDetails.innerHTML='<span>暂时没有可用的额度数据。</span>';}}
els.quota.onclick=event=>{event.stopPropagation();els.quotaDetails.hidden=!els.quotaDetails.hidden;};els.quotaDetails.onclick=event=>event.stopPropagation();document.addEventListener('click',()=>els.quotaDetails.hidden=true);
function itemText(i){if(!i)return'';if(i.type==='userMessage')return(i.content||[]).filter(x=>x.type==='text').map(x=>x.text||'').join('\n');if(i.type==='agentMessage')return i.text||'';return'';}
function reasoningText(i){const s=i.summary??i.summaries??i.text??i.content??'';if(Array.isArray(s))return s.map(x=>typeof x==='string'?x:(x.text||JSON.stringify(x))).join('\n\n');return typeof s==='string'?s:JSON.stringify(s,null,2);}
function renderItem(i,turn){const t=itemText(i);if(i.type==='agentMessage'&&i.phase==='commentary')return t?`<div class="commentary markdown-body">${window.messageTime?.render(i,turn,'assistant')||''}${window.renderMarkdown(t)}</div>`:'';if(i.type==='reasoning'){const c=reasoningText(i).trim();if(!c||c==='[]'||c==='{}')return'';return`<details class="reasoning-card"><summary><span>推理摘要</span><span class="expand-hint">展开查看</span></summary><div class="reasoning-body markdown-body">${window.renderMarkdown(c)}</div><div class="voice-actions">${window.voiceUI?.record(turn,i,c,'reasoning')||''}</div></details>`;}if(['commandExecution','fileChange','mcpToolCall','dynamicToolCall'].includes(i.type))return`<details class="tool"><summary>${esc(i.type)}</summary><pre>${esc(JSON.stringify(i,null,2))}</pre></details>`;return'';}
function cleanPath(v){return v.replace(/[\s.,:;，。；：）)\]}]+$/,'');}
function attachmentPaths(items){const found=[];for(const i of items){found.push(...((itemText(i).match(pathPattern)||[]).map(cleanPath)));if(i.type==='fileChange')for(const c of(i.changes||[]))if(/^[A-Za-z]:\\/.test(c.path||''))found.push(c.path);}return[...new Set(found)];}
function renderAttachments(turn){const files=turn.bridgeAttachments||[];if(!files.length)return'';return`<section class="attachments"><div class="attachment-heading">返回的文件</div>${files.map(file=>{const path=file.agentDiskPath||file.localPath,ext=(file.name.split('.').pop()||'').toLowerCase(),src=`/api/attachment?path=${encodeURIComponent(path)}`,direct=file.delivery!=='local_only',preview=direct&&imageExtensions.has(ext)?`<a href="${src}" target="_blank" rel="noopener"><img class="attachment-preview" src="${src}" alt="${esc(file.name)}" loading="lazy"></a>`:'',location=file.delivery==='agent_disk'?`Agent Disk：${path}`:`本机文件：${path}`,actions=direct?`<div class="attachment-actions"><a href="${src}" target="_blank" rel="noopener">查看 / 下载</a><button data-open-path="${esc(path)}">本机打开</button></div>`:`<div class="attachment-actions"><button data-open-path="${esc(path)}">本机打开</button></div>`;return`<div class="attachment-card">${preview}<div class="attachment-info"><strong>${esc(file.name)}</strong><span>${esc(location)}</span><span>${esc(file.reason||'')}</span></div>${actions}</div>`;}).join('')}</section>`;}
function bindAttachmentButtons(){document.querySelectorAll('[data-open-path]').forEach(b=>b.onclick=async()=>{const original=b.textContent;b.disabled=true;b.textContent='正在打开…';try{const r=await fetch(`/api/open-attachment?path=${encodeURIComponent(b.dataset.openPath)}`);if(!r.ok)throw new Error();b.textContent='已打开';}catch{b.textContent='文件不存在';}setTimeout(()=>{b.disabled=false;b.textContent=original;},1800);} );}
function renderTurns(turns){window.voiceUI?.clear(selected);if(!turns.length)return'<div class="empty"><h3>暂无历史</h3><p>从飞书向该对话发送第一条消息。</p></div>';return turns.map(turn=>{const items=turn.items||[],users=items.filter(x=>x.type==='userMessage'),agents=items.filter(x=>x.type==='agentMessage'),final=[...agents].reverse().find(x=>x.phase!=='commentary'),middle=items.filter(x=>!users.includes(x)&&x!==final).map(i=>renderItem(i,turn)).join(''),answer=itemText(final)||(agents.length?itemText(agents.at(-1)):'（尚无最终回答）');return`<article class="turn">${users.map((user,index)=>`<div class="user"><div class="label">${index?'补充引导':'你'}${window.messageTime?.render(user,turn,'user')||''}</div><div class="bubble">${esc(itemText(user)||'（非文字输入）')}</div></div>`).join('')}${middle}<div class="assistant"><div class="label">Codex · ${esc(window.modelPicker?.label(turn)||'模型未记录')}${window.messageTime?.render(final,turn,'assistant')||''}</div><div class="bubble"><div class="markdown-body">${window.renderMarkdown(answer)}</div><div class="voice-actions">${final?window.voiceUI?.record(turn,final,answer,'final')||'':''}</div></div></div>${renderAttachments(turn)}</article>`;}).join('');}
async function loadThread(id,silent=false,showOlder=false){
  if(silent&&threadLoading&&selected===id)return;
  window.turnHealthUI?.begin(id);
  const switching=selected!==id;
  if(switching&&!threadVisibleCounts.has(id))threadVisibleCounts.set(id,6);
  const limit=threadVisibleCounts.get(id)||6;
  if(threadController)threadController.abort();
  const controller=new AbortController(),requestId=++threadRequestSerial;
  threadController=controller;threadLoading=true;selected=id;window.modelPicker?.begin(id);renderThreads();
  if(!silent)els.messages.innerHTML='<div class="loading">正在读取最近对话…</div>';
  window.bridgeLoading?.begin();
  try{
    const response=await fetch(`/api/thread/${encodeURIComponent(id)}?turnLimit=${limit}`,{signal:controller.signal,cache:'no-store'});
    const data=await response.json();
    if(requestId!==threadRequestSerial||selected!==id)return;
    if(data.error){window.turnHealthUI?.unavailable(id);if(!silent)els.messages.innerHTML=`<div class="loading">${esc(data.error)}</div>`;return;}
    window.modelPicker?.thread(data.thread);
    window.turnHealthUI?.show(id,data.thread?.bridgeHealth,data.thread?.bridgeSync?.syncedAt,data.thread);
    const t=data.thread,total=Number(t.bridgeTotalTurns??(t.turns||[]).length),visible=(t.turns||[]).length;
    const signature=JSON.stringify([total,visible,(t.turns||[]).map(turn=>[turn.id,turn.status,turn.bridgeModel,(turn.items||[]).length])]);
    const summary=threads.find(item=>item.id===id);
    els.title.textContent=summary?.name||t.name||'未命名对话';
    const compactions=Number.isInteger(t.bridgeCompactionCount)&&t.bridgeCompactionCount>=0?`${t.bridgeCompactionCount} 次`:'未知';
    els.meta.textContent=`项目：${(t.desktopProject?.name||summary?.desktopProject?.name||projectName(summary?.projectOverride||t.projectOverride||summary?.cwd||t.cwd))} · ${statusLabel(t.status)} · ${total} 轮 · 压缩 ${compactions} · ID：${t.id||id}`;
    if(!silent||signature!==lastThreadSignature){
      const nearBottom=els.messages.scrollHeight-els.messages.scrollTop-els.messages.clientHeight<140,remaining=Math.max(0,total-visible);
      const older=remaining?`<div class="older-turns-wrap"><button id="load-older-turns" type="button">查看更早 6 轮（还有 ${remaining} 轮）</button><button id="load-all-turns" type="button">查看全部</button></div>`:'';
      els.messages.innerHTML=older+renderTurns(t.turns||[]);
      const olderButton=document.querySelector('#load-older-turns'),allButton=document.querySelector('#load-all-turns');
      if(olderButton)olderButton.onclick=()=>{threadVisibleCounts.set(id,Math.min(total,Number(limit)+6));loadThread(id,false,true);};
      if(allButton)allButton.onclick=()=>{threadVisibleCounts.set(id,'all');loadThread(id,false,true);};
      bindAttachmentButtons();
      window.voiceUI?.bind(id);
      if(showOlder)els.messages.scrollTop=0;else if(!silent||nearBottom)els.messages.scrollTop=els.messages.scrollHeight;
      lastThreadSignature=signature;
    }
  }catch(error){
    if(error.name!=='AbortError')window.turnHealthUI?.unavailable(id);
    if(error.name!=='AbortError'&&!silent)els.messages.innerHTML='<div class="loading">读取失败，请重试</div>';
  }finally{
    window.bridgeLoading?.end();
    if(requestId===threadRequestSerial){threadLoading=false;threadController=null;}
  }
}
async function authenticate(){els.authGate.hidden=false;els.authRetry.hidden=true;els.authMessage.textContent='正在连接飞书并确认身份…';try{const config=await(window.bridgeAuthConfig||fetch('/api/auth/config',{cache:'no-store'}).then(response=>response.json()));if(!config.authRequired||config.authenticated){els.authGate.hidden=true;return true;}if(!config.ownerConfigured)throw new Error('桥尚未绑定所有者，请先在机器人单聊中发送一条消息');const code=await requestFeishuCode(config.appId);const response=await fetch('/api/auth/feishu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});const result=await response.json();if(!response.ok)throw new Error(result.error==='owner_mismatch'?'当前飞书账号不是桥的所有者':(result.message||'身份验证失败'));els.authGate.hidden=true;return true;}catch(error){els.authMessage.textContent=error.message||'身份验证失败';els.authRetry.hidden=false;return false;}}
async function boot(){if(!await authenticate())return;try{await loadThreads();}catch{(els.threads.textContent='对话列表暂时无法读取，请点击刷新');}finally{window.bridgeLoading?.release();}const tasks=[['status',loadStatus],['quota',loadQuota],['models',()=>window.modelPicker?.refresh()],['interactions',()=>window.bridgeInteractions?.poll()],['voice',()=>window.voiceUI?.boot()]];for(const[key,job]of tasks){if(window.bridgeLoading)window.bridgeLoading.background(key,job).catch(()=>{});else Promise.resolve().then(job).catch(()=>{});}setInterval(()=>loadThreads(false),30000);setInterval(loadStatus,5000);setInterval(loadQuota,60000);setInterval(()=>{if(selected)loadThread(selected,true);},3000);}
els.authRetry.onclick=boot;els.menu.onclick=()=>document.body.classList.add('sidebar-open');els.backdrop.onclick=()=>document.body.classList.remove('sidebar-open');els.search.oninput=renderThreads;els.refresh.onclick=()=>{loadThreads();if(selected)loadThread(selected,true);};els.loadMore.onclick=()=>loadThreads(true);boot();
