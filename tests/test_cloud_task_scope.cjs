const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('cloud/web/app.js','utf8');
const functions = ['loadStatus','pollTask'].map(name => {
  const line = source.split(/\r?\n/).find(s => s.startsWith(`async function ${name}(`) || s.includes(`async function ${name}(`));
  assert.ok(line, name);
  return line.slice(line.indexOf(`async function ${name}(`));
}).join('\n');
(async () => {
  const messages = [], context = vm.createContext({Date, Set, Map, console,
    els:{mode:{}},taskStrip:{},renderActivityStatus(){},showTask(message){messages.push(message);},
    fetch:async()=>({json:async()=>({online:true,mode:'mobile',label:'在线',activeThreads:[{id:'b'}]})})});
  vm.runInContext(`let selected='b',lastGlobalActiveIds=new Set(),selectedCompletedUntil=0,
    serviceRestartLatched=false,serviceOfflineNotice=false,activeWebTaskId='task-a',
    activeTaskThreadId='a',waitingForThreadCompletion=false,steeredThreadId=null,
    cloudThreadStates=new Map(),cloudTaskPolling=false,lastTaskEventId=0;
    ${functions}`,context);
  await vm.runInContext('loadStatus()',context);
  assert.deepEqual(messages,['当前对话正在处理']); // A's pending task cannot suppress B's status.
  messages.length=0;
  let release;
  context.fetch=()=>new Promise(resolve=>{release=resolve;});
  vm.runInContext("selected='a'",context);
  const request=vm.runInContext('pollTask()',context);
  vm.runInContext("selected='b'",context); // Switch while A's request is in flight.
  release({json:async()=>({events:[{id:1,kind:'progress',payload:{summary:'A-only'}}]})});
  await request;
  assert.deepEqual(messages,[]);
  assert.equal(vm.runInContext('lastTaskEventId',context),0); // Replay when A is revisited.
  console.log('cloud: cross-thread status and late task-event isolation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
