# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

import base64, binascii, hashlib, json, os, re, secrets, shutil, sqlite3, time, uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parent; WEB=ROOT/'web'; DB=Path(os.getenv('CODEX_HISTORY_DB',ROOT/'data/history.db')); UPLOADS=DB.parent/'uploads'
APP_ID=os.environ['FEISHU_APP_ID']; APP_SECRET=os.environ['FEISHU_APP_SECRET']; OWNER=os.environ['FEISHU_OWNER_OPEN_ID']; SYNC_TOKEN=os.environ['SYNC_TOKEN']
PUBLIC_BASE_URL=os.environ['PUBLIC_BASE_URL'].rstrip('/'); CLIENT_PROJECTS_ROOT=os.getenv('CLIENT_PROJECTS_ROOT',''); CLIENT_STANDALONE_DIR=os.getenv('CLIENT_STANDALONE_DIR','')
SESSIONS={}; OAUTH_STATES={}
DB.parent.mkdir(parents=True,exist_ok=True); UPLOADS.mkdir(parents=True,exist_ok=True)
db=sqlite3.connect(DB,check_same_thread=False)
db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA busy_timeout=5000')
db.executescript('''CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,status TEXT,preview TEXT,updated_at TEXT,payload TEXT NOT NULL,content_hash TEXT NOT NULL,synced_at INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS idx_threads_synced_at ON threads(synced_at DESC);CREATE TABLE IF NOT EXISTS hidden_threads(thread_id TEXT PRIMARY KEY,hidden_at INTEGER NOT NULL);CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,op TEXT NOT NULL,thread_id TEXT,title TEXT,cwd TEXT,text TEXT,source TEXT NOT NULL,status TEXT NOT NULL,created_at INTEGER NOT NULL,claimed_at INTEGER,updated_at INTEGER NOT NULL,result TEXT,error TEXT);CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status,created_at);CREATE TABLE IF NOT EXISTS task_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id,id);CREATE TABLE IF NOT EXISTS task_files(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,name TEXT NOT NULL,mime TEXT,size INTEGER NOT NULL,path TEXT NOT NULL,created_at INTEGER NOT NULL);CREATE INDEX IF NOT EXISTS idx_task_files_task ON task_files(task_id);'''); db.commit()
db.execute('CREATE TABLE IF NOT EXISTS output_files(id TEXT PRIMARY KEY,name TEXT NOT NULL,mime TEXT,size INTEGER NOT NULL,path TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)');db.commit()
ALLOWED_UPLOAD_EXT={'.jpg','.jpeg','.png','.webp','.gif','.bmp','.pdf','.doc','.docx','.xls','.xlsx','.csv','.ppt','.pptx','.txt','.md'}
def valid_thread_id(value):
    try: uuid.UUID(str(value).removeprefix('urn:uuid:')); return True
    except (ValueError,AttributeError,TypeError): return False


MODEL_LOCK=__import__('threading').RLock()
def model_settings():
    row=db.execute("SELECT value FROM meta WHERE key='model_settings'").fetchone()
    return json.loads(row[0]) if row else {'models':[],'choices':{}}

def valid_effort(model,effort):
    entry=next((m for m in model_settings()['models'] if m['model']==model),{})
    return effort in {e['reasoningEffort'] for e in entry.get('supportedReasoningEfforts',[])}

def merge_model_settings(incoming):
    with MODEL_LOCK:
        saved=model_settings()
        if incoming.get('models'):
            saved['models']=incoming['models']
        if incoming.get('defaults'):saved['defaults']=incoming['defaults']
        allowed={m['model'] for m in saved['models']}
        for thread_id,choice in (incoming.get('choices') or {}).items():
            if not valid_thread_id(thread_id) or not isinstance(choice,dict):continue
            stamp=choice.get('updated')
            if (choice.get('model') is not None and choice.get('model') not in allowed) or not isinstance(stamp,(float,int)) or not 0<stamp<time.time()+60:continue
            if stamp>saved['choices'].get(thread_id,{}).get('updated',0):
                saved['choices'][thread_id]={'model':choice.get('model'),'effort':choice.get('effort'),'updated':stamp}
        db.execute("INSERT INTO meta VALUES('model_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(saved),))
        db.commit()
        return saved

def post_json(url,payload,headers=None):
    req=Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',**(headers or {})},method='POST')
    with urlopen(req,timeout=20) as r:return json.loads(r.read())
def cookie_token(h):
    c=SimpleCookie(); c.load(h or ''); return c.get('codex_history').value if c.get('codex_history') else ''
def text_value(value):
    if value is None:return None
    if isinstance(value,(str,int,float,bool)):return str(value)
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))

