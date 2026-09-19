// DOM-level tests with synthetic data. No browser or production service is used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');

class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.value=''; this.hidden=false; this.attributes={}; this.textContent=''; }
  append(...nodes) { for (const n of nodes) {n.parent=this;this.children.push(n);} }
  before(n) {n.parent=this.parent;this.parent.children.splice(this.parent.children.indexOf(this),0,n);}
  remove() {if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
  setAttribute(k,v) {this.attributes[k]=v;}
  set innerHTML(_) {throw new Error('Interaction content must never become HTML');}
}
function all(node, predicate) {return [node,...node.children.flatMap(c=>all(c,()=>true))].filter(predicate);}
async function drain() {for(let n=0;n<8;n++)await Promise.resolve();}
function fixture(file) {
  const parent=new Element('section'),anchor=new Element('div');parent.append(anchor);
  let data={session:'session-one',startedAt:1,revision:0,available:true,requests:[]}, offline=false, release;
  const posts=[];
  const context={document:{querySelector:s=>s==='#messages'?anchor:null,createElement:t=>new Element(t)},
    window:{},URL,threads:[{id:'t1',name:'报告任务'},{id:'t2',name:'浏览器任务'}],setInterval(){},console,
    fetch:async(url,options={})=>{
      if(offline)throw new Error('offline');
      if(options.method==='POST'){
        posts.push(JSON.parse(options.body));
        return new Promise(resolve=>{release=(status='queued')=>resolve({ok:true,json:async()=>({ok:true,status})});});
      }
      const snapshot=structuredClone(data);
      return {ok:true,status:200,json:async()=>snapshot};
    }};
  vm.runInNewContext(fs.readFileSync(file,'utf8'),context,{filename:file});
  return {parent,posts,context,setData:d=>{data=d;},getData:()=>data,setOffline:v=>{offline=v;},release:s=>release(s),
    poll:async()=>{await context.window.bridgeInteractions.poll();await drain();}};
}
const web={id:'r1',session:'session-one',threadId:'t1',turnId:'u1',status:'pending',category:'web',kind:'questions',
  title:'Codex 需要你的回答',message:'<img src=x onerror=evil()>',help:'可在网页回答',actions:['answer','cancel'],
  questions:[{id:'q',question:'选择语言',pc:false,options:[{label:'中文',description:'中文报告'}]}]};
const pc={id:'r2',session:'session-one',threadId:'t2',turnId:'u2',status:'pending',category:'pc',kind:'questions',
  title:'需要在主力 PC 操作',message:'请解锁主力 PC',help:'请回到电脑或使用远程协助',actions:['manual_done','cancel'],
  questions:[{id:'code',question:'请在 PC 输入验证码',pc:true,secret:true,options:[]}]};

async function run(file) {
  const f=fixture(file);await drain();
  f.setData({...f.getData(),requests:[web,pc]});await f.poll();
  const forms=all(f.parent,e=>e.tag==='form');assert.equal(forms.length,2);
  assert.equal(all(forms[1],e=>['input','textarea','select'].includes(e.tag)).length,0,'PC verification has no credential field');
  assert.ok(all(forms[0],e=>e.tag==='p').some(e=>e.textContent.includes('<img')),'untrusted text is literal');
  const draft=all(forms[0],e=>e.tag==='textarea')[0];draft.value='中文，保留技术术语';
  await f.poll();assert.equal(all(f.parent,e=>e.tag==='textarea')[0],draft,'poll preserves field identity');
  assert.equal(draft.value,'中文，保留技术术语');
  const submit=all(forms[0],e=>e.tag==='button'&&e.textContent==='提交回答')[0];
  const first=submit.onclick();submit.onclick();await drain();assert.equal(f.posts.length,1,'double click sends once');
  assert.equal(f.posts[0].threadId,'t1');assert.equal(f.posts[0].turnId,'u1');assert.equal(f.posts[0].answers.q,draft.value);
  f.setData({...f.getData(),requests:[{...web,delivery:'queued'},pc]});f.release('queued');await first;await drain();
  assert.ok(submit.disabled,'queued response disables repeat');
  await f.poll();assert.equal(all(f.parent,e=>e.tag==='textarea')[0].value,draft.value);
  // Server resolves the first request; the other conversation stays visible.
  f.setData({...f.getData(),revision:1,requests:[{...web,status:'answered'},pc]});await f.poll();
  assert.equal(all(f.parent,e=>e.tag==='form').length,1);
  const done=all(f.parent,e=>e.tag==='button'&&e.textContent==='我已在 PC 完成操作')[0];
  f.setOffline(true);await f.poll();assert.ok(done.disabled,'offline prevents stale answers');
  f.setOffline(false);await f.poll();assert.equal(done.disabled,false);
  const pending=done.onclick();await drain();assert.equal(f.posts[1].action,'manual_done');assert.equal(f.posts[1].threadId,'t2');
  f.release('answered');await pending;await drain();await f.poll();
  assert.equal(all(f.parent,e=>e.tag==='form').length,0,'old snapshot cannot resurrect locally acknowledged request');
  // Restarted session replaces old requests and invalidates old forms.
  f.setData({session:'session-two',startedAt:2,revision:0,available:true,requests:[{...web,id:'new',session:'session-two'}]});await f.poll();
  assert.equal(all(f.parent,e=>e.tag==='form').length,1);
  assert.equal(all(f.parent,e=>e.tag==='textarea')[0].value,'','old draft does not cross sessions');
  console.log('PASS',path.relative(root,file),'drafts, classification, routing, duplicate clicks, offline, restart, safe rendering');
}
(async()=>{
  const a=path.join(root,'web/interactions.js'),b=path.join(root,'cloud/web/interactions.js');
  assert.equal(fs.readFileSync(a,'utf8'),fs.readFileSync(b,'utf8'),'local/cloud interaction UI must stay identical');
  await run(a);await run(b);
})().catch(error=>{console.error(error);process.exitCode=1;});


