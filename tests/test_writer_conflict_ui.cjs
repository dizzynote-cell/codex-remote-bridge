// A rejected writer acquisition must stay an error and never trigger a resend.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
for (const [name, declaration, invoke] of [
  ['web/local-composer.js', 'const localShowTask=', 'localShowTask'],
  ['cloud/web/app.js', 'function showTask(', 'showTask']
]) {
  const line = fs.readFileSync(path.join(root, name), 'utf8').split(/\r?\n/).find(line => line.startsWith(declaration));
  assert.ok(line, name);
  const strip = {};
  const context = vm.createContext({localTaskStrip: strip, taskStrip: strip, serviceRestartLatched: false});
  vm.runInContext(line, context);
  context.raw = "Codex RPC 错误：{'code': -32600, 'message': 'thread demo-thread already has an active writer'}";
  vm.runInContext(`${invoke}(raw,true)`, context);
  assert.match(strip.textContent, /本次消息未发送/);
  assert.match(strip.textContent, /原客户端继续/);
  assert.doesNotMatch(strip.textContent, /-32600|already has an active writer/);
  assert.equal(strip.className, 'task-strip error');
  assert.equal(strip.hidden, false);
  vm.runInContext(`${invoke}('请求超时，请先查看历史',true)`, context);
  assert.equal(strip.textContent, '请求超时，请先查看历史');
  vm.runInContext(`${invoke}(raw,false)`, context);
  assert.equal(strip.textContent, context.raw, 'normal progress or quoted content must not be rewritten');
}
console.log('PASS writer-conflict guidance, preserved failure state, unchanged timeout and normal content');
