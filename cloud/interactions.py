# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

"""Authenticated relay for human replies; the PC remains the request authority."""
import json
import time


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS interaction_answers(session TEXT NOT NULL, request_id TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(session,request_id))')
    db.commit()


def load(db):
    row = db.execute("SELECT value FROM meta WHERE key='interactions'").fetchone()
    return json.loads(row[0]) if row else {"session": "", "startedAt": 0, "revision": -1, "requests": [], "syncedAt": 0}


def read(db):
    data = load(db)
    data['available'] = time.time() - data.get('syncedAt', 0) < 20
    queued = {row[0] for row in db.execute('SELECT request_id FROM interaction_answers WHERE session=?', (data['session'],))}
    for item in data.get('requests', []):
        if item['id'] in queued and item['status'] == 'pending': item['delivery'] = 'queued'
    return data


def submit(db, payload):
    if not isinstance(payload, dict) or len(json.dumps(payload)) > 64000:
        raise ValueError('回答内容过大或格式错误')
    data = read(db)
    if not data['available']: raise ValueError('主力 PC 暂时未连接，请稍后再试')
    item = next((r for r in data['requests'] if r['id'] == payload.get('id')), None)
    if not item or payload.get('session') != data['session'] or any(payload.get(k, '') != item.get(k, '') for k in ('threadId', 'turnId')):
        raise ValueError('请求已失效，请刷新')
    if item['status'] != 'pending': raise ValueError('请求已经处理')
    if payload.get('action') not in item['actions']: raise ValueError('不支持这个回答动作')
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    old = db.execute('SELECT payload FROM interaction_answers WHERE session=? AND request_id=?', (data['session'], item['id'])).fetchone()
    if old and old[0] != body: raise ValueError('此请求已有回答等待主力 PC 接收')
    db.execute('INSERT OR IGNORE INTO interaction_answers VALUES(?,?,?,?)', (data['session'], item['id'], body, time.time()))
    db.commit()
    return {'ok': True, 'status': 'queued'}


def exchange(db, payload):
    snap = payload.get('snapshot')
    if not isinstance(snap, dict) or not isinstance(snap.get('requests'), list) or not isinstance(snap.get('startedAt'), (float, int)) or not isinstance(snap.get('revision'), int):
        raise ValueError('invalid_interaction_snapshot')
    if not isinstance(snap.get('session'), str) or len(snap['session']) != 32 or len(snap['requests']) > 500:
        raise ValueError('invalid_interaction_session')
    if len(json.dumps(snap)) > 2 * 1024 * 1024: raise ValueError('interaction_snapshot_too_large')
    old = load(db)
    if snap['startedAt'] < old.get('startedAt', 0) or (snap['session'] == old['session'] and snap['revision'] < old['revision']):
        return {'answers': []}
    # Preserve a delivery error until the next accepted answer; it is not a task failure.
    errors = {r['id']: r.get('deliveryError') for r in old.get('requests', []) if r.get('deliveryError')}
    for ack in payload.get('acks') or []:
        if ack.get('session') != snap['session']: continue
        db.execute('DELETE FROM interaction_answers WHERE session=? AND request_id=?', (snap['session'], ack.get('id')))
        if ack.get('error'): errors[ack['id']] = str(ack['error'])[:300]
        else: errors.pop(ack.get('id'), None)
    data = {**snap, 'syncedAt': time.time()}
    pending = set()
    for item in data['requests']:
        if item['status'] == 'pending':
            pending.add(item['id'])
            if errors.get(item['id']): item['deliveryError'] = errors[item['id']]
    # Never replay answers into a restarted bridge or a completed turn.
    db.execute('DELETE FROM interaction_answers WHERE session<>? OR created_at<?', (snap['session'], time.time() - 300))
    for (key,) in db.execute('SELECT request_id FROM interaction_answers WHERE session=?', (snap['session'],)).fetchall():
        if key not in pending: db.execute('DELETE FROM interaction_answers WHERE session=? AND request_id=?', (snap['session'], key))
    db.execute("INSERT INTO meta VALUES('interactions',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(data, ensure_ascii=False),))
    db.commit()
    rows = db.execute('SELECT payload FROM interaction_answers WHERE session=? ORDER BY created_at LIMIT 20', (snap['session'],)).fetchall()
    return {'answers': [json.loads(row[0]) for row in rows]}
