"""Offline protocol, relay and HTTP tests. Never launches Codex or production bridge."""
import ast
import copy
import importlib.util
import io
import json
import secrets
import sqlite3
import sys
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from rpc_interactions import Interactions, InteractionError, describe
from codex_rpc import CodexRpc
spec = importlib.util.spec_from_file_location('interaction_relay', ROOT / 'cloud/interactions.py')
relay = importlib.util.module_from_spec(spec); spec.loader.exec_module(relay)


def question(body='请选择报告语言', **kw):
    return {'id': 'language', 'header': '选择', 'question': body, **kw}


class RequestsTests(unittest.TestCase):
    def setUp(self):
        self.sent = []; self.manager = Interactions(self.sent.append)

    def add(self, method='item/tool/requestUserInput', **params):
        params = {'threadId':'thread-a', 'turnId':'turn-a', **params}
        if method == 'item/tool/requestUserInput': params.setdefault('questions', [question()])
        self.manager.request({'id': 7, 'method': method, 'params': params})
        return self.manager.snapshot()['requests'][-1]

    def answer(self, item, action='answer', **extra):
        return {k:item[k] for k in ('id','session','threadId','turnId')} | {'action':action, **extra}

    def test_web_answer_returns_to_original_rpc_id(self):
        item = self.add(); self.assertEqual(item['category'], 'web')
        self.manager.respond(self.answer(item, answers={'language':'中文'}))
        self.assertEqual(self.sent, [{'id':7,'result':{'answers':{'language':{'answers':['中文']}}}}])

    def test_pc_requests_do_not_collect_codes(self):
        for body in ('请在电脑上输入验证码', '请解锁 Windows', 'Please solve the CAPTCHA', '请扫码登录'):
            item = describe('item/tool/requestUserInput', {'questions':[question(body)]})
            self.assertEqual(item['category'], 'pc')
            self.assertNotIn('answer', item['actions'])

    def test_discussion_of_captcha_stays_web(self):
        item = describe('item/tool/requestUserInput', {'questions':[question('验证码功能选哪家服务商？')]})
        self.assertEqual(item['category'], 'web')

    def test_secret_and_mixed_questions(self):
        item = self.add(questions=[question(), {'id':'pc','header':'验证','question':'登录','isSecret':True}])
        self.manager.respond(self.answer(item, 'manual_done', answers={'language':'中文'}))
        result = self.sent[-1]['result']['answers']
        self.assertEqual(result['language']['answers'], ['中文'])
        self.assertIn('重新检查', result['pc']['answers'][0])

    def test_approval_not_confused_with_pc_operation(self):
        item = self.add('item/commandExecution/requestApproval', reason='允许检查锁屏状态吗', command='whoami')
        self.assertEqual(item['category'], 'web')
        self.manager.respond(self.answer(item,'accept'))
        self.assertEqual(self.sent[-1]['result'], {'decision':'accept'})

    def test_permissions_never_expand_scope(self):
        item = self.add('item/permissions/requestApproval', permissions={'network':{'enabled':True}})
        self.manager.respond(self.answer(item,'accept', permissions={'fileSystem':{'write':['/']}}))
        self.assertEqual(self.sent[-1]['result'], {'permissions':{'network':{'enabled':True}},'scope':'turn'})

    def test_retry_idempotency_and_conflicting_answer(self):
        item = self.add(); payload = self.answer(item, answers={'language':'中文'})
        self.manager.respond(payload); self.manager.respond(payload)
        self.assertEqual(len(self.sent),1)
        with self.assertRaises(InteractionError): self.manager.respond(self.answer(item, answers={'language':'英文'}))

    def test_session_thread_and_turn_validation(self):
        item = self.add()
        for key in ('session','threadId','turnId','id'):
            payload = self.answer(item, answers={'language':'中文'}); payload[key]='wrong'
            with self.assertRaises(InteractionError): self.manager.respond(payload)
        self.assertFalse(self.sent)

    def test_resolved_request_cannot_be_answered(self):
        item = self.add()
        self.manager.notification('serverRequest/resolved', {'threadId':'thread-a','requestId':7})
        with self.assertRaises(InteractionError): self.manager.respond(self.answer(item, answers={'language':'中文'}))

    def test_old_turn_event_does_not_clear_new_request(self):
        item = self.add()
        self.manager.notification('turn/completed', {'threadId':'thread-a','turn':{'id':'older-turn'}})
        self.assertEqual(self.manager.snapshot()['requests'][0]['status'],'pending')
        self.manager.notification('turn/completed', {'threadId':'thread-a','turn':{'id':'turn-a'}})
        self.assertEqual(self.manager.snapshot()['requests'][0]['status'],'resolved')

    def test_cancel_sends_empty_answers_not_approval(self):
        item = self.add(); self.manager.respond(self.answer(item,'cancel'))
        self.assertEqual(self.sent[-1]['result'], {'answers':{}})

    def test_url_localhost_goes_to_pc(self):
        for url in ('http://localhost:3333/auth','https://127.0.0.1/a','https://192.168.1.4/auth','javascript:alert(1)'):
            item = describe('mcpServer/elicitation/request', {'mode':'url','url':url,'message':'请登录'})
            self.assertEqual(item['category'],'pc'); self.assertNotIn('url', item)

    def test_https_authorization_can_be_opened_on_phone(self):
        item = self.add('mcpServer/elicitation/request', mode='url', url='https://accounts.example.com/auth', message='请授权')
        self.assertEqual(item['category'],'web')
        self.manager.respond(self.answer(item,'manual_done'))
        self.assertEqual(self.sent[-1]['result'], {'action':'accept','content':None})

    def test_forms_validate_types_enums_and_required_fields(self):
        item = self.add('mcpServer/elicitation/request', mode='form', requestedSchema={
            'type':'object','required':['choice','confirm'],'properties':{'choice':{'type':'string','enum':['A','B']},'confirm':{'type':'boolean'}}})
        self.assertEqual(item['category'],'web')
        for content in ({'choice':'C','confirm':True},{'choice':'A','confirm':'yes'},{'choice':'A'}):
            with self.assertRaises(InteractionError): self.manager.respond(self.answer(item,content=content))
        self.manager.respond(self.answer(item,content={'choice':'A','confirm':False}))
        self.assertEqual(self.sent[-1]['result']['content'],{'choice':'A','confirm':False})

    def test_secret_or_unsupported_form_is_not_fake_completed(self):
        for spec in ({'type':'string','format':'password'},{'type':'array'}, {'type':'string','pattern':'[A-Z]+'}):
            item = describe('mcpServer/elicitation/request', {'mode':'form','requestedSchema':{'type':'object','properties':{'value':spec}}})
            self.assertEqual(item['category'],'pc'); self.assertEqual(item['actions'],['cancel'])

    def test_host_tools_fail_instead_of_waiting_for_human(self):
        self.add('item/tool/call', tool='unavailable')
        self.assertFalse(self.sent[-1]['result']['success'])
        self.assertEqual(self.manager.snapshot()['requests'][0]['kind'],'notice')

    def test_text_blocker_is_notice_not_fabricated_rpc(self):
        self.manager.notification('item/completed', {'threadId':'t','turnId':'u','item':{'type':'agentMessage','text':'请手动输入验证码，再继续。'}})
        item = self.manager.snapshot()['requests'][0]
        self.manager.respond(self.answer(item,'dismiss'))
        self.assertFalse(self.sent)

    def test_snapshot_never_contains_protocol_params_or_answers(self):
        item = self.add(extra_secret='not-for-cloud')
        self.manager.respond(self.answer(item, answers={'language':'private-answer'}))
        rendered = json.dumps(self.manager.snapshot())
        for secret in ('not-for-cloud','private-answer','wireId','answerHash'):
            self.assertNotIn(secret,rendered)

    def test_dispatcher_keeps_response_and_request_ids_separate(self):
        rpc = CodexRpc.__new__(CodexRpc)
        rpc._condition = threading.Condition(); rpc._closed=False; rpc._pending={'7'}; rpc._responses={}
        rpc.interactions=self.manager
        rpc.process=types.SimpleNamespace(stdout=io.StringIO('\n'.join(map(json.dumps,[
            {'id':7,'method':'item/tool/requestUserInput','params':{'threadId':'t','turnId':'u','questions':[question()]}},
            {'id':'7','result':{'correct':True}}, {'id':'expired','result':{}}]))))
        rpc._read_stdout()
        self.assertEqual(rpc._responses,{'7':{'id':'7','result':{'correct':True}}})
        self.assertTrue(rpc._closed)
        self.assertEqual(self.manager.snapshot()['requests'][0]['status'],'disconnected')


