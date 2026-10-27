const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
for(const sub of (fs.existsSync(path.join(root,'cloud/web'))?['web','cloud/web']:['web'])){
 const c={document:{currentScript:{dataset:{provider:'codex'}}},window:{},localStorage:{getItem:()=>null},Intl,Date};
 vm.runInNewContext(fs.readFileSync(path.join(root,sub,'thread-browser-controls.js'),'utf8'),c);
 const api=c.window.threadBrowser;
 const rows=[{id:'test',updatedAt:1700000000},{id:'work',updatedAt:'2026-10-27T05:15:00Z'},{id:'pin',pinned:true,bridgeUpdatedAt:1000},{id:'unknown'}];
 assert.equal(Array.from(api.sort(rows),t=>t.id).join(','),'pin,work,test,unknown');
 assert.equal(rows[0].id,'test','must not mutate source order');
 assert.equal(api.epoch(1700000000),api.epoch(1700000000000));
 assert.equal(api.activity({updatedAt:100,syncedAt:2000}),100000,'sync times must not reorder');
 assert.equal(api.activity({updatedAt:100,lastOpened:3000}),100000,'viewing must not reorder');
 assert.equal(Array.from(api.sort([{id:'b'},{id:'a'}]),t=>t.id).join(','),'a,b');
}
console.log('PASS pins, real activity, stable ties, seconds/ms/ISO, no sync/view-time sorting');
