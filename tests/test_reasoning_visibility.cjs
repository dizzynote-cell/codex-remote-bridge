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
  const context={URL,esc:value=>String(value),itemText:()=>'',voiceUI:{record:()=>''}};
  context.window=context;
  vm.createContext(context);
  const root=require('node:path').dirname(file);
  for(const script of ['lib/markdown-it-15.0.3.min.js','markdown.js']){
    vm.runInContext(fs.readFileSync(`${root}/${script}`,'utf8'),context);
  }
  vm.runInContext(definitions,context);
  for(const summary of ['', '   ', [], {}, ['']]){
    assert.equal(context.renderItem({type:'reasoning',summary}),'',`${file}: empty summary should be hidden`);
  }
  const visible=context.renderItem({type:'reasoning',summary:['准备检查网页显示。']});
  assert.match(visible,/推理摘要/);
  assert.match(visible,/准备检查网页显示。/);
}
console.log('PASS reasoning cards show only nonempty summaries');
