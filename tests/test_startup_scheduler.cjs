const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{for(const sub of ['web','cloud/web']){
 const root=path.resolve(__dirname,'..',sub),frames=[],window={requestAnimationFrame:fn=>frames.push(fn)};
 vm.runInNewContext(fs.readFileSync(path.join(root,'startup-scheduler.js'),'utf8'),{window,Promise,Map,setTimeout});
 const scheduler=window.bridgeLoading,events=[];
 const work=scheduler.background('quota',async()=>{events.push('quota');return 7;});
 assert.equal(scheduler.background('quota',()=>events.push('duplicate')),work);
 assert.deepEqual(events,[]);scheduler.release();scheduler.begin();while(frames.length)frames.shift()();await Promise.resolve();assert.deepEqual(events,[]);
 scheduler.end();while(frames.length)frames.shift()();await Promise.resolve();assert.deepEqual(events,['quota']);assert.equal(await work,7);
 // Exercise the actual boot function with authentication, device choice and list promises.
 const source=fs.readFileSync(path.join(root,'app.js'),'utf8');const boot=source.split(/\r?\n/).find(line=>line.startsWith('async function boot()'));
 let finishChoice,finishList;events.length=0;
 const choice=new Promise(r=>finishChoice=r),list=new Promise(r=>finishList=r);
 const context={window:{bridgeAuthConfig:Promise.resolve({authRequired:true}),bridgeLoading:scheduler,sessionUI:{ensureChoice:()=>choice},modelPicker:{refresh:()=>events.push('models')},bridgeInteractions:{poll:()=>events.push('interactions')},voiceUI:{boot:()=>events.push('voice')}},authenticate:async()=>true,restoreActiveTask:()=>{},loadThreads:()=>{events.push('list');return list;},loadStatus:()=>events.push('status'),loadQuota:()=>events.push('quota'),showTask:()=>{},els:{threads:{}},setInterval:()=>{},pollTask:()=>{},monitorSteeredThread:()=>{}};
 vm.createContext(context);vm.runInContext(boot,context);const started=context.boot();await new Promise(setImmediate);
 if(sub==='cloud/web')assert.deepEqual(events,[],'device choice must precede list');
 finishChoice();await new Promise(setImmediate);await Promise.resolve();
 assert.deepEqual(events,['list']);finishList();await started;while(frames.length)frames.shift()();await Promise.resolve();
 assert.ok(events.includes('quota')&&events.includes('voice'));assert.equal(events[0],'list');
}
console.log('PASS primary/device-choice gates, foreground priority, dedupe and parallel auxiliary startup');})().catch(e=>{console.error(e);process.exitCode=1});
