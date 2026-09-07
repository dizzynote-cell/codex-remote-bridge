const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Element {
  constructor(){this.dataset={};this.value='';this.classList={toggle(){}};this.children=[];this.nodes={};}
  set innerHTML(value){this.html=value;}
  querySelector(selector){return this.nodes[selector] ||= new Element();}
  before(){}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
}
async function main(){
  const document={nodes:{},querySelector(selector){return this.nodes[selector] ||= new Element();},createElement(){return new Element();}};
  const models=['a','b'].map(model=>({model,displayName:model,defaultReasoningEffort:'low',supportedReasoningEfforts:[{reasoningEffort:'low'},{reasoningEffort:'high'}]}));
  let choices={},stamp=100,pendingResolve;
  const context={document,Option:class{constructor(text,value){this.text=text;this.value=value;}},window:{},setInterval(){},Date,console,
    fetch:async (url,opts)=>{
      if(opts?.method==='POST'){const body=JSON.parse(opts.body);choices[body.threadId]={...body,updated:++stamp};}
      return {ok:true,json:async()=>({models,defaults:{model:'a',effort:'low'},choices})};
    }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/model-picker.js'),'utf8'),context);
  const picker=context.window.modelPicker;
  await new Promise(r=>setImmediate(r));
  picker.begin('thread-one');picker.thread({id:'thread-one',turns:[]});
  assert.equal(picker.capture('thread-one').model,'a');
  assert.equal(picker.capture('thread-one').effort,'low');
  assert.equal(picker.capture('thread-one').followDefaults,true);
  // Discover the controls created inside the section.
  let section;
  const oldCreate=document.createElement;
  // A second isolated boot exposes the controls via a tracked section.
  document.createElement=function(tag){const e=oldCreate(tag);if(tag==='section')section=e;return e;};
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/model-picker.js'),'utf8'),context);
  await new Promise(r=>setImmediate(r));
  const p=context.window.modelPicker;p.begin('thread-one');p.thread({id:'thread-one',turns:[]});
  const model=section.querySelector('#bridge-model'),effort=section.querySelector('#bridge-effort');
  model.value='b';await model.onchange();
  effort.value='high';await effort.onchange();
  assert.equal(p.capture('thread-one').model,'b');
  assert.equal(p.capture('thread-one').effort,'high');
  assert.equal(p.capture('thread-one').followDefaults,false);
  assert.equal(Object.keys(choices).length,0,'selection must not POST settings');
  await p.refresh();assert.equal(p.capture('thread-one').effort,'high','poll must preserve draft');
  p.accepted('thread-one',p.capture('thread-one'));
  p.begin('thread-two');assert.throws(()=>p.capture('thread-two'));
  p.thread({id:'thread-two',turns:[]});assert.equal(p.capture('thread-two').model,'a');
  p.begin('thread-one');p.thread({id:'thread-one',turns:[{status:'inProgress',bridgeModel:{requested:'a',effort:'low'}}]});
  assert.equal(p.capture('thread-one').model,'b');
  assert.match(section.querySelector('span').textContent,/本轮：a/);
  assert.equal(p.capture('thread-one').followDefaults,false);
  assert.equal(p.capture('thread-one').effort,'high');
  assert.ok(!section.html.includes('model-follow'));
  assert.ok(!section.html.includes('下次模型'));
  assert.match(p.label({}),/未记录/);
  console.log('PASS picker defaults, per-thread memory, effort, switching, running label, draft-only selection, accepted persistence');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
