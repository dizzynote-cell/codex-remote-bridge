# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge

import hashlib, json, sqlite3, sys, time

DB='/opt/codex-history/data/history.db'
def text_value(value):
    if value is None:return None
    if isinstance(value,(str,int,float,bool)):return str(value)
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))

data=json.load(sys.stdin); now=int(time.time()); db=sqlite3.connect(DB)
db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA busy_timeout=5000')
for t in data.get('threads',[]):
    raw=json.dumps(t,ensure_ascii=False,separators=(',',':')); h=hashlib.sha256(raw.encode()).hexdigest()
    db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,cwd=excluded.cwd,status=excluded.status,preview=excluded.preview,updated_at=excluded.updated_at,payload=excluded.payload,content_hash=excluded.content_hash,synced_at=excluded.synced_at',(str(t['id']),text_value(t.get('name')),text_value(t.get('cwd')),text_value(t.get('status')),text_value(t.get('preview')),text_value(t.get('updatedAt')),raw,h,now))
db.execute("INSERT INTO meta VALUES('heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(now),))
db.execute("DELETE FROM meta WHERE key='service_notice'")
if data.get('quota') is not None:
    quota=dict(data['quota']); quota['syncedAt']=now
    db.execute("INSERT INTO meta VALUES('quota',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(quota),))
db.commit(); print(json.dumps({'ok':True,'count':len(data.get('threads',[]))}))