class H(BaseHTTPRequestHandler):
    def json(self,p,status=200,cookie=None):
        b=json.dumps(p,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(b)))
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers(); self.wfile.write(b)
    def authed(self):
        t=cookie_token(self.headers.get('Cookie')); return SESSIONS.get(t,0)>time.time()
    def redirect(self,location,cookie=None):
        self.send_response(302); self.send_header('Location',location); self.send_header('Cache-Control','no-store')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers()
    def new_session(self):
        token=secrets.token_urlsafe(32); SESSIONS[token]=time.time()+30*86400
        return f'codex_history={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={30*86400}'
    def exchange_feishu_code(self,code):
        app=post_json('https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal',{'app_id':APP_ID,'app_secret':APP_SECRET})
        user=post_json('https://open.feishu.cn/open-apis/authen/v1/access_token',{'grant_type':'authorization_code','code':code},{'Authorization':'Bearer '+app['app_access_token']})
        return user.get('data') or {}
    def do_GET(self):
        p=urlparse(self.path)
        if p.path=='/api/auth/config':return self.json({'appId':APP_ID,'authRequired':True,'authenticated':self.authed(),'ownerConfigured':True,'projectsRoot':CLIENT_PROJECTS_ROOT,'standaloneDir':CLIENT_STANDALONE_DIR})
        if p.path=='/api/auth/oauth/start':
            query=parse_qs(p.query); return_to=(query.get('return_to') or ['/'])[0]
            if not return_to.startswith('/') or return_to.startswith('//'):return_to='/'
            state=secrets.token_urlsafe(32); OAUTH_STATES[state]=(time.time()+600,return_to)
            callback=PUBLIC_BASE_URL+'/api/auth/oauth/callback'
            auth_url='https://open.feishu.cn/open-apis/authen/v1/authorize?'+urlencode({'app_id':APP_ID,'redirect_uri':callback,'state':state})
            return self.redirect(auth_url)
        if p.path=='/api/auth/oauth/callback':
            query=parse_qs(p.query); state=(query.get('state') or [''])[0]; code=(query.get('code') or [''])[0]
            saved=OAUTH_STATES.pop(state,None)
            if not saved or saved[0]<time.time() or not code:return self.json({'error':'invalid_or_expired_oauth_state'},400)
            try:identity=self.exchange_feishu_code(code)
            except Exception:return self.json({'error':'feishu_oauth_failed'},502)
            if identity.get('open_id')!=OWNER:return self.json({'error':'owner_mismatch'},403)
            return self.redirect(saved[1],cookie=self.new_session())
        if p.path=='/api/device/tasks':
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            now=int(time.time()); db.execute("UPDATE tasks SET status='expired',updated_at=? WHERE status='queued' AND created_at<?",(now,now-30))
            for old in db.execute('SELECT id,path FROM task_files WHERE created_at<?',(now-3600,)).fetchall():
                try:Path(old[1]).unlink(missing_ok=True)
                except OSError:pass
                db.execute('DELETE FROM task_files WHERE id=?',(old[0],))
            db.commit()
            row=db.execute("SELECT id,op,thread_id,title,cwd,text,source,created_at FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:return self.json({'task':None})
            changed=db.execute("UPDATE tasks SET status='claimed',claimed_at=?,updated_at=? WHERE id=? AND status='queued'",(now,now,row[0])).rowcount; db.commit()
            if not changed:return self.json({'task':None})
            task=dict(zip(('id','op','threadId','title','cwd','text','source','createdAt'),row)); files=db.execute('SELECT id,name,mime,size FROM task_files WHERE task_id=? ORDER BY created_at',(row[0],)).fetchall(); task['files']=[dict(zip(('id','name','mime','size'),f)) for f in files]
            model_row=db.execute('SELECT value FROM meta WHERE key=?',('task_model:'+task['id'],)).fetchone()
            choice=json.loads(model_row[0]) if model_row else {}
            task['model']=choice.get('model')
            task['modelUpdated']=choice.get('updated')
            task['effort']=choice.get('effort')
            task['followDefaults']=choice.get('followDefaults',False)
            return self.json({'task':task})
        if p.path=='/api/device/storage':
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            now=int(time.time())
            for row in db.execute('SELECT id,path FROM output_files WHERE expires_at<?',(now,)).fetchall():
                try:Path(row[1]).unlink(missing_ok=True)
                except OSError:pass
                db.execute('DELETE FROM output_files WHERE id=?',(row[0],))
            db.commit();usage=shutil.disk_usage(DB.parent);stored=db.execute('SELECT COALESCE(SUM(size),0) FROM output_files').fetchone()[0];available=usage.free>=2*1024**3 and usage.free/usage.total>=.10 and stored<5*1024**3
            return self.json({'available':available,'freeBytes':usage.free,'totalBytes':usage.total,'storedBytes':stored,'message':'' if available else '云端可用存储不足或已接近安全线'})
        if p.path.startswith('/api/device/files/'):
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            file_id=unquote(p.path.split('/api/device/files/',1)[1]); row=db.execute('SELECT name,mime,size,path FROM task_files WHERE id=?',(file_id,)).fetchone()
            if not row:return self.send_error(404)
            f=Path(row[3]);
            if not f.is_file():return self.send_error(404)
            b=f.read_bytes(); self.send_response(200); self.send_header('Content-Type',row[1] or 'application/octet-stream'); self.send_header('Content-Length',str(len(b))); self.send_header('X-File-Name',quote(row[0])); self.end_headers(); self.wfile.write(b); return
        if p.path.startswith('/api/') and not self.authed():return self.json({'error':'feishu_login_required'},401)
        if p.path=='/api/models':return self.json(model_settings())
        if p.path.startswith('/api/output-files/'):
            file_id=unquote(p.path.split('/api/output-files/',1)[1]);row=db.execute('SELECT name,mime,size,path,expires_at FROM output_files WHERE id=?',(file_id,)).fetchone()
            if not row or row[4]<int(time.time()) or not Path(row[3]).is_file():return self.send_error(404)
            b=Path(row[3]).read_bytes();self.send_response(200);self.send_header('Content-Type',row[1]);self.send_header('Content-Length',str(len(b)));self.send_header('Content-Disposition',f"inline; filename*=UTF-8''{quote(row[0])}");self.end_headers();self.wfile.write(b);return
        if p.path=='/api/tasks':
            q=parse_qs(p.query); after=int((q.get('after') or ['0'])[0] or 0)
            rows=db.execute("SELECT id,op,thread_id,title,cwd,text,source,status,created_at,updated_at,result,error FROM tasks WHERE updated_at>=? ORDER BY created_at DESC LIMIT 50",(after,)).fetchall()
            return self.json({'tasks':[dict(zip(('id','op','threadId','title','cwd','text','source','status','createdAt','updatedAt','result','error'),r)) for r in rows]})
        if p.path.startswith('/api/task/') and p.path.endswith('/events'):
            task_id=unquote(p.path.split('/api/task/',1)[1].rsplit('/events',1)[0]); q=parse_qs(p.query); after=int((q.get('after') or ['0'])[0] or 0)
            rows=db.execute('SELECT id,kind,payload,created_at FROM task_events WHERE task_id=? AND id>? ORDER BY id',(task_id,after)).fetchall()
            return self.json({'events':[{'id':r[0],'kind':r[1],'payload':json.loads(r[2]),'createdAt':r[3]} for r in rows]})
        if p.path=='/api/threads':
            rows=db.execute('SELECT id,name,cwd,status,preview,updated_at,synced_at FROM threads WHERE id NOT IN (SELECT thread_id FROM hidden_threads) ORDER BY CAST(updated_at AS REAL) DESC').fetchall()
            return self.json({'threads':[{'id':r[0],'name':r[1],'cwd':r[2],'status':r[3],'preview':r[4],'updatedAt':r[5],'syncedAt':r[6]} for r in rows],'nextCursor':None})
        if p.path=='/api/threads/hidden':
            rows=db.execute('SELECT t.id,t.name,t.cwd,h.hidden_at FROM hidden_threads h LEFT JOIN threads t ON t.id=h.thread_id ORDER BY h.hidden_at DESC').fetchall()
            return self.json({'threads':[{'id':r[0],'name':r[1] or '未命名对话','cwd':r[2],'hiddenAt':r[3]} for r in rows]})
        if p.path.startswith('/api/thread/'):
            query=parse_qs(p.query)
            try:
                with HISTORY_LOCK:
                    result=history_store.read(db,unquote(p.path.split('/api/thread/',1)[1]),(query.get('turnLimit') or ['6'])[0],(query.get('refresh') or ['0'])[0]=='1')
                return self.json(result or {'error':'对话尚未同步'},200 if result else 404)
            except ValueError:return self.json({'error':'invalid_turn_limit'},400)
        if p.path=='/api/status':
            row=db.execute("SELECT value FROM meta WHERE key='heartbeat'").fetchone(); ts=int(row[0]) if row else 0; online=time.time()-ts<75
            runtime_row=db.execute("SELECT value FROM meta WHERE key='runtime'").fetchone();runtime=json.loads(runtime_row[0]) if runtime_row else {};working=bool(runtime.get('working')) if online else False
            active_ids=[str(x) for x in (runtime.get('activeThreadIds') or []) if valid_thread_id(x)][:20] if online else []
            active_threads=[]
            for thread_id in active_ids:
                thread_row=db.execute('SELECT name,cwd FROM threads WHERE id=?',(thread_id,)).fetchone()
                active_threads.append({'id':thread_id,'name':thread_row[0] if thread_row else '正在运行的对话','cwd':thread_row[1] if thread_row else ''})
            history_row=db.execute("SELECT value FROM meta WHERE key='history_sync'").fetchone();history_ts=int(history_row[0]) if history_row else 0;history_stale=bool(online and time.time()-history_ts>120)
            notice_row=db.execute("SELECT value FROM meta WHERE key='service_notice'").fetchone(); notice=json.loads(notice_row[0]) if notice_row else None
            if notice and notice.get('state')=='restarting' and int(notice.get('until') or 0)>time.time():return self.json({'mode':'restarting','online':online,'label':'服务即将重启','seconds':max(1,int(notice['until']-time.time()))})
            label='服务中断，请检查主机状态' if not online else ('PC 在线 · 历史同步暂时延迟' if history_stale else 'PC 在线 · 同步通道已连接')
            return self.json({'mode':'mobile' if online else 'offline','online':online,'working':working,'activeCount':len(active_threads) if active_threads else (1 if working else 0),'activeThreads':active_threads,'historyStale':history_stale,'desktopRunning':online,'label':label})
        if p.path=='/api/quota':
            row=db.execute("SELECT value FROM meta WHERE key='quota'").fetchone(); return self.json(json.loads(row[0]) if row else {'available':False})
        rel='index.html' if p.path=='/' else p.path.lstrip('/'); f=(WEB/rel).resolve()
        if not f.is_file() or WEB.resolve() not in f.parents:return self.send_error(404)
        b=f.read_bytes(); ct={'.html':'text/html','.js':'application/javascript','.css':'text/css'}.get(f.suffix,'application/octet-stream'); self.send_response(200); self.send_header('Content-Type',ct+'; charset=utf-8'); self.send_header('Cache-Control','no-cache, no-store, must-revalidate'); self.send_header('Pragma','no-cache'); self.send_header('Expires','0'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        with DB_LOCK:
            return self._do_POST()
    def _do_POST(self):
        p=urlparse(self.path); n=min(int(self.headers.get('Content-Length') or 0),24*1024*1024); body=self.rfile.read(n)
        if p.path=='/api/device/heartbeat':
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            data=json.loads(body or b'{}');now=int(time.time());active_ids=[str(x) for x in (data.get('activeThreadIds') or []) if valid_thread_id(x)][:20];runtime={'working':bool(data.get('working')),'activeThreadIds':active_ids,'historySyncAge':data.get('historySyncAge'),'historyError':str(data.get('historyError') or '')[:300],'updatedAt':now}
            db.execute("INSERT INTO meta VALUES('heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(now),));db.execute("INSERT INTO meta VALUES('runtime',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(runtime,ensure_ascii=False),));db.commit();settings=merge_model_settings(data.get('modelSettings') or {});return self.json({'ok':True,'modelChoices':settings['choices']})
        if p.path.startswith('/api/device/output-files/'):
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            file_id=unquote(p.path.split('/api/device/output-files/',1)[1]);name=unquote(self.headers.get('X-File-Name') or 'file');mime=self.headers.get('X-File-Mime') or 'application/octet-stream'
            if not re.fullmatch(r'[0-9a-f]{32}',file_id):return self.json({'error':'invalid_file_id'},400)
            if len(body)<=0 or len(body)>10*1024*1024:return self.json({'error':'file_too_large'},400)
            usage=shutil.disk_usage(DB.parent);stored=db.execute('SELECT COALESCE(SUM(size),0) FROM output_files').fetchone()[0]
            if usage.free-len(body)<2*1024**3 or usage.free/usage.total<.10 or stored+len(body)>5*1024**3:return self.json({'error':'storage_low','message':'云端可用存储不足'},507)
            path=UPLOADS/f'output-{file_id}{Path(name).suffix.lower()}';path.write_bytes(body);now=int(time.time());db.execute('INSERT OR REPLACE INTO output_files VALUES(?,?,?,?,?,?,?)',(file_id,Path(name).name,mime,len(body),str(path),now,now+7*86400));db.commit();return self.json({'ok':True,'fileId':file_id,'expiresAt':now+7*86400})
        if p.path=='/api/sync':
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            with HISTORY_LOCK:
                result=history_store.ingest(db,json.loads(body))
            return self.json(result)
        if p.path=='/api/device/status':
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            data=json.loads(body or b'{}'); now=int(time.time()); state=str(data.get('state') or '')
            notice={'state':state,'until':now+max(5,min(int(data.get('seconds') or 20),300)),'message':str(data.get('message') or '')}
            db.execute("INSERT INTO meta VALUES('service_notice',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(notice,ensure_ascii=False),)); db.commit(); return self.json({'ok':True})
        if p.path.startswith('/api/device/tasks/'):
            if not secrets.compare_digest(self.headers.get('Authorization') or '',f'Bearer {SYNC_TOKEN}'):return self.json({'error':'unauthorized'},401)
            task_id=unquote(p.path.split('/api/device/tasks/',1)[1]); data=json.loads(body or b'{}'); now=int(time.time()); kind=str(data.get('kind') or 'status'); payload=data.get('payload') or {}
            db.execute('INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,?,?,?)',(task_id,kind,json.dumps(payload,ensure_ascii=False),now))
            status=data.get('status'); result=data.get('result'); error=data.get('error')
            if status:db.execute('UPDATE tasks SET status=?,updated_at=?,result=COALESCE(?,result),error=COALESCE(?,error) WHERE id=?',(status,now,result,error,task_id))
            else:db.execute('UPDATE tasks SET updated_at=? WHERE id=?',(now,task_id))
            if kind=='files_received':
                for file_id in payload.get('fileIds') or []:
                    row=db.execute('SELECT path FROM task_files WHERE id=? AND task_id=?',(str(file_id),task_id)).fetchone()
                    if row:
                        try:Path(row[0]).unlink(missing_ok=True)
                        except OSError:pass
                        db.execute('DELETE FROM task_files WHERE id=?',(str(file_id),))
            db.commit(); return self.json({'ok':True})
        if p.path=='/api/model-choice':
            if not self.authed():return self.json({'error':'feishu_login_required'},401)
            data=json.loads(body or b'{}');thread_id=str(data.get('threadId') or '');model=data.get('model')
            if not valid_thread_id(thread_id):return self.json({'error':'invalid_thread_id'},400)
            if model and model not in {m['model'] for m in model_settings()['models']}:return self.json({'error':'模型不可用，请等待本机同步模型列表'},400)
            effort=data.get('effort')
            if model and effort and not valid_effort(model,effort):return self.json({'error':'该模型不支持此推理强度'},400)
            return self.json(merge_model_settings({'choices':{thread_id:{'model':model,'effort':effort,'updated':time.time()}}}))
        if p.path=='/api/tasks':
            if not self.authed():return self.json({'error':'feishu_login_required'},401)
            data=json.loads(body or b'{}'); op=str(data.get('op') or 'message'); thread_id=str(data.get('threadId') or '').strip(); text=str(data.get('text') or '').strip(); title=str(data.get('title') or '').strip(); cwd=str(data.get('cwd') or '').strip()
            if op=='message' and (not thread_id or not text):return self.json({'error':'missing_thread_or_text'},400)
            if op=='message' and not valid_thread_id(thread_id):return self.json({'error':'invalid_thread_id','message':'所选条目不是有效的 Codex 对话，请刷新后重新选择'},400)
            if op=='new_thread' and (not title or not cwd):return self.json({'error':'missing_title_or_cwd'},400)
            model=data.get('model')
            if model and model not in {m['model'] for m in model_settings()['models']}:return self.json({'error':'模型不可用，请刷新模型列表'},400)
            effort=data.get('effort')
            if model and effort and not valid_effort(model,effort):return self.json({'error':'该模型不支持此推理强度'},400)
            incoming=data.get('files') or []
            if len(incoming)>3:return self.json({'error':'too_many_files'},400)
            decoded=[]; total=0
            try:
                for item in incoming:
                    name=Path(str(item.get('name') or '')).name; ext=Path(name).suffix.lower(); raw=base64.b64decode(str(item.get('data') or ''),validate=True); total+=len(raw)
                    if not name or ext not in ALLOWED_UPLOAD_EXT:raise ValueError('unsupported_file_type')
                    if len(raw)>10*1024*1024 or total>15*1024*1024:raise ValueError('file_too_large')
                    decoded.append((name,str(item.get('mime') or 'application/octet-stream'),raw))
            except (ValueError,binascii.Error) as error:return self.json({'error':str(error)},400)
            task_id=uuid.uuid4().hex; now=int(time.time()); db.execute('INSERT INTO tasks(id,op,thread_id,title,cwd,text,source,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(task_id,op,thread_id or None,title or None,cwd or None,text or None,'web','queued',now,now))
            if model:
                db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('task_model:'+task_id,json.dumps({'model':model,'effort':effort,'followDefaults':bool(data.get('followDefaults')),'updated':time.time()})))
                if thread_id and not data.get('followDefaults'):merge_model_settings({'choices':{thread_id:{'model':model,'effort':effort,'updated':time.time()}}})
            for name,mime,raw in decoded:
                file_id=uuid.uuid4().hex; path=UPLOADS/f'{file_id}{Path(name).suffix.lower()}'; path.write_bytes(raw); db.execute('INSERT INTO task_files VALUES(?,?,?,?,?,?,?)',(file_id,task_id,name,mime,len(raw),str(path),now))
            db.execute('INSERT INTO task_events(task_id,kind,payload,created_at) VALUES(?,?,?,?)',(task_id,'queued',json.dumps({'message':'已提交，等待本机桥接收','files':[x[0] for x in decoded]},ensure_ascii=False),now)); db.commit(); return self.json({'ok':True,'taskId':task_id,'status':'queued'},202)
        if p.path in {'/api/threads/hide','/api/threads/unhide'}:
            if not self.authed():return self.json({'error':'feishu_login_required'},401)
            data=json.loads(body or b'{}'); thread_id=str(data.get('threadId') or '').strip()
            if not thread_id:return self.json({'error':'missing_thread_id'},400)
            if p.path.endswith('/hide'):db.execute('INSERT OR REPLACE INTO hidden_threads(thread_id,hidden_at) VALUES(?,?)',(thread_id,int(time.time())))
            else:db.execute('DELETE FROM hidden_threads WHERE thread_id=?',(thread_id,))
            db.commit(); return self.json({'ok':True,'hidden':p.path.endswith('/hide')})
        if p.path=='/api/auth/feishu':
            code=json.loads(body).get('code',''); identity=self.exchange_feishu_code(code)
            if identity.get('open_id')!=OWNER:return self.json({'error':'owner_mismatch'},403)
            return self.json({'ok':True},cookie=self.new_session())
        self.send_error(404)
    def log_message(self,*_):pass
import history_store
DB_LOCK=__import__('threading').RLock()
HISTORY_LOCK=DB_LOCK
history_store.initialize(db)
ThreadingHTTPServer(('127.0.0.1',8780),H).serve_forever()
