"""Owner browser sessions: hashed tokens, fixed expiry and explicit revocation."""
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

TTL = {'temporary': 3600, 'personal': 7 * 86400}


class BrowserSessions:
    def __init__(self, path, clock=time.time, owner=""):
        self.clock = clock
        self.lock = threading.RLock()
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            descriptor=os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('''CREATE TABLE IF NOT EXISTS browser_sessions(
            id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, created REAL NOT NULL,
            expires REAL NOT NULL, last_seen REAL NOT NULL, mode TEXT NOT NULL,
            chosen INTEGER NOT NULL, label TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)''')
        self.db.execute('CREATE TABLE IF NOT EXISTS session_policy(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        fingerprint=self.digest(owner)
        saved=self.db.execute("SELECT value FROM session_policy WHERE key='owner'").fetchone()
        if saved is not None and saved[0]!=fingerprint:
            self.db.execute('DELETE FROM browser_sessions')
        self.db.execute("INSERT OR REPLACE INTO session_policy VALUES('owner',?)", (fingerprint,))
        self.db.commit()
        if str(path) != ':memory:':
            try: os.chmod(path, 0o600)
            except OSError: pass

    @staticmethod
    def digest(token):
        return hashlib.sha256(str(token).encode()).hexdigest()

    @staticmethod
    def device_label(user_agent):
        text = str(user_agent)[:1024].lower()
        kind = '手机/平板' if any(k in text for k in ('android', 'iphone', 'ipad', 'mobile')) else '电脑/其他设备'
        browser = next((name for key, name in [('edg','Edge'),('firefox','Firefox'),('chrome','Chrome'),('safari','Safari')] if key in text), '浏览器')
        return kind + ' · ' + browser

    @staticmethod
    def public(row):
        return {'id':row['id'], 'createdAt':row['created'], 'expiresAt':row['expires'],
                'lastSeenAt':row['last_seen'], 'mode':row['mode'],
                'deviceChoiceRequired':not bool(row['chosen']), 'name':row['label']}

    def create(self, user_agent=''):
        now = self.clock()
        token, identity = secrets.token_urlsafe(32), secrets.token_urlsafe(18)
        with self.lock:
            self.db.execute('DELETE FROM browser_sessions WHERE expires<=? OR revoked=1', (now,))
            if self.db.execute('SELECT count(*) FROM browser_sessions').fetchone()[0] >= 256:
                raise ValueError('登录设备数量过多，请先撤销旧设备')
            self.db.execute('INSERT INTO browser_sessions VALUES(?,?,?,?,?,?,?,?,0)',
                            (identity,self.digest(token),now,now+TTL['temporary'],now,'temporary',0,self.device_label(user_agent)))
            self.db.commit()
            return token, self.get(token)

    def get(self, token):
        if not token or len(str(token)) > 512: return None
        now = self.clock()
        with self.lock:
            row = self.db.execute('SELECT * FROM browser_sessions WHERE token_hash=? AND revoked=0 AND expires>?', (self.digest(token),now)).fetchone()
            if row is None: return None
            if now - row['last_seen'] >= 30:
                self.db.execute('UPDATE browser_sessions SET last_seen=? WHERE id=?', (now,row['id']))
                self.db.commit()
                row = dict(row, last_seen=now)
            return self.public(row)

    def choose(self, token, mode, name=''):
        if mode not in TTL: raise ValueError('请选择个人设备或临时设备')
        if not isinstance(name, str): raise ValueError('设备名称无效')
        name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip()[:60]
        with self.lock:
            current = self.get(token)
            if not current: raise PermissionError('登录已失效')
            if not current['deviceChoiceRequired']: raise ValueError('设备属性已经设置；如需更改，请退出后重新登录')
            replacement = secrets.token_urlsafe(32)
            self.db.execute('UPDATE browser_sessions SET token_hash=?, mode=?, chosen=1, expires=?, label=? WHERE id=?',
                            (self.digest(replacement),mode,current['createdAt']+TTL[mode],name or current['name'],current['id']))
            self.db.commit()
            return replacement, self.get(replacement)

    def list(self, token):
        with self.lock:
            current = self.get(token)
            if not current: raise PermissionError('登录已失效')
            rows = self.db.execute('SELECT * FROM browser_sessions WHERE revoked=0 AND expires>? ORDER BY last_seen DESC', (self.clock(),)).fetchall()
            return [dict(self.public(row), current=row['id']==current['id']) for row in rows]

    def revoke(self, token, identity=None, others=False):
        with self.lock:
            current = self.get(token)
            if not current: raise PermissionError('登录已失效')
            if others:
                self.db.execute('UPDATE browser_sessions SET revoked=1 WHERE id<>?', (current['id'],))
            else:
                self.db.execute('UPDATE browser_sessions SET revoked=1 WHERE id=?', (identity or current['id'],))
            self.db.commit()
            return not others and (not identity or identity==current['id'])

    def cookie(self, token, session):
        age = max(0, int(session['expiresAt'] - self.clock()))
        return f'codex_history={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={age}'

    @staticmethod
    def clear_cookie():
        return 'codex_history=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0'

    def close(self):
        self.db.close()
