const assert=require('node:assert/strict'), fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..');
for(const sub of (fs.existsSync(path.join(root,'cloud/web/message-time.js'))?['web','cloud/web']:['web'])){
 const c={window:{},Intl,Date};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(root,sub,'message-time.js'),'utf8'),c);
 const {dateOf,render}=c.window.messageTime;
 assert.equal(dateOf(1793078100).toISOString(),dateOf(1793078100000).toISOString());
 assert.equal(dateOf('2026-10-27T05:15:00Z').toISOString(),'2026-10-27T05:15:00.000Z');
 for(const v of [null,0,-1,'bad','2026-10-27T05:15:00',true,Infinity])assert.equal(dateOf(v),null);
 const first={type:'userMessage'},steer={type:'userMessage'},turn={items:[first,steer],bridgeStartedAt:1793078100};
 assert.match(render(first,turn,'user'),/<time /);
 assert.match(render(steer,turn,'user'),/时间未记录/);
 assert.match(render(null,turn,'assistant'),/时间未记录/);
 assert.match(render({bridgeTimestamp:'<script>'},null,'assistant'),/时间未记录/);
 assert.match(render({bridgeTimestamp:1793078100000},turn,'assistant'),/datetime="2026-10-27T05:15:00.000Z"/);
 const app=fs.readFileSync(path.join(root,sub,'app.js'),'utf8');assert.match(app,/messageTime\?\.render/);
}
console.log('PASS recorded times, seconds/ms/ISO, invalid inputs and steering isolation');
