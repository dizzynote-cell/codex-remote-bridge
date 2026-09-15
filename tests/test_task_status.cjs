const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/local-composer.js','utf8');
const functions=source.slice(source.indexOf('const localTrackedTasks='),source.indexOf('setInterval(renderLocalTracked'));
async function scenario(task,turns){
  const shown=[];
  const context={selected:'thread',setTimeout:fn=>fn(),localTaskStrip:{},
    localShowTask:(message,error)=>shown.push({message,error}),responseJson:async r=>r.data,
    loadThreads:async()=>{},loadThread:()=>{},fetch:async url=>({ok:true,data:task,json:async()=>({thread:{turns}})})};
  vm.createContext(context);vm.runInContext(functions,context);
  await vm.runInContext("pollLocalTask('task')",context);
  return {shown,strip:context.localTaskStrip};
}
(async()=>{
  let result=await scenario({threadId:'thread',turnId:'one',status:'interrupted',message:'old'},[{id:'one',status:'interrupted',items:[]}]);
  assert.match(result.shown.at(-1).message,/本轮已中断/);
  assert.equal(result.strip.className,'task-strip interrupted');
  result=await scenario({threadId:'thread',turnId:'one',status:'interrupted',message:'old'},[{id:'one',status:'interrupted'},{id:'two',status:'completed'}]);
  assert.equal(result.shown.at(-1).message,'任务已完成');
  result=await scenario({threadId:'thread',turnId:'one',status:'completed',steered:true},[{id:'one',status:'completed'}]);
  assert.equal(result.shown.at(-1).message,'任务已完成');
  console.log('PASS interrupted, successor, and steered completion status');
})().catch(error=>{console.error(error);process.exitCode=1});
