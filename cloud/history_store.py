"""Bounded live snapshots and explicitly requested historical windows."""
import hashlib
import json
import time
import uuid


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS history_requests(
      thread_id TEXT PRIMARY KEY, request_id TEXT, turn_limit TEXT, requested_at REAL, viewed_at REAL,
      completed_id TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS history_windows(
      thread_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    ''')
    db.commit()


def request(db, thread_id, limit, refresh=False):
    now = time.time()
    row = db.execute('SELECT request_id,turn_limit,requested_at,completed_id FROM history_requests WHERE thread_id=?', (thread_id,)).fetchone()
    pending = row and row[0] != row[3] and now-row[2] < 120
    if not row or (not pending and refresh and now-row[2]>3) or (pending and str(limit) != row[1]):
        db.execute('INSERT INTO history_requests VALUES(?,?,?,?,?,NULL,NULL) ON CONFLICT(thread_id) DO UPDATE SET request_id=excluded.request_id,turn_limit=excluded.turn_limit,requested_at=excluded.requested_at,viewed_at=excluded.viewed_at,error=NULL',
                   (thread_id, uuid.uuid4().hex, str(limit), now, now))
    else:
        db.execute('UPDATE history_requests SET viewed_at=? WHERE thread_id=?', (now, thread_id))
    db.commit()


def interests(db):
    now = time.time()
    return [dict(zip(('threadId','requestId','turnLimit','requestedAt','viewedAt','completedId'), row))
            for row in db.execute('SELECT thread_id,request_id,turn_limit,requested_at,viewed_at,completed_id FROM history_requests WHERE viewed_at>? ORDER BY viewed_at DESC', (now-1800,)).fetchall()]


def ingest(db, data):
    now = int(time.time())
    for t in data.get('summaries', []):
        raw = json.dumps(dict(t, turns=[]), ensure_ascii=False)
        db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,cwd=excluded.cwd,status=excluded.status,preview=excluded.preview,updated_at=excluded.updated_at',
                   (t['id'],t.get('name'),t.get('cwd'),json.dumps(t.get('status')),t.get('preview'),str(t.get('updatedAt') or 0),raw,'',0))
    for incoming in data.get('threads', []):
        t = dict(incoming)
        t.setdefault('bridgeTotalTurns',len(t.get('turns') or []))
        request_id = t.pop('bridgeRequestId', None)
        # Historical windows never get overwritten by the next six-turn snapshot.
        if request_id:
            db.execute('INSERT INTO history_windows VALUES(?,?) ON CONFLICT(thread_id) DO UPDATE SET payload=excluded.payload', (t['id'],json.dumps(t,ensure_ascii=False)))
            db.execute('UPDATE history_requests SET completed_id=?,error=NULL WHERE thread_id=? AND request_id=?', (request_id,t['id'],request_id))
        t['turns'] = (t.get('turns') or [])[-6:]
        raw = json.dumps(t,ensure_ascii=False,separators=(',',':'))
        db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,cwd=excluded.cwd,status=excluded.status,preview=excluded.preview,updated_at=excluded.updated_at,payload=excluded.payload,content_hash=excluded.content_hash,synced_at=excluded.synced_at',
                   (t['id'],t.get('name'),t.get('cwd'),json.dumps(t.get('status')),t.get('preview'),str(t.get('updatedAt') or 0),raw,hashlib.sha256(raw.encode()).hexdigest(),now))
    for error in data.get('historyErrors', []):
        db.execute('UPDATE history_requests SET error=?,completed_id=request_id WHERE thread_id=? AND request_id=?', (error['message'],error['threadId'],error['requestId']))
    for thread_id in data.get('checkedThreads',[]):
        db.execute('UPDATE threads SET synced_at=? WHERE id=? AND synced_at>0',(now,thread_id))
    if data.get('quota') is not None:
        db.execute("INSERT INTO meta VALUES('quota',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(data['quota']),))
    db.execute("INSERT INTO meta VALUES('history_sync',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now),))
    db.execute("INSERT INTO meta VALUES('heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(now),))
    db.commit()
    return {'ok':True,'historyRequests':interests(db)}


def read(db, thread_id, requested, force=False):
    row = db.execute('SELECT payload,synced_at,name,cwd,updated_at FROM threads WHERE id=?', (thread_id,)).fetchone()
    if not row:
        return None
    t = json.loads(row[0]); live = t.get('turns') or []
    t.update(name=row[2],cwd=row[3],updatedAt=row[4])
    total = int(t.get('bridgeTotalTurns',len(live)))
    limit = total if requested == 'all' else max(6,min(int(requested),100000))
    turns = live
    if limit > 6:
        window = db.execute('SELECT payload FROM history_windows WHERE thread_id=?',(thread_id,)).fetchone()
        if window:
            cached = json.loads(window[0])
            old = cached.get('turns') or []
            if total-int(cached.get('bridgeTotalTurns',len(old)))>len(live):
                old = []
            current = {turn['id']:turn for turn in live}
            turns = [current.pop(turn['id'],turn) for turn in old] + list(current.values())
    missing = len(turns) < min(limit,total) or row[1] == 0
    request(db,thread_id,requested,refresh=force or missing or time.time()-row[1]>30)
    state = db.execute('SELECT request_id,completed_id,error FROM history_requests WHERE thread_id=?',(thread_id,)).fetchone()
    t['turns'] = turns[-limit:] if limit else []
    t['bridgeTotalTurns'] = total
    t['bridgeSync'] = {'syncedAt':row[1], 'pending':state[0]!=state[1], 'error':state[2], 'requested':requested}
    return {'thread':t}
