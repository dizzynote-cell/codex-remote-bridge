"""Bounded live snapshots and explicitly requested historical windows."""
import hashlib
import json
import time
import uuid
from thread_payload import for_web


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS source_catalog_members(thread_id TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS source_retired_threads(thread_id TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS history_requests(
      thread_id TEXT PRIMARY KEY, request_id TEXT, turn_limit TEXT, requested_at REAL, viewed_at REAL,
      completed_id TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS history_windows(
      thread_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    ''')
    db.commit()


def request(db, thread_id, limit, refresh=False, missing=False):
    now = time.time()
    row = db.execute('SELECT request_id,turn_limit,requested_at,completed_id FROM history_requests WHERE thread_id=?', (thread_id,)).fetchone()
    pending = row and row[0] != row[3] and now-row[2] < 120
    if not row or (not pending and refresh and (missing or now-row[2]>3)) or (pending and str(limit) != row[1]):
        db.execute('INSERT INTO history_requests VALUES(?,?,?,?,?,NULL,NULL) ON CONFLICT(thread_id) DO UPDATE SET request_id=excluded.request_id,turn_limit=excluded.turn_limit,requested_at=excluded.requested_at,viewed_at=excluded.viewed_at,error=NULL',
                   (thread_id, uuid.uuid4().hex, str(limit), now, now))
    else:
        db.execute('UPDATE history_requests SET viewed_at=? WHERE thread_id=?', (now, thread_id))
    db.commit()


def interests(db):
    now = time.time()
    return [dict(zip(('threadId','requestId','turnLimit','requestedAt','viewedAt','completedId'), row))
            for row in db.execute('SELECT thread_id,request_id,turn_limit,requested_at,viewed_at,completed_id FROM history_requests WHERE viewed_at>? ORDER BY viewed_at DESC', (now-1800,)).fetchall()]


def reconcile_catalog(db, catalog):
    """Retire cached entries reversibly; never delete history or desktop data."""
    if not isinstance(catalog, dict) or catalog.get('version') != 1 or catalog.get('complete') is not True:
        return False
    ids, captured = catalog.get('ids'), catalog.get('capturedAt')
    if (not isinstance(ids, list) or len(ids) > 100000 or
            any(not isinstance(tid, str) or not tid or len(tid) > 200 for tid in ids) or
            not isinstance(captured, (int, float)) or isinstance(captured, bool) or not 0 < captured < float('inf')):
        return False
    previous = db.execute("SELECT value FROM meta WHERE key='source_catalog_at'").fetchone()
    if previous and captured <= float(previous[0]):
        return False
    db.execute('DELETE FROM source_catalog_members')
    db.executemany('INSERT OR IGNORE INTO source_catalog_members VALUES(?)', ((tid,) for tid in ids))
    db.execute('INSERT OR IGNORE INTO source_retired_threads SELECT id FROM threads WHERE id NOT IN (SELECT thread_id FROM source_catalog_members)')
    db.execute('DELETE FROM source_retired_threads WHERE thread_id IN (SELECT thread_id FROM source_catalog_members)')
    db.execute("INSERT INTO meta VALUES('source_catalog_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(captured),))
    return True


def retired(db, thread_id):
    return db.execute('SELECT 1 FROM source_retired_threads WHERE thread_id=?', (thread_id,)).fetchone() is not None


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
        if request_id and len(t.get('turns') or []) > 6:
            db.execute('INSERT INTO history_windows VALUES(?,?) ON CONFLICT(thread_id) DO UPDATE SET payload=excluded.payload', (t['id'],json.dumps(t,ensure_ascii=False)))
        if request_id:
            db.execute('UPDATE history_requests SET completed_id=?,error=NULL WHERE thread_id=? AND request_id=?', (request_id,t['id'],request_id))
        t['bridgeHasMoreTurns'] = more_turns(t) or len(t.get('turns') or []) > 6
        t['turns'] = (t.get('turns') or [])[-6:]
        raw = json.dumps(t,ensure_ascii=False,separators=(',',':'))
        db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,cwd=excluded.cwd,status=excluded.status,preview=excluded.preview,updated_at=excluded.updated_at,payload=excluded.payload,content_hash=excluded.content_hash,synced_at=excluded.synced_at',
                   (t['id'],t.get('name'),t.get('cwd'),json.dumps(t.get('status')),t.get('preview'),str(t.get('updatedAt') or 0),raw,hashlib.sha256(raw.encode()).hexdigest(),now))
    reconcile_catalog(db, data.get('threadCatalog'))
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


def known_total(thread):
    value = thread.get('bridgeTotalTurns', len(thread.get('turns') or []))
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def more_turns(thread):
    total = known_total(thread)
    return bool(thread.get('bridgeHasMoreTurns')) or (total is not None and total > len(thread.get('turns') or []))


def read(db, thread_id, requested, force=False):
    if retired(db, thread_id):
        return None
    row = db.execute('SELECT payload,synced_at,name,cwd,updated_at FROM threads WHERE id=?', (thread_id,)).fetchone()
    if not row:
        return None
    t = json.loads(row[0]); live = t.get('turns') or []
    t.update(name=row[2], cwd=row[3], updatedAt=row[4])
    limit = None if requested == 'all' else max(6, min(int(requested), 100000))
    turns, total, has_more = live, known_total(t), more_turns(t)
    if limit is None or limit > 6:
        window = db.execute('SELECT payload FROM history_windows WHERE thread_id=?', (thread_id,)).fetchone()
        if window:
            cached = json.loads(window[0]); old = cached.get('turns') or []
            live_ids = {turn['id'] for turn in live}
            overlap = next((index for index, turn in enumerate(old) if turn['id'] in live_ids), None)
            # No overlap means the old window cannot prove continuity. Re-fetch
            # it on demand rather than displaying a stale gap or reverted tail.
            if overlap is not None:
                turns = old[:overlap] + live
                complete = not more_turns(cached)
                has_more = not complete
                total = len(turns) if complete else None
    missing = row[1] == 0 or (has_more and (limit is None or len(turns) < limit))
    request(db, thread_id, requested, refresh=force or missing or time.time()-row[1] > 30, missing=missing)
    state = db.execute('SELECT request_id,completed_id,error FROM history_requests WHERE thread_id=?', (thread_id,)).fetchone()
    t['turns'] = turns if limit is None else turns[-limit:]
    t['bridgeTotalTurns'] = total
    t['bridgeHasMoreTurns'] = has_more or len(turns) > len(t['turns'])
    t['bridgeVisibleTurns'] = len(t['turns'])
    t['bridgeSync'] = {'syncedAt':row[1], 'pending':state[0] != state[1], 'error':state[2], 'requested':requested}
    return {'thread':for_web(t)}
