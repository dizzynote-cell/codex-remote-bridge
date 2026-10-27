# SPDX-License-Identifier: MIT
"""Authenticated HTTP relay; the Windows agent only makes outbound HTTPS calls."""
from __future__ import annotations

import base64
import binascii
import json
import hashlib
import mimetypes
from pathlib import Path
from dsh_snapshots import DshSnapshots
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qs, quote, unquote, urlsplit

MAX_BODY = 45 * 1024 * 1024
MAX_RESULT = 32 * 1024 * 1024
MAX_MEMORY = 96 * 1024 * 1024
RESPONSE_HEADERS = {'content-type', 'content-disposition', 'content-language', 'location',
                    'x-content-type-options', 'referrer-policy', 'service-worker-allowed'}


class DshGateway:
    def __init__(self, token='', public_origin='', timeout=165, snapshot_path=None, web_root=None):
        self.snapshots = DshSnapshots(snapshot_path) if snapshot_path else None
        self.web_root = Path(web_root) if web_root else None
        self.token = token
        parsed = urlsplit(public_origin)
        self.origin = f'{parsed.scheme}://{parsed.netloc}' if parsed.netloc else ''
        self.host = parsed.netloc
        self.timeout = timeout
        self.changed = threading.Condition()
        self.jobs = OrderedDict()
        self.last_seen = 0.0
        self.memory = 0

    @property
    def online(self):
        with self.changed:
            return bool(self.host and len(self.token) >= 32 and time.monotonic() - self.last_seen < 45)

    def providers(self):
        return {'providers': [
            {'id': 'codex', 'name': 'Codex', 'url': '/', 'online': True},
            {'id': 'deepseek-harness', 'name': 'DeepSeek Harness', 'url': '/dsh/', 'online': self.online, 'cached': bool(self.snapshots and self.snapshots.available)},
        ]}

    def authorized(self, headers):
        return len(self.token) >= 32 and secrets.compare_digest(
            headers.get('Authorization', ''), 'Bearer ' + self.token)

    def poll(self, wait=20):
        deadline = time.monotonic() + min(20, max(0, wait))
        with self.changed:
            self.last_seen = time.monotonic()
            while True:
                now = time.monotonic()
                for key, job in self.jobs.items():
                    if not job['claimed'] and job['deadline'] > now:
                        job['claimed'] = True
                        self.last_seen = now
                        return {'id': key, **job['request']}
                if now >= deadline:
                    self.last_seen = now
                    return None
                self.changed.wait(deadline - now)

    def complete(self, payload):
        key = payload.get('id')
        status = payload.get('status')
        if not isinstance(key, str) or not isinstance(status, int) or not 200 <= status <= 599:
            raise ValueError('invalid relay response')
        try:
            body = base64.b64decode(payload.get('body', ''), validate=True)
        except (ValueError, TypeError, binascii.Error):
            raise ValueError('invalid relay response body') from None
        if len(body) > MAX_RESULT:
            raise ValueError('relay response too large')
        headers = {}
        for name, value in (payload.get('headers') or {}).items():
            if str(name).lower() in RESPONSE_HEADERS and isinstance(value, str) and not any(c in value for c in '\r\n'):
                headers[str(name).lower()] = value
        with self.changed:
            job = self.jobs.get(key)
            if not job or not job['claimed'] or job['deadline'] < time.monotonic():
                return False
            if job['result'] is not None:
                return True
            if self.memory + len(body) > MAX_MEMORY:
                status, headers, body = 503, {}, b'{"error":"relay_capacity"}'
            self.memory += len(body)
            job['result'] = (status, headers, body)
            self.changed.notify_all()
            return True

    def forward(self, method, path, headers, body=b''):
        decoded = unquote(urlsplit(path).path)
        if not decoded.startswith('/dsh/') or '\\' in decoded or any(x in {'.', '..'} for x in decoded.split('/')):
            return 400, {}, b'{"error":"invalid_dsh_path"}'
        if method not in {'GET', 'HEAD', 'POST'} or len(body) > MAX_BODY:
            return 413, {}, b'{"error":"request_not_supported"}'
        if not self.online:
            return 503, {}, json.dumps({'error': 'dsh_offline', 'message': 'DeepSeek Harness 主机暂时离线'}, ensure_ascii=False).encode()
        safe_headers = {name: headers[name] for name in ['Accept', 'Content-Type', 'Range'] if headers.get(name)}
        safe_headers['Host'] = self.host
        if headers.get('Origin'):
            safe_headers['Origin'] = self.origin
        safe_headers['Sec-Fetch-Site'] = 'same-origin'
        request = {'method': method, 'path': path, 'headers': safe_headers,
                   'body': base64.b64encode(body).decode('ascii')}
        size = len(request['body'])
        key = secrets.token_urlsafe(24)
        with self.changed:
            if len(self.jobs) >= 32 or self.memory + size > MAX_MEMORY:
                return 503, {}, b'{"error":"relay_busy"}'
            job = {'request': request, 'claimed': False, 'result': None,
                   'deadline': time.monotonic() + self.timeout}
            self.jobs[key] = job
            self.memory += size
            self.changed.notify_all()
            try:
                while job['result'] is None:
                    remaining = job['deadline'] - time.monotonic()
                    if remaining <= 0:
                        return 504, {}, json.dumps({'error': 'dsh_timeout', 'message':
                            '请求结果暂未确认，请先查看历史；不要重复发送相同指令。'}, ensure_ascii=False).encode()
                    self.changed.wait(remaining)
                status, response_headers, response = job['result']
                if urlsplit(path).path == '/dsh/api/bridge-info' and status == 200:
                    try:
                        info = json.loads(response)
                        for target in info.get('logoMenu', {}).get('targets', []):
                            if target.get('providerId') == 'codex':
                                target.update(url='/', enabled=True, reason=None)
                        response = json.dumps(info, ensure_ascii=False).encode()
                    except (ValueError, TypeError, AttributeError):
                        pass
                return status, response_headers, response
            finally:
                self.memory -= size + (len(job['result'][2]) if job['result'] else 0)
                self.jobs.pop(key, None)

    @staticmethod
    def _reply(handler, status, body, headers=None):
        handler.send_response(status)
        values = {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store',
                  'x-content-type-options': 'nosniff', **(headers or {})}
        for name, value in values.items():
            handler.send_header(name, value)
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        if handler.command != 'HEAD':
            handler.wfile.write(body)

    @staticmethod
    def _body(handler, limit):
        if handler.headers.get('Transfer-Encoding'):
            raise ValueError('unsupported transfer encoding')
        try:
            length = int(handler.headers.get('Content-Length', '0'))
        except ValueError:
            raise ValueError('invalid content length') from None
        if not 0 <= length <= limit:
            raise ValueError('request too large')
        handler.connection.settimeout(45)
        body = handler.rfile.read(length)
        if len(body) != length:
            raise ValueError('incomplete request')
        return body

    def handle(self, handler):
        path = urlsplit(handler.path).path
        if path.startswith('/api/device/dsh-relay/'):
            if not self.authorized(handler.headers):
                handler.close_connection = True
                handler.json({'error': 'unauthorized'}, 401)
                return True
            try:
                if handler.command == 'POST' and path.endswith('/snapshot') and self.snapshots:
                    payload=json.loads(self._body(handler, MAX_RESULT))
                    result=self.snapshots.ingest(payload)
                    with self.changed:self.last_seen=time.monotonic()
                elif handler.command == 'GET' and path.endswith('/snapshot-requests') and self.snapshots:
                    with self.changed:self.last_seen=time.monotonic()
                    result={'historyRequests':self.snapshots.requests()}
                elif handler.command == 'GET' and path.endswith('/poll'):
                    result = {'request': self.poll()}
                elif handler.command == 'GET' and path.endswith('/heartbeat'):
                    with self.changed:
                        self.last_seen = time.monotonic()
                    result = {'ok': True}
                elif handler.command == 'GET' and path.endswith('/probe'):
                    # Transport diagnostic only; cannot choose a path or execute a model task.
                    status, headers, body = self.forward('GET', '/dsh/api/bridge-info', {})
                    self._reply(handler, status, body, headers)
                    return True
                elif handler.command == 'POST' and path.endswith('/result'):
                    result = {'accepted': self.complete(json.loads(self._body(handler, 48 * 1024 * 1024)))}
                else:
                    self._reply(handler, 404, b'{"error":"unknown_relay_endpoint"}')
                    return True
                self._reply(handler, 200, json.dumps(result).encode())
            except (ValueError, TypeError, AttributeError):
                handler.close_connection = True
                self._reply(handler, 400, b'{"error":"invalid_relay_payload"}')
            return True
        if path == '/api/providers':
            if not handler.authed():
                handler.json({'error': 'unauthorized'}, 401)
            else:
                handler.json(self.providers())
            return True
        if path != '/dsh' and not path.startswith('/dsh/'):
            return False
        if not handler.authed():
            handler.close_connection = True
            if handler.command == 'GET' and path in {'/dsh', '/dsh/'}:
                handler.redirect('/api/auth/oauth/start?return_to=' + quote(handler.path, safe=''))
            else:
                handler.json({'error': 'unauthorized'}, 401)
            return True
        if path == '/dsh':
            handler.redirect('/dsh/')
            return True
        if handler.command in {'GET','HEAD'} and self.web_root and not path.startswith('/dsh/api/'):
            target=(self.web_root/('index.html' if path=='/dsh/' else unquote(path[len('/dsh/'):]))).resolve()
            if self.web_root.resolve() not in target.parents or not target.is_file():
                self._reply(handler,404,b'{"error":"static_not_found"}');return True
            body=target.read_bytes()
            if target.name=='index.html':
                body=body.replace(b'<!-- bridge-boot -->',b'<script>window.DSH_BRIDGE={basePath:"/dsh/",remote:true};</script>')
            digest='"'+hashlib.sha256(body).hexdigest()+'"'
            cache='no-store' if target.suffix=='.html' else ('no-cache' if target.name=='sw.js' else 'private, max-age=300')
            status=304 if handler.headers.get('If-None-Match')==digest and target.suffix!='.html' else 200
            self._reply(handler,status,b'' if status==304 else body,{'content-type':mimetypes.guess_type(target.name)[0] or 'application/octet-stream','cache-control':cache,'etag':digest})
            return True
        if handler.command in {'GET','HEAD'} and self.snapshots and self.snapshots.available and path.startswith('/dsh/api/'):
            try:value=self.snapshots.read(handler.path,self.online)
            except (ValueError,TypeError):self._reply(handler,400,b'{"error":"invalid_snapshot_request"}');return True
            if value is not None:
                self._reply(handler,200,json.dumps(value,ensure_ascii=False).encode());return True
        if path == '/dsh/' and handler.command == 'GET' and not self.online:
            self._reply(handler, 503, ('<!doctype html><meta charset="utf-8"><title>DeepSeek Harness 离线</title>'
                '<body style="background:#10141c;color:#eef2f7;font:18px sans-serif;padding:40px">'
                '<h1>DeepSeek Harness 主机暂时离线</h1><p>请确认主力电脑和 DSH 桥正在运行。</p>'
                '<p><a style="color:#8ca4ff" href="/?provider=codex">返回 Codex</a> · '
                '<a style="color:#8ca4ff" href="/dsh/">重试连接</a></p></body>').encode(),
                {'content-type': 'text/html; charset=utf-8'})
            return True
        if handler.command == 'POST':
            origin = handler.headers.get('Origin')
            site = handler.headers.get('Sec-Fetch-Site')
            if (origin and origin != self.origin) or (site and site not in {'same-origin', 'none'}):
                handler.close_connection = True
                handler.json({'error': 'cross_origin'}, 403)
                return True
        try:
            body = self._body(handler, MAX_BODY) if handler.command == 'POST' else b''
            status, headers, response = self.forward(handler.command, handler.path, handler.headers, body)
            if self.snapshots and handler.command=='GET' and status==200:
                try:self.snapshots.cache_control(handler.path,json.loads(response))
                except (ValueError,TypeError):pass
            if self.snapshots and handler.command=='POST' and 200<=status<300:
                try:self.snapshots.confirmed_write(handler.path,json.loads(body or b'{}'),json.loads(response or b'{}'))
                except (ValueError,TypeError,AttributeError):pass
            self._reply(handler, status, response, headers)
        except (ValueError, TimeoutError, OSError):
            handler.close_connection = True
            self._reply(handler, 400, b'{"error":"invalid_dsh_request"}')
        return True
