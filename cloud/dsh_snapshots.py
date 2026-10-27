"""DSH snapshots in a provider-isolated database, using the shared history windows."""
import copy
import json
import sqlite3
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit
from pathlib import Path
import history_store

META_PATHS={'/api/balance':'balance','/api/status':'status','/api/bridge-info':'info',
            '/api/models':'models','/api/permissions':'permissions','/api/preferences':'preferences',
            '/api/voice/config':'voice','/api/thread-library':'library'}

class DshSnapshots:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(str(path),check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS threads(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,status TEXT,preview TEXT,updated_at TEXT,payload TEXT NOT NULL,content_hash TEXT NOT NULL,synced_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
        history_store.initialize(self.db)

    def meta(self,key,default=None):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self,key,value):
        self.db.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value,ensure_ascii=False)))

    def requests(self):
        with self.lock:return history_store.interests(self.db)

    def ingest(self,payload):
        if not isinstance(payload,dict) or payload.get('version')!=1:raise ValueError('invalid_snapshot_version')
        rows=payload.get('summaries')
        if rows is not None and (not isinstance(rows,list) or len(rows)>2000):raise ValueError('invalid_summaries')
        for row in (rows or [])+(payload.get('threads') or []):
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not 0<len(row['id'])<=200:raise ValueError('invalid_thread')
        if len(payload.get('threads') or [])>1:raise ValueError('one_history_per_upload')
        with self.lock,self.db:
            metadata=payload.get('metadata') or {}
            if not isinstance(metadata,dict):raise ValueError('invalid_metadata')
            for key in ['balance','status','info','models','permissions','preferences','voice','projects']:
                if key in metadata:
                    self.put(key,metadata[key]);self.put(key+':at',time.time())
            if 'library' in metadata:self.merge_library(metadata['library'])
            self.put('snapshotAt',time.time())
            if rows is not None:
                self.put('catalogIds',[r['id'] for r in rows]);self.put('catalogAt',time.time())
            # Shared module keeps a six-turn live snapshot plus requested older windows.
            result=history_store.ingest(self.db,{'summaries':rows or [],'threads':payload.get('threads') or [],'checkedThreads':payload.get('checkedThreads') or [],'historyErrors':payload.get('historyErrors') or []})
            return result

    def merge_library(self,incoming):
        incoming=incoming.get('threads',incoming) if isinstance(incoming,dict) else {}
        current=self.meta('library',{'threads':{}}).get('threads',{})
        for identity,item in incoming.items():
            if not isinstance(item,dict):continue
            if identity not in current or float(item.get('updatedAt') or 0)>=float(current[identity].get('updatedAt') or 0):
                current[identity]={key:item[key] for key in ['name','hidden','pinned','updatedAt'] if key in item}
        self.put('library',{'threads':current})

    @property
    def available(self):
        with self.lock:return self.meta('catalogIds') is not None

    def read(self,path,online):
        parsed=urlsplit(path);relative=parsed.path.removeprefix('/dsh');query=parse_qs(parsed.query)
        with self.lock:
            stamp=self.meta('catalogAt',0);sync={'syncedAt':stamp,'online':online,'stale':not online or time.time()-stamp>30}
            if relative=='/api/threads':
                limit=max(1,min(200,int((query.get('limit') or ['50'])[0])));offset=max(0,int((query.get('cursor') or ['0'])[0]))
                library=self.meta('library',{'threads':{}}).get('threads',{});ids=set(self.meta('catalogIds',[]));rows=[]
                for identity,name,cwd,status,updated in self.db.execute('SELECT id,name,cwd,status,updated_at FROM threads').fetchall():
                    if identity not in ids or library.get(identity,{}).get('hidden'):continue
                    item=library.get(identity,{})
                    rows.append({'id':identity,'name':name,'cwd':cwd,'status':json.loads(status or 'null'),'bridgeUpdatedAt':updated,'pinned':bool(item.get('pinned'))})
                rows.sort(key=lambda r:(-int(r['pinned']),-float(r['bridgeUpdatedAt'] or 0),r['id']))
                window=rows[offset:offset+limit]
                return {'threads':window,'projects':self.meta('projects',[]),'nextCursor':str(offset+limit) if offset+limit<len(rows) else None,'bridgeSync':sync}
            if relative.startswith('/api/thread/'):
                identity=unquote(relative[len('/api/thread/'):]);
                if not identity or len(identity)>200 or any(c in identity for c in '/\\') or identity in {'.','..'}:raise ValueError('invalid_thread_id')
                requested=(query.get('turnLimit') or ['6'])[0]
                result=history_store.read(self.db,identity,requested,(query.get('refresh') or ['0'])[0]=='1')
                if not result:
                    history_store.request(self.db,identity,requested,refresh=True)
                    result={'thread':{'id':identity,'turns':[],'bridgeTotalTurns':0,'bridgeSync':{'syncedAt':0,'pending':True}}}
                state=result['thread'].setdefault('bridgeSync',{});row=self.db.execute('SELECT content_hash FROM threads WHERE id=?',(identity,)).fetchone();state['contentHash']=row[0] if row else '';state.update(online=online,stale=not online or time.time()-state.get('syncedAt',0)>30)
                return result
            if relative in {'/api/models','/api/permissions'} and query.get('threadId'):
                record=self.meta('control:'+relative+':'+query['threadId'][0])
                if record and (not online or time.time()-record['at']<15):
                    value=record['value'];value['bridgeSync']=dict(sync,syncedAt=record['at']);return value
                return None
            if relative in META_PATHS:
                key=META_PATHS[relative];value=copy.deepcopy(self.meta(key))
                if value is None:
                    if key=='balance':value={'available':False,'status':'syncing','entries':[],'display':{'label':'余额待同步'}}
                    elif key=='library':value={'threads':{}}
                    elif key=='models':value={'models':[],'choices':{}}
                    elif key=='permissions':value={'options':[]}
                    else:value={}
                if isinstance(value,dict):
                    key_stamp=self.meta(key+':at',stamp)
                    sync=dict(sync,syncedAt=key_stamp,stale=not online or time.time()-key_stamp>(90 if key=='balance' else 30))
                    value['bridgeSync']=sync
                    if key=='status' and not online:value.update(mode='offline',label='本机离线 · 显示服务器快照',shortLabel='本机离线 · 历史可读')
                    if key=='balance' and sync['stale']:value['stale']=True
                    if key=='info':
                        for target in value.get('logoMenu',{}).get('targets',[]):
                            if target.get('providerId')=='codex':target.update(url='/',enabled=True,reason=None)
                return value
            return None

    def cache_control(self,path,value):
        parsed=urlsplit(path);relative=parsed.path.removeprefix('/dsh');query=parse_qs(parsed.query)
        if relative not in {'/api/models','/api/permissions'} or not query.get('threadId'):return
        with self.lock:
            self.put('control:'+relative+':'+query['threadId'][0],{'at':time.time(),'value':value});self.db.commit()

    def confirmed_write(self,path,request,response):
        relative=urlsplit(path).path.removeprefix('/dsh')
        with self.lock:
            if relative=='/api/thread-library' and isinstance(response.get('thread'),dict):
                self.merge_library({request.get('threadId'):response['thread']})
            elif relative=='/api/preferences':self.put('preferences',response)
            if relative in {'/api/models','/api/permissions'} and not request.get('threadId') and response.get('bridgeDefault'):
                kind='models' if relative=='/api/models' else 'permissions'
                cached=self.meta(kind,{})
                cached['bridgeDefault']=response['bridgeDefault'];self.put(kind,cached);self.put(kind+':at',time.time())
            if relative in {'/api/models','/api/permissions'}:
                key='control:'+relative+':'+str(request.get('threadId') or '')
                self.db.execute('DELETE FROM meta WHERE key=?',(key,))
            self.db.commit()

    def close(self):self.db.close()
