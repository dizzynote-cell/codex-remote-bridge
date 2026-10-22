"""Surface retry/no-output states without treating slow tools as failures."""
import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from turn_state import status, TERMINAL

UUID = r'[0-9a-fA-F-]{36}'
THREAD = re.compile(r'(?:thread_id|thread\.id|conversation\.id)=["\']?(' + UUID + r')')
TURN = re.compile(r'(?:turn_id|turn\.id)=["\']?(' + UUID + r')')
NETWORK = re.compile(r'request failed|error sending request|stream disconnected|connection reset|connect(?:ion)? timed? ?out|tls handshake|failed to connect', re.I)
TOOLS = {'commandExecution', 'mcpToolCall', 'dynamicToolCall', 'imageGeneration'}


class TurnHealth:
    def __init__(self, home=None, clock=time.time):
        self.home = Path(home) if home else None
        self.clock = clock
        self.lock = threading.RLock()
        self.states = {}
        self.failures = {}
        self.next_log_check = 0

    def retry(self, thread_id, turn_id, at=None):
        if thread_id and turn_id:
            with self.lock:
                self.failures[(thread_id, turn_id)] = self.clock() if at is None else at
                if len(self.failures) > 128:
                    self.failures.pop(next(iter(self.failures)))

    def notification(self, method, params):
        if method == 'error' and params.get('willRetry'):
            self.retry(params.get('threadId'), params.get('turnId'))

    def stderr(self, line):
        # Do not retain or expose log bodies, URLs, request headers or credentials.
        if not NETWORK.search(line):
            return
        thread, turn = THREAD.search(line), TURN.search(line)
        if thread and turn:
            self.retry(thread[1], turn[1])

    def _logs(self, now):
        if not self.home or now < self.next_log_check:
            return
        self.next_log_check = now + 15
        self.failures = {key: stamp for key, stamp in self.failures.items() if now-stamp < 180}
        try:
            files = list(self.home.glob('logs_*.sqlite'))
            if not files:
                return
            path = max(files, key=lambda p: p.stat().st_mtime_ns)
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.15)) as db:
                rows = db.execute('''SELECT ts,feedback_log_body FROM logs
                    WHERE id>(SELECT COALESCE(MAX(id),0)-5000 FROM logs) AND ts>?
                    AND target IN ('codex_http_client::client','codex_core::client')
                    ORDER BY id DESC LIMIT 80''', (now-180,)).fetchall()
            for stamp, body in rows:
                if not body or not NETWORK.search(body):
                    continue
                thread, turn = THREAD.search(body), TURN.search(body)
                if thread and turn:
                    key = (thread[1], turn[1])
                    self.failures[key] = max(stamp, self.failures.get(key, 0))
        except (OSError, ValueError, sqlite3.Error):
            pass  # Diagnostic availability never blocks or fails a chat request.

    def snapshot(self, thread, waiting=False):
        turns = thread.get('turns') or []
        latest = turns[-1] if turns else None
        if not latest or status(latest) in TERMINAL:
            return None
        tid, turn_id = thread.get('id'), latest.get('id')
        if not tid or not turn_id:
            return None
        with self.lock:
            now = self.clock()
            self._logs(now)
            items = latest.get('items') or []
            signature = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            state = self.states.get(tid)
            if not state or state['turn'] != turn_id:
                started = latest.get('startedAt')
                started = float(started) if isinstance(started, (int, float)) else now
                if started > 100000000000: started /= 1000
                # On restart, an existing output's true age is unknown. Start conservatively.
                activity = min(now, started) if not items or all(i.get('type') == 'userMessage' for i in items) else now
                state = dict(turn=turn_id, signature=signature, activity=activity)
                self.states[tid] = state
                if len(self.states) > 128:
                    self.states.pop(next(iter(self.states)))
            elif state['signature'] != signature:
                state.update(signature=signature, activity=now)
            tool_running = any(i.get('type') in TOOLS and status(i) in {'inProgress','in_progress','running'} for i in items)
            if waiting or tool_running:
                return None
            failure = self.failures.get((tid, turn_id), 0)
            if failure >= state['activity'] and now-failure < 180:
                return dict(kind='retrying', turnId=turn_id, updatedAt=failure,
                            message='连接模型服务暂未成功，Codex 正在重试；任务尚未结束，请勿重复发送。')
            idle = max(0, int(now-state['activity']))
            if idle >= 120:
                return dict(kind='no_progress', turnId=turn_id, idleSeconds=idle,
                            message=f'已约 {idle//60} 分钟没有收到新输出；任务仍在运行，暂不能确定原因，请勿重复发送。')
            return None
