const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
for (const file of ['web/project-display.js', 'cloud/web/project-display.js']) {
  const context = {window: {}};
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), context);
  const d = context.window.projectDisplay;
  const p = {id: 'p', key: 'desktop:p', cwd: 'D:/new', name: 'PC cleanup'};
  const thread = {cwd: 'C:/old', projectOverride: 'C:/legacy', desktopProject: p};
  assert.equal(d.key(thread), 'desktop:p');
  assert.equal(d.name(d.key(thread), [p]), 'PC cleanup');
  assert.equal(d.cwd(d.key(thread), [p]), 'D:/new');
  assert.equal(thread.cwd, 'C:/old');
  assert.equal(d.key({cwd: 'C:/old', projectOverride: 'D:/manual'}), 'D:/manual');
  assert.equal(d.name('desktop:projectless', [p]), '独立会话');
  assert.equal(d.cwd('desktop:projectless', [p]), '');
  const groups = new Map([['C:/fallback', []], ['desktop:p', []]]);
  assert.equal(d.groups(groups, [p])[0][0], 'desktop:p');
}
console.log('Project grouping, labels, fallback and execution cwd checks passed.');
