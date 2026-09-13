const assert=require('node:assert/strict');
const fs=require('node:fs');
for(const file of ['web/app.js','cloud/web/app.js']){
  const source=fs.readFileSync(file,'utf8');
  assert.match(source,/turnLimit=\$\{limit\}/);
  assert.match(source,/threadController\.abort\(\)/);
  assert.match(source,/requestId!==threadRequestSerial\|\|selected!==id/);
  assert.match(source,/Math\.min\(total,Number\(limit\)\+6\)/);
  assert.match(source,/查看更早 6 轮/);
  assert.match(source,/id="load-all-turns"[^>]*>查看全部/);
  assert.match(source,/threadVisibleCounts\.set\(id,'all'\)/);
  assert.doesNotMatch(source,/async function loadThread\(id,silent=false\)\{if\(threadLoading\)return/);
}
// Only the hosted UI performs Feishu OAuth; local UI is authenticated by loopback access.
assert.match(fs.readFileSync('cloud/web/app.js','utf8'),/function requestFeishuCode\(appId\)/,'OAuth helper must survive history loader edits');
console.log('PASS six-turn history, progressive expansion, latest-click cancellation');
