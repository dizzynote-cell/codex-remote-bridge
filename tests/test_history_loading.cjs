const assert=require('node:assert/strict');
const fs=require('node:fs');
for(const file of ['web/app.js','cloud/web/app.js']){
  const source=fs.readFileSync(file,'utf8');
  assert.match(source,/turnLimit=\$\{limit\}/);
  assert.match(source,/threadController\.abort\(\)/);
  assert.match(source,/requestId!==threadRequestSerial\|\|selected!==id/);
  assert.match(source,/Math\.min\(total,limit\+6\)/);
  assert.match(source,/查看更早 6 轮/);
  assert.doesNotMatch(source,/async function loadThread\(id,silent=false\)\{if\(threadLoading\)return/);
}
console.log('PASS six-turn history, progressive expansion, latest-click cancellation');