class RelayTests(unittest.TestCase):
    add = RequestsTests.add
    answer = RequestsTests.answer

    def setUp(self):
        RequestsTests.setUp(self); self.db=sqlite3.connect(':memory:',check_same_thread=False)
        self.db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)'); relay.initialize(self.db)

    def tearDown(self): self.db.close()

    def sync(self, acks=None):
        return relay.exchange(self.db, {'snapshot':self.manager.snapshot(),'acks':acks or []})

    def test_relay_roundtrip_ack_removes_answer_body(self):
        item=self.add(); self.sync(); answer=self.answer(item,answers={'language':'中文'})
        relay.submit(self.db,answer); relay.submit(self.db,answer)
        self.assertEqual(relay.read(self.db)['requests'][0]['delivery'],'queued')
        replies=self.sync()['answers']; self.assertEqual(len(replies),1)
        self.manager.respond(replies[0]); self.sync([{'session':item['session'],'id':item['id']}])
        self.assertEqual(relay.read(self.db)['requests'][0]['status'],'answered')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM interaction_answers').fetchone()[0],0)

    def test_restart_invalidates_pending_answers(self):
        item=self.add(); self.sync(); relay.submit(self.db,self.answer(item,answers={'language':'中文'}))
        old=self.manager.snapshot(); self.manager=Interactions(self.sent.append); self.sync()
        self.assertFalse(self.sync()['answers'])
        with self.assertRaises(ValueError): relay.submit(self.db,self.answer(item,answers={'language':'中文'}))
        relay.exchange(self.db,{'snapshot':old})
        self.assertEqual(relay.load(self.db)['session'], self.manager.session)

    def test_offline_refuses_answers(self):
        item=self.add(); self.sync(); data=relay.load(self.db); data['syncedAt']=time.time()-30
        self.db.execute("UPDATE meta SET value=? WHERE key='interactions'",(json.dumps(data),));self.db.commit()
        with self.assertRaises(ValueError): relay.submit(self.db,self.answer(item,answers={'language':'中文'}))

    def test_first_answer_wins_across_browsers(self):
        item=self.add(); self.sync(); relay.submit(self.db,self.answer(item,answers={'language':'中文'}))
        with self.assertRaises(ValueError): relay.submit(self.db,self.answer(item,answers={'language':'英文'}))

    def test_rejected_answer_is_reported_and_can_be_corrected(self):
        item=self.add(); self.sync(); relay.submit(self.db,self.answer(item,answers={}))
        self.sync([{'session':item['session'],'id':item['id'],'error':'请填写回答'}])
        data=relay.read(self.db);self.assertEqual(data['requests'][0]['deliveryError'],'请填写回答')
        relay.submit(self.db,self.answer(item,answers={'language':'中文'}))
        self.assertEqual(len(self.sync()['answers']),1)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',check_same_thread=False)
        self.db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)');relay.initialize(self.db)
        tree=ast.parse((ROOT/'cloud/app.py').read_text(encoding='utf-8'))
        body=[x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='H' or isinstance(x,ast.FunctionDef) and x.name=='cookie_token']
        self.ns={'BaseHTTPRequestHandler':BaseHTTPRequestHandler,'json':json,'time':time,'SimpleCookie':SimpleCookie,
                 'urlparse':urlparse,'parse_qs':parse_qs,'secrets':secrets,'SYNC_TOKEN':'test-only-token',
                 'SESSIONS':{'test-session':time.time()+60},'interactions':relay,'db':self.db,'DB_LOCK':threading.RLock()}
        exec(compile(ast.Module(body=body,type_ignores=[]),'cloud-handler','exec'),self.ns)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.ns['H'])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.db.close()

    def request(self,path,data=None,headers=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,
            headers={'Content-Type':'application/json',**(headers or {})})
        try:r=urllib.request.urlopen(req,timeout=3)
        except urllib.error.HTTPError as e:r=e
        with r:return r.status,json.loads(r.read())

    def test_auth_and_browser_to_pc_roundtrip(self):
        for path in ('/api/interactions','/api/interactions/respond','/api/device/interactions'):
            code,_=self.request(path,{} if path!='/api/interactions' else None);self.assertEqual(code,401)
        sent=[];manager=Interactions(sent.append)
        manager.request({'id':3,'method':'item/tool/requestUserInput','params':{'threadId':'t','turnId':'u','questions':[question()]}})
        item=manager.snapshot()['requests'][0]
        code,_=self.request('/api/device/interactions',{'snapshot':manager.snapshot()}, {'Authorization':'Bearer test-only-token'})
        self.assertEqual(code,200)
        code,data=self.request('/api/interactions',headers={'Cookie':'codex_history=test-session'})
        self.assertEqual(code,200);self.assertEqual(data['requests'][0]['id'],item['id'])
        payload={k:item[k] for k in ('id','session','threadId','turnId')}|{'action':'answer','answers':{'language':'中文'}}
        code,_=self.request('/api/interactions/respond',payload,{'Cookie':'codex_history=test-session','Origin':'https://foreign.example'})
        self.assertEqual(code,403)
        code,_=self.request('/api/interactions/respond',payload,{'Cookie':'codex_history=test-session','Origin':self.base})
        self.assertEqual(code,202)
        _,data=self.request('/api/device/interactions',{'snapshot':manager.snapshot()},{'Authorization':'Bearer test-only-token'})
        manager.respond(data['answers'][0]);self.assertEqual(sent[-1]['id'],3)


