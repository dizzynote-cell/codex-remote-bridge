const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');

async function check(file){
  let posts=0, release;
  const stored=new Map();
  let button,player;
  const ref='turn-1:answer-1';
  const buttonFactory=()=>({dataset:{voiceRef:ref},classList:{toggle(){}},closest:()=>null,
    disabled:false,title:'',textContent:'',onclick:null,after(){}});
  button=buttonFactory();
  const fetch=async (url,options={})=>{
    if(url==='/api/voice/request'){
      posts++;
      return new Promise(resolve=>{release=()=>resolve({ok:true,json:async()=>({cached:true,key:stored.get('voiceKey')})});});
    }
    let data={};
    if(url==='/api/preferences')data={voiceEnabled:true};
    else if(url==='/api/voice/config')data={configured:true,voice:'test-voice',resource:'test-resource'};
    else if(url==='/api/status')data={online:true};
    else if(url.startsWith('/api/voice/status'))data={cached:{}};
    else if(url.startsWith('/api/voice/lookup/'))data={status:'missing',cached:false};
    else if(url==='/api/quota')data={};
    return {ok:true,json:async()=>data};
  };
  const context={window:{},location:{hostname:'example.com'},fetch,crypto:webcrypto,TextEncoder,
    sessionStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)},
    document:{querySelectorAll:selector=>selector==='.voice-button'?[button]:[],
      querySelector:selector=>selector==='#messages'?{after:element=>stored.set('dock',element)}:null,
      createElement:()=>({hidden:false,setAttribute(){},append(){},insertBefore(element){player=element},
        play:async()=>{},pause(){},remove(){},set src(v){this.url=v}}),body:{append:element=>stored.set('dock',element)}},
    MutationObserver:class{},setTimeout,console,confirm:()=>true,alert:()=>{}};
  vm.runInNewContext(fs.readFileSync(file,'utf8'),context,{filename:file});
  await context.window.voiceUI.settings();
  const item={id:'answer-1',type:'agentMessage',text:'长文本的已完成回复'};
  const turn={id:'turn-1',status:'completed'};
  context.window.voiceUI.clear('thread-1');
  context.window.voiceUI.record(turn,item,item.text,'final');
  await context.window.voiceUI.bind('thread-1');
  const payload=JSON.stringify([item.text,'test-voice','test-resource','v3-sse-mp3-rate25']);
  const hash=await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(payload));
  stored.set('voiceKey',Buffer.from(hash).toString('hex'));
  button.onclick();
  for(let n=0;n<20&&!release;n++)await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(posts,1,`${file}: first request must be sent`);
  // A background conversation refresh replaces the DOM button while POST is unresolved.
  button=buttonFactory();
  context.window.voiceUI.clear('thread-1');
  context.window.voiceUI.record(turn,item,item.text,'final');
  await context.window.voiceUI.bind('thread-1');
  button.onclick();
  assert.equal(posts,1,`${file}: a refreshed button must not resend an unresolved POST`);
  release();
  await new Promise(resolve=>setTimeout(resolve,20));
  assert.equal(button.textContent,'🔊',`${file}: completed request must restore cached state`);
  const dock=stored.get('dock');
  assert.ok(dock&&!dock.hidden,`${file}: audio dock must sit outside the message list`);
  // New message content replaces the old response DOM, not the audio dock.
  button=buttonFactory();
  assert.ok(player&&dock.hidden===false,`${file}: fresh replies must not interrupt audio`);
  player.pause();
  assert.equal(dock.hidden,false,`${file}: pause must keep the player available`);
  player.onended();
  assert.equal(dock.hidden,true,`${file}: natural completion must close the player`);
}

(async()=>{for(const file of ['web/voice-ui.js','cloud/web/voice-ui.js'])await check(file);
  console.log('PASS voice task dedupe and uninterrupted player lifecycle');})().catch(error=>{console.error(error);process.exitCode=1;});
