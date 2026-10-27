"""Relay isolation and authentication with synthetic traffic only."""
import base64
import importlib.util
import io
import json
import threading
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('gateway_under_test', Path(__file__).resolve().parents[1] / 'cloud/dsh_gateway.py')
gateway_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway_module)
DshGateway = gateway_module.DshGateway


class Handler:
    def __init__(self, path, method='GET', authed=False, headers=None, body=b''):
        self.path, self.command = path, method
        self.headers, self.wfile, self.rfile = headers or {}, io.BytesIO(), io.BytesIO(body)
        self.is_authed, self.close_connection = authed, False
        self.connection = type('Socket', (), {'settimeout': lambda *_: None})()
        self.response_headers = {}
        self.status = None
    def authed(self): return self.is_authed
    def send_response(self, status): self.status = status
    def send_header(self, key, value): self.response_headers[key.lower()] = value
    def end_headers(self): pass
    def json(self, value, status=200): self.status = status; self.wfile.write(json.dumps(value).encode())
    def redirect(self, value): self.status = 302; self.response_headers['location'] = value


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = DshGateway('t' * 48, 'https://bridge.example.test', timeout=.5)

    def roundtrip(self, method='GET', path='/dsh/api/bridge-info', body=b'', response=b'{}'):
        self.gateway.poll(wait=0)
        result = []
        thread = threading.Thread(target=lambda: result.append(self.gateway.forward(method, path,
            {'Cookie': 'never-forward-this', 'Authorization': 'never-forward-this', 'Content-Type': 'application/json'}, body)))
        thread.start()
        request = self.gateway.poll(wait=1)
        self.assertIsNotNone(request)
        self.assertNotIn('Cookie', request['headers'])
        self.assertNotIn('Authorization', request['headers'])
        self.assertEqual(base64.b64decode(request['body']), body)
        payload = {'id': request['id'], 'status': 200,
                   'headers': {'Content-Type': 'application/octet-stream', 'Set-Cookie': 'must-not-forward'},
                   'body': base64.b64encode(response).decode()}
        self.assertTrue(self.gateway.complete(payload))
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.gateway.memory, 0)
        self.assertNotIn('set-cookie', result[0][1])
        return result[0]

    def test_anonymous_dsh_api_cannot_reach_the_relay(self):
        for path in ['/dsh/api/balance', '/dsh/api/local-tasks', '/api/providers']:
            h = Handler(path, method='POST' if path.endswith('local-tasks') else 'GET')
            self.assertTrue(self.gateway.handle(h)); self.assertEqual(h.status, 401)
        self.assertEqual(len(self.gateway.jobs), 0)

    def test_anonymous_page_redirects_to_existing_login(self):
        h = Handler('/dsh/'); self.gateway.handle(h)
        self.assertEqual(h.status, 302)
        self.assertTrue(h.response_headers['location'].startswith('/api/auth/oauth/start?return_to='))

    def test_worker_uses_its_own_token_and_offline_is_explicit(self):
        self.assertFalse(self.gateway.authorized({'Authorization': 'Bearer wrong'}))
        self.assertTrue(self.gateway.authorized({'Authorization': 'Bearer ' + 't' * 48}))
        self.assertEqual(self.gateway.forward('GET', '/dsh/api/balance', {})[0], 503)
        h = Handler('/dsh/', authed=True); self.gateway.handle(h)
        self.assertEqual(h.status, 503); self.assertIn(b'text/html', h.response_headers['content-type'].encode())

    def test_cross_origin_post_rejected_before_any_execution(self):
        h = Handler('/dsh/api/local-tasks', 'POST', True, {'Origin': 'https://evil.example.test'})
        self.gateway.handle(h)
        self.assertEqual(h.status, 403); self.assertEqual(len(self.gateway.jobs), 0)

    def test_binary_post_roundtrip(self):
        body = bytes(range(256)) * 10
        result = self.roundtrip('POST', '/dsh/api/local-tasks', body, body)
        self.assertEqual(result[2], body)

    def test_provider_link_is_same_origin_on_the_server(self):
        value = {'providerId': 'deepseek-harness', 'logoMenu': {'targets': [
            {'providerId': 'codex', 'url': 'http://localhost:8765/', 'enabled': False}]}}
        result = self.roundtrip(response=json.dumps(value).encode())
        target = json.loads(result[2])['logoMenu']['targets'][0]
        self.assertEqual(target['url'], '/'); self.assertTrue(target['enabled'])

    def test_path_escape_and_unknown_response_rejected(self):
        for path in ['/api/threads', '/dsh/../api/threads', '/dsh/%2e%2e/api/threads']:
            self.assertEqual(self.gateway.forward('GET', path, {})[0], 400)
        self.assertFalse(self.gateway.complete({'id': 'not-present', 'status': 200, 'body': ''}))

    def test_timeout_never_requeues_a_claimed_mutation(self):
        self.gateway.timeout = .05
        self.gateway.poll(wait=0)
        result = []
        t = threading.Thread(target=lambda: result.append(self.gateway.forward('POST', '/dsh/api/local-tasks', {}, b'{}')))
        t.start(); self.assertIsNotNone(self.gateway.poll(wait=1)); t.join(2)
        self.assertEqual(result[0][0], 504)
        self.assertEqual(self.gateway.poll(wait=0), None)
        self.assertEqual(self.gateway.memory, 0)
