# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

import time,uuid
def initialize(db):db.execute('CREATE TABLE IF NOT EXISTS thread_organizer(thread_id TEXT PRIMARY KEY,name TEXT,pinned INTEGER NOT NULL DEFAULT 0,project TEXT,updated REAL NOT NULL)');db.commit()
def valid_id(value):
    try:uuid.UUID(str(value).removeprefix('urn:uuid:'));return True
    except (ValueError,AttributeError,TypeError):return False
def snapshot(db):
    rows=db.execute('SELECT thread_id,name,pinned,project,updated FROM thread_organizer').fetchall();return {'threads':{r[0]:{'name':r[1],'pinned':bool(r[2]),'project':r[3],'updated':r[4]} for r in rows}}
def update(db,payload):
    thread_id=str(payload.get('threadId') or '')
    if not valid_id(thread_id):raise ValueError('invalid_thread_id')
    old=db.execute('SELECT name,pinned,project FROM thread_organizer WHERE thread_id=?',(thread_id,)).fetchone() or (None,0,None)
    name=old[0] if 'name' not in payload else str(payload.get('name') or '').strip()
    if 'name' in payload and (not name or len(name)>100):raise ValueError('invalid_name')
    pinned=old[1] if 'pinned' not in payload else int(bool(payload['pinned']))
    project=old[2] if 'project' not in payload else str(payload.get('project') or '').strip() or None
    if project and len(project)>500:raise ValueError('invalid_project')
    now=time.time();db.execute('INSERT OR REPLACE INTO thread_organizer VALUES(?,?,?,?,?)',(thread_id,name,pinned,project,now));db.commit();return {'name':name,'pinned':bool(pinned),'project':project,'updated':now}
def merge(db,incoming):
    incoming=incoming.get('threads',incoming) if isinstance(incoming,dict) else {}
    if not isinstance(incoming,dict):return snapshot(db)
    for thread_id,item in incoming.items():
        if not valid_id(thread_id) or not isinstance(item,dict):continue
        updated=float(item.get('updated') or 0);old=db.execute('SELECT updated FROM thread_organizer WHERE thread_id=?',(thread_id,)).fetchone()
        if old and float(old[0])>=updated:continue
        name=str(item.get('name') or '').strip() or None;project=str(item.get('project') or '').strip() or None
        if name and len(name)>100 or project and len(project)>500:continue
        db.execute('INSERT OR REPLACE INTO thread_organizer VALUES(?,?,?,?,?)',(thread_id,name,int(bool(item.get('pinned'))),project,updated))
    db.commit();return snapshot(db)


