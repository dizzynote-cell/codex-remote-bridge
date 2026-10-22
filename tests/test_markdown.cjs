const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

for (const root of ['web', 'cloud/web']) {
  const ctx = {URL}; ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(`${root}/lib/markdown-it-15.0.3.min.js`, 'utf8'), ctx);
  vm.runInContext(fs.readFileSync(`${root}/markdown.js`, 'utf8'), ctx);
  const render = ctx.renderMarkdown;
  const sample = '**提升画面、镜头和编排的 Skill：**\n\n' +
    '| 项目 | Star | 能改善什么 | 我的判断 |\n' +
    '|---|---:|---|---|\n' +
    '| [huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion) | **4,064** | 中文知识演示、动画语法 | 优先推荐 |\n' +
    '| hyperframes-motion-director | 462 | 分镜、排版、镜头运动 | 当前环境贴合 |';
  const html = render(sample);
  assert.match(html, /<table>/);
  assert.match(html, /<thead>/);
  assert.match(html, /<strong>4,064<\/strong>/);
  assert.match(html, /<a href="https:\/\/github.com/);
  assert.match(html, /class="markdown-table"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(render('1. 第一项\n2. 第二项'), /<ol>/);
  assert.match(render('`x < y`\n\n```js\nconst x = "<script>";\n```'), /<pre><code class="language-js">const x = &quot;&lt;script&gt;&quot;;/);
  const unsafe = render('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n[x](file:///C:/private)');
  assert.doesNotMatch(unsafe, /<script|<img|href="(?:javascript:|file:)/i);
  assert.match(unsafe, /&lt;script&gt;/);
  assert.doesNotMatch(render('![remote image](https://example.com/track.png)'), /<img/i);
  assert.equal(render(sample), html);
  const partial = render('| A | B |\n|---|---|\n| 尚未完成');
  assert.match(partial, /<table>/);
  const fallback = {window: {}, URL};
  vm.runInNewContext(fs.readFileSync(`${root}/markdown.js`, 'utf8'), fallback);
  assert.match(fallback.window.renderMarkdown('<script>'), /&lt;script&gt;/);
  console.log(`${root}: tables, formatting, streaming fragments, safe links and escaped HTML passed`);
}