class LocalHttpTests(HttpTests):
    def setUp(self):
        self.sent=[]; self.manager=Interactions(self.sent.append)
        tree=ast.parse((ROOT/'app/bridge.py').read_text(encoding='utf-8'))
        body=[x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='DashboardHandler']
        ns={'BaseHTTPRequestHandler':BaseHTTPRequestHandler,'json':json,'time':time,'SimpleCookie':SimpleCookie,
            'urlparse':urlparse,'web_sessions_lock':threading.RLock(),'web_sessions':{},
            'codex_rpc':types.SimpleNamespace(interactions=self.manager,_closed=False),'log':lambda *args:None}
        exec(compile(ast.Module(body=body,type_ignores=[]),'local-handler','exec'),ns)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),ns['DashboardHandler'])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def test_auth_and_browser_to_pc_roundtrip(self):
        self.manager.request({'id':4,'method':'item/tool/requestUserInput','params':{'threadId':'t','turnId':'u','questions':[question()]}})
        code,data=self.request('/api/interactions');self.assertEqual(code,200)
        item=data['requests'][0]
        payload={k:item[k] for k in ('id','session','threadId','turnId')}|{'action':'answer','answers':{'language':'中文'}}
        code,_=self.request('/api/interactions/respond',payload,{'Origin':'https://foreign.example'})
        self.assertEqual(code,403)
        code,_=self.request('/api/interactions/respond',payload,{'Host':'remote.example'})
        self.assertEqual(code,401)
        code,_=self.request('/api/interactions/respond',payload,{'Origin':self.base})
        self.assertEqual(code,200);self.assertEqual(self.sent[-1]['id'],4)
        payload['threadId']='wrong'
        code,_=self.request('/api/interactions/respond',payload);self.assertEqual(code,409)


if __name__=='__main__': unittest.main()
