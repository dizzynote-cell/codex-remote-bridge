import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tested_browser_sessions',ROOT/'cloud/browser_sessions.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
BrowserSessions=module.BrowserSessions

class StoreTests(unittest.TestCase):
    def test_hashed_persistent_token_and_fixed_expiry(self):
        now=[1000.0]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sessions.db'
            store=BrowserSessions(path,clock=lambda:now[0])
            token,session=store.create('Mozilla Chrome Android Mobile')
            self.assertEqual(session['mode'],'temporary')
            self.assertEqual(session['expiresAt'],4600)
            self.assertTrue(session['deviceChoiceRequired'])
            self.assertNotIn(token,[value for row in store.db.execute('SELECT * FROM browser_sessions') for value in row])
            now[0]=1100;self.assertEqual(store.get(token)['expiresAt'],4600)
            store.close();store=BrowserSessions(path,clock=lambda:now[0])
            self.assertIsNotNone(store.get(token))
            now[0]=4600;self.assertIsNone(store.get(token));store.close()

    def test_choice_rotates_token_and_does_not_slide_or_trust_ua(self):
        now=[1000.0];store=BrowserSessions(':memory:',clock=lambda:now[0])
        old,_=store.create('Android Mobile')
        now[0]=1010;token,session=store.choose(old,'personal','My phone')
        self.assertIsNone(store.get(old))
        self.assertNotEqual(token,old)
        self.assertEqual(session['expiresAt'],1000+7*86400)
        self.assertFalse(session['deviceChoiceRequired'])
        with self.assertRaises(ValueError):store.choose(token,'personal')
        now[0]+=100;self.assertEqual(store.get(token)['expiresAt'],1000+7*86400)
        self.assertTrue(all(flag in store.cookie(token,session) for flag in ['HttpOnly','Secure','SameSite=Lax']))
        store.close()

    def test_changing_configured_owner_invalidates_saved_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sessions.db'
            store=BrowserSessions(path,owner='owner-a')
            token,_=store.create();store.close()
            store=BrowserSessions(path,owner='owner-b')
            self.assertIsNone(store.get(token));store.close()

    def test_remote_revocation_and_logout(self):
        store=BrowserSessions(':memory:')
        first,_=store.create();second,other=store.create();third,_=store.create()
        self.assertFalse(store.revoke(first,identity=other['id']))
        self.assertIsNone(store.get(second));self.assertIsNotNone(store.get(first))
        store.revoke(first,others=True)
        self.assertIsNone(store.get(third));self.assertIsNotNone(store.get(first))
        self.assertTrue(store.revoke(first));self.assertIsNone(store.get(first))
        with self.assertRaises(PermissionError):store.list(first)
        store.close()

from test_interactions import HttpTests as Base
import http.client,json
from http.cookies import SimpleCookie

class SessionHttpTests(Base):
    def setUp(self):
        super().setUp();self.ns.update(APP_ID='synthetic-app',CLIENT_PROJECTS_ROOT='',CLIENT_STANDALONE_DIR='')

    def test_cookie_rotation_config_and_revocation(self):
        previous=self.session_token
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('POST','/api/auth/session/device',json.dumps({'mode':'personal','name':'My device'}),{'Cookie':'codex_history='+previous,'Content-Type':'application/json','Origin':self.base})
        response=conn.getresponse();result=json.loads(response.read());self.assertEqual(response.status,200)
        cookie=SimpleCookie();cookie.load(response.getheader('Set-Cookie'));self.session_token=cookie['codex_history'].value
        self.assertNotEqual(self.session_token,previous);self.assertEqual(result['session']['mode'],'personal');conn.close()
        self.assertEqual(self.request('/api/interactions',headers={'Cookie':'codex_history='+previous})[0],401)
        status,config=self.request('/api/auth/config',headers={'Cookie':'codex_history=test-session'})
        self.assertTrue(config['authenticated']);self.assertFalse(config['session']['deviceChoiceRequired'])
        other,session=self.session_store.create()
        self.assertEqual(self.request('/api/auth/sessions/revoke',{'id':session['id']},{'Cookie':'codex_history=test-session','Origin':self.base})[0],200)
        self.assertEqual(self.request('/api/interactions',headers={'Cookie':'codex_history='+other})[0],401)
        self.assertEqual(self.request('/api/auth/session/logout',{}, {'Cookie':'codex_history=test-session','Origin':self.base})[0],200)
        self.assertEqual(self.request('/api/interactions',headers={'Cookie':'codex_history=test-session'})[0],401)

    def test_session_writes_require_auth_json_and_same_origin(self):
        for path in ['/api/auth/session/device','/api/auth/session/logout','/api/auth/sessions/revoke','/api/auth/sessions/revoke-others']:
            self.assertEqual(self.request(path,{})[0],401)
            self.assertEqual(self.request(path,{}, {'Cookie':'codex_history=test-session','Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/api/auth/session/device',{'mode':'personal'},{'Cookie':'codex_history=test-session','Host':'remote.example','Origin':'http://remote.example'})[0],403)
        self.assertIsNotNone(self.session_store.get(self.session_token))
        self.assertEqual(self.request('/api/auth/session/device',{'mode':'phone'},{'Cookie':'codex_history=test-session','Origin':self.base})[0],400)
        self.assertEqual(self.request('/api/auth/session/device',{'mode':'temporary'},{'Cookie':'codex_history=test-session','Sec-Fetch-Site':'cross-site'})[0],403)

del Base
