const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
for(const file of ['web/turn-health.js','cloud/web/turn-health.js']){
 const box={hidden:true,textContent:'',dataset:{}};
 const ctx={window:{},document:{querySelector:()=>box},Date};
 vm.runInNewContext(fs.readFileSync(file,'utf8'),ctx);
 const message=ctx.window.turnStatusMessage;
 const cases=[
  [{message:'Selected model is at capacity. Please try a different model.',codexErrorInfo:'serverOverloaded'},/模型服务繁忙/],
  [{codexErrorInfo:'usageLimitExceeded'},/额度或请求频率/],
  [{codexErrorInfo:{responseStreamDisconnected:{}}},/模型连接中断/],
  [{message:'maximum context length exceeded'},/上下文超出/],
  [{message:'authentication failed'},/身份验证失败/],
  [{message:'private-path token=secret',codexErrorInfo:'other'},/other/],
  [null,/具体原因暂未识别/]
 ];
 for(const [error,pattern] of cases){
  const turn={status:{type:'failed'},error,items:[]};
  assert.match(message(turn),pattern);assert.doesNotMatch(message(turn),/private-path|secret/);
  ctx.window.turnHealthUI.begin('one');ctx.window.turnHealthUI.show('one',null,null,{turns:[turn]});
  assert.equal(box.textContent,message(turn));assert.equal(box.dataset.kind,'failed');
 }
 // A command failure or an earlier failed turn must not label a successful turn failed.
 assert.equal(message({status:'completed',error:{codexErrorInfo:'serverOverloaded'},items:[{type:'commandExecution',status:'failed'}]}),'任务已完成');
 assert.match(message({status:'interrupted',items:[{type:'agentMessage',phase:'final_answer'}]}),/已有回复/);
 ctx.window.turnHealthUI.show('one',null,null,{turns:[{status:'failed',error:{codexErrorInfo:'serverOverloaded'}},{status:'completed'}]});
 assert.equal(box.textContent,'本轮已完成');
 assert.match(fs.readFileSync('web/local-composer.js','utf8'),/message:window.turnStatusMessage\(turn\)/);
 const cloud=fs.readFileSync('cloud/web/app.js','utf8');
 assert.match(cloud,/message:window.turnStatusMessage\(last\)/);
 assert.match(cloud,/failedTurn.*window.turnStatusMessage\(failedTurn\)/);
 assert.match(cloud,/showTask\(window.turnStatusMessage\(turn\)/);
}
console.log('PASS failure reasons, persisted history, task/steer hooks, success isolation and safe display');
