const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

for(const file of ['web/app.js','cloud/web/app.js']){
  const source=fs.readFileSync(file,'utf8');
  const definitions=['reasoningText','renderItem'].map(name=>{
    const line=source.split(/\r?\n/).find(line=>line.startsWith(`function ${name}(`));
    assert.ok(line,`${file}: missing ${name}`);
    return line;
  }).join('\n');
  const context={esc:value=>String(value),itemText:()=>'',window:{voiceUI:{record:()=>''}}};
  vm.runInNewContext(definitions,context);
  for(const summary of ['', '   ', [], {}, ['']]){
    assert.equal(context.renderItem({type:'reasoning',summary}),'',`${file}: empty summary should be hidden`);
  }
  const visible=context.renderItem({type:'reasoning',summary:['准备检查网页显示。']});
  assert.match(visible,/推理摘要/);
  assert.match(visible,/准备检查网页显示。/);
}
console.log('PASS reasoning cards show only nonempty summaries');
