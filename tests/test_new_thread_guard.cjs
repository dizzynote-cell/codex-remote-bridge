const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
async function check(file){
 const submit={disabled:false,textContent:'创建并发送'},title={disabled:false,value:'Example'},existing={disabled:true},cancel={disabled:false},close={disabled:false},opener={disabled:false};
 let note,closed=0,prevented=false;
 const form={elements:[submit,title,existing,cancel,close],querySelector:s=>s==='[type="submit"]'?submit:s==='footer'?{before:n=>note=n}:s==='#close-new-thread'?close:s==='#cancel-new-thread'?cancel:null,setAttribute(){},removeAttribute(){}};
 const dialog={addEventListener:(name,fn)=>dialog[name]=fn,close:()=>closed++};
 const ctx={window:{},document:{createElement:()=>({setAttribute(){}})},setTimeout:fn=>setTimeout(fn,0),Date};
 vm.runInNewContext(fs.readFileSync(file,'utf8'),ctx);
 const guard=ctx.window.createThreadGuard({form,dialog,opener});
 assert(guard.start());assert.equal(guard.start(),false);assert(submit.disabled&&opener.disabled&&title.disabled);assert.match(submit.textContent,/正在创建/);
 dialog.cancel({preventDefault:()=>prevented=true});assert(prevented);
 let reads=0;
 await guard.local({taskId:'task'},async()=>({ok:true,json:async()=>++reads===1?{status:'running'}:{threadId:'created'}}));
 assert.equal(reads,2);assert(guard.busy);guard.succeed();assert.equal(closed,1);assert.equal(guard.busy,false);assert.equal(existing.disabled,true);assert.equal(title.disabled,false);assert.equal(title.value,'Example');
 guard.start();guard.fail({message:'invalid',creationConfirmed:true});assert.equal(guard.busy,false);assert.equal(submit.disabled,false);assert.equal(note.textContent,'invalid');
 guard.start();guard.fail(new Error('network'));assert(guard.busy);assert(submit.disabled);assert.equal(guard.start(),false);assert.match(note.textContent,/暂未确认/);assert.equal(cancel.disabled,false);
 // Polling only reads: a transient read failure does not unlock or replay creation.
 reads=0;
 await guard.local({taskId:'task'},async()=>{if(++reads===1)throw new Error('offline');return {ok:true,json:async()=>({threadId:'created'})};});
 assert.equal(reads,2);guard.succeed();
 guard.start();let eventReads=0;
 const created=await guard.cloud({taskId:'cloud'},async path=>({ok:true,json:async()=>path.includes('/events')?{events:++eventReads>1?[{kind:'created',payload:{threadId:'cloud-created'}}]:[]}:{tasks:[{id:'cloud',status:'running'}]}}));
 assert.equal(created.threadId,'cloud-created');guard.succeed();
 guard.start();await assert.rejects(guard.local({taskId:'failed'},async()=>({ok:true,json:async()=>({status:'failed',message:'rejected'})})),e=>e.creationConfirmed===true&&e.message==='rejected');
 guard.fail({creationConfirmed:true,message:'rejected'});assert.equal(guard.busy,false);
 console.log('PASS '+file+': single submission, confirmed creation, failure, unknown result, controls and drafts');
}
(async()=>{for(const file of ['web/new-thread-guard.js','cloud/web/new-thread-guard.js'].filter(f=>fs.existsSync(f)))await check(file);})().catch(e=>{console.error(e);process.exitCode=1});
