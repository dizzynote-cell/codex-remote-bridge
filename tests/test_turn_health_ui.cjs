const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
for (const file of ['web/turn-health.js', 'cloud/web/turn-health.js']) {
  const box = {hidden: true, textContent: '', dataset: {}};
  const ctx = {window: {}, document: {querySelector: () => box}, Date};
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), ctx);
  const ui = ctx.window.turnHealthUI;
  for (const [seconds, expected] of [[0,'0秒'],[59.9,'59秒'],[60,'1分 00秒'],[61,'1分 01秒'],
    [3599,'59分 59秒'],[3600,'1小时 00分 00秒'],[86399,'23小时 59分 59秒'],
    [86400,'1天 00小时 00分 00秒'],[93784,'1天 02小时 03分 04秒'],[-20,'0秒'],[NaN,'未知'],[Infinity,'未知']])
    assert.equal(ctx.window.formatSyncAge(seconds), expected);
  ui.begin('a'); ui.show('a', {kind: 'retrying', message: '连接模型失败，正在重试'});
  assert.equal(box.hidden, false);
  ui.begin('b'); assert.equal(box.hidden, true);
  ui.show('a', {kind: 'retrying', message: 'late response'}); assert.equal(box.hidden, true);
  ui.show('b', {kind: 'no_progress', message: '<script>test</script>'});
  assert.equal(box.textContent, '<script>test</script>'); // textContent, never HTML.
  ui.show('b', null); assert.equal(box.hidden, true);
  const thread = (id, status, items=[]) => ({id, turns:[{id:id+'-turn', status, items}]});
  const tool = {type:'commandExecution',status:'inProgress',command:'python scripts/inspect.py --token=never-display-this'};
  ui.show('b', null, null, thread('b','inProgress',[tool]));
  assert.match(box.textContent,/正在执行/); assert.match(box.textContent,/inspect\.py/);
  assert.doesNotMatch(box.textContent,/never-display|--token/);
  ui.begin('a'); ui.show('a',null,null,thread('a','completed'));
  assert.match(box.textContent,/本轮已完成/);
  ui.begin('b');
  assert.equal(box.hidden,false); assert.match(box.textContent,/上次读取.*inspect\.py/);
  ui.show('a',null,null,thread('a','completed')); // Late completion from A cannot clear B.
  assert.match(box.textContent,/inspect\.py/);
  ui.show('b',null,null,thread('b','inProgress',[{...tool,status:'completed'}]));
  assert.match(box.textContent,/等待模型继续/); assert.match(box.textContent,/最近操作已完成/);
  assert.doesNotMatch(box.textContent,/正在执行/);
  ui.show('b',{kind:'retrying',turnId:'old-turn',message:'obsolete retry'},null,thread('b','inProgress',[]));
  assert.doesNotMatch(box.textContent,/obsolete retry/);
  ui.show('b',{kind:'retrying',turnId:'b-turn',message:'正在重试'},null,thread('b','inProgress',[]));
  assert.equal(box.dataset.kind,'retrying');
  ui.show('b',{kind:'retrying',turnId:'b-turn',message:'正在重试'},null,thread('b','completed',[]));
  assert.match(box.textContent,/本轮已完成/); assert.doesNotMatch(box.textContent,/重试/);
  ui.show('b',null,Date.now()/1000-90,thread('b','inProgress',[tool]));
  assert.match(box.textContent,/上次同步时/);
  assert.match(box.textContent,/1分 30秒前/);
  ui.unavailable('b'); assert.match(box.textContent,/状态更新暂时断开/);
  ui.unavailable('a'); assert.match(box.textContent,/状态更新暂时断开/);
  ui.show('b',null,null,thread('b','inProgress',[{type:'commandExecution',status:{type:'inProgress'},command:'npm run build'}]));
  assert.match(box.textContent,/构建项目/); assert.doesNotMatch(box.textContent,/上次同步|断开/);
  ui.show('b',null,null,thread('b','inProgress',[{type:'fileChange',status:'inProgress'}]));
  assert.match(box.textContent,/修改文件/);
  ui.show('b',null,null,thread('b','inProgress',[tool,{type:'imageGeneration',status:'inProgress'}]));
  assert.match(box.textContent,/生成图片.*并行操作/);
  const waiting=thread('b','inProgress',[tool]);waiting.status={type:'active',activeFlags:['waitingForApproval']};
  ui.show('b',null,null,waiting);assert.match(box.textContent,/等待你处理/);
  ui.show('b',null,null,thread('b','failed'));assert.equal(box.dataset.kind,'failed');
  console.log(file + ': warning, recovery and thread-switch checks passed');
}
assert.equal(fs.readFileSync('web/turn-health.js','utf8').replace(/\r\n/g,'\n'),fs.readFileSync('cloud/web/turn-health.js','utf8').replace(/\r\n/g,'\n'));
