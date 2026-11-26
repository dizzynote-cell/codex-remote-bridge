const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function check(file){
 const source=fs.readFileSync(file,'utf8').replace(/\r\n/g,'\n'),start=source.indexOf('async function loadThread('),end=source.indexOf('\n}\n',start)+3;
 assert(start>=0&&end>start);
 const buttons={older:{},all:{}},urls=[];
 const messages={innerHTML:'',scrollHeight:100,scrollTop:0,clientHeight:100};
 const context={window:{turnStatusMessage:()=>'',formatSyncAge:()=>''},selected:null,threadLoading:false,threadController:null,threadRequestSerial:0,threadVisibleCounts:new Map(),threads:[],lastThreadSignature:'',completionTimer:null,cloudThreadStates:new Map(),
  AbortController,clearTimeout,Date,Map,els:{messages,title:{textContent:''},meta:{textContent:''}},
  document:{querySelector:s=>s==='#load-older-turns'&&messages.innerHTML.includes('id="load-older-turns"')?buttons.older:s==='#load-all-turns'&&messages.innerHTML.includes('id="load-all-turns"')?buttons.all:null},
  renderThreads(){},renderTurns:turns=>turns.map(t=>t.id).join(','),bindAttachmentButtons(){},projectName:()=>'',statusLabel:()=>'',showTask(){},
  fetch:async url=>{
   urls.push(url);const limit=new URL('http://test'+url).searchParams.get('turnLimit');
   const count=limit==='all'?20:Number(limit);
   return {json:async()=>({thread:{id:'one',turns:Array.from({length:count},(_,i)=>({id:String(20-count+i),status:'completed',items:[]})),bridgeTotalTurns:limit==='all'?20:null,bridgeHasMoreTurns:limit!=='all'}})};
  }};
 vm.createContext(context);vm.runInContext(source.slice(start,end),context);
 await vm.runInContext("loadThread('one')",context);
 assert.match(messages.innerHTML,/查看更早 6 轮/);assert.doesNotMatch(messages.innerHTML,/还有 0 轮/);assert.match(context.els.meta.textContent,/最近 6 轮/);
 buttons.older.onclick();await new Promise(setImmediate);
 assert.match(urls.at(-1),/turnLimit=12/);assert.match(context.els.meta.textContent,/最近 12 轮/);
 buttons.all.onclick();await new Promise(setImmediate);
 assert.match(urls.at(-1),/turnLimit=all/);assert.match(context.els.meta.textContent,/20 轮/);assert.doesNotMatch(messages.innerHTML,/id="load-older-turns"/);
 assert.equal(context.threadVisibleCounts.get('one'),'all');
 console.log('PASS '+file+': unknown totals, native has-more, 6→12→all and exact completed count');
}
(async()=>{for(const file of ['web/app.js','cloud/web/app.js'])await check(file);})().catch(e=>{console.error(e);process.exitCode=1});
