import importlib.util
import sqlite3
import sys
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'cloud'))
sys.path.insert(0,str(ROOT/'app'))
import history_store as store
import turn_state
import history_sync
from unittest.mock import patch
from types import SimpleNamespace

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript('CREATE TABLE threads(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,status TEXT,preview TEXT,updated_at TEXT,payload TEXT,content_hash TEXT,synced_at INTEGER);CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);')
        store.initialize(self.db)
        self.thread={'id':'one','name':'Example','updatedAt':time.time(),'bridgeTotalTurns':20,'turns':[{'id':str(i),'status':'completed','items':[]} for i in range(20)]}
    def tearDown(self):self.db.close()
    def test_snapshot_and_requested_window_survive_live_updates(self):
        store.ingest(self.db,{'threads':[self.thread]})
        result=store.read(self.db,'one','6')['thread']
        self.assertEqual(len(result['turns']),6)
        self.assertEqual(result['bridgeTotalTurns'],20)
        store.read(self.db,'one','all')
        request=store.interests(self.db)[0]
        store.ingest(self.db,{'threads':[dict(self.thread,bridgeRequestId=request['requestId'])]})
        store.ingest(self.db,{'threads':[dict(self.thread,turns=self.thread['turns'][-6:])]})
        result=store.read(self.db,'one','all')['thread']
        self.assertEqual(len(result['turns']),20)
        self.assertFalse(result['bridgeSync']['pending'])
    def test_metadata_does_not_destroy_body(self):
        store.ingest(self.db,{'threads':[self.thread]})
        store.ingest(self.db,{'summaries':[{'id':'one','name':'Renamed','updatedAt':time.time()}]})
        self.assertEqual(len(store.read(self.db,'one','6')['thread']['turns']),6)
    def test_request_coalescing_and_new_limit(self):
        store.ingest(self.db,{'threads':[self.thread]})
        store.read(self.db,'one','12')
        first=store.interests(self.db)[0]['requestId']
        store.read(self.db,'one','12')
        self.assertEqual(first,store.interests(self.db)[0]['requestId'])
        store.read(self.db,'one','all')
        self.assertNotEqual(first,store.interests(self.db)[0]['requestId'])
    def test_metadata_only_thread_requests_body(self):
        store.ingest(self.db,{'summaries':[{'id':'one','name':'Old','updatedAt':1}]})
        self.assertTrue(store.read(self.db,'one','6')['thread']['bridgeSync']['pending'])
    def test_interrupted_is_not_completed(self):
        old={'id':'a','status':'interrupted','items':[]}
        new={'id':'b','status':'inProgress'}
        self.assertIn('未生成最终答案',turn_state.message(old))
        self.assertEqual(turn_state.successor({'turns':[old,new]},old),new)
        self.assertIsNone(turn_state.successor({'turns':[old]},old))

    def run_worker(self,active=(),requests=()):
        now=time.time();sent=[];reads=[]
        def post(url,**kwargs):
            sent.append(kwargs['json'])
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'historyRequests':requests})
        def read(tid):
            reads.append(tid)
            return dict(self.thread,id=tid)
        api={'os':SimpleNamespace(environ={'CODEX_HISTORY_URL':'https://example.invalid/api/sync','CODEX_HISTORY_SYNC_TOKEN':'test'}),
             'http':SimpleNamespace(post=post),'cloud_runtime_state':{},'active_turns':dict.fromkeys(active,'turn'),
             'list_threads_page':lambda *_:{'data':[{'id':'recent','updatedAt':now},{'id':'old','updatedAt':now-8*86400}]},
             'read_thread':read,'enrich_thread_attachments':lambda t,_:t,'account_quota':lambda:{},'log':lambda _:None}
        ticks=0
        def sleep(_):
            nonlocal ticks
            ticks+=1
            if ticks>=2:raise KeyboardInterrupt
        with patch.object(history_sync.threading,'Thread'),patch.object(history_sync.time,'sleep',sleep):
            with self.assertRaises(KeyboardInterrupt):history_sync.run(api)
        return sent,reads
    def test_seven_day_filter_and_six_turn_transfer(self):
        sent,reads=self.run_worker()
        self.assertEqual(reads,['recent'])
        self.assertEqual(len(sent[0]['threads'][0]['turns']),6)
        self.assertEqual(len(sent[0]['summaries']),2)
    def test_running_old_thread_remains_active(self):
        _,reads=self.run_worker(active=['old'])
        self.assertEqual(reads[0],'old')
    def test_explicit_history_request_activates_old_thread(self):
        sent,reads=self.run_worker(requests=[{'threadId':'old','requestId':'r','completedId':None,'turnLimit':'all','requestedAt':time.time(),'viewedAt':time.time()}])
        self.assertEqual(reads,['recent','old'])
        self.assertEqual(len(sent[1]['threads'][0]['turns']),20)
        self.assertEqual(sent[1]['threads'][0]['bridgeRequestId'],'r')

if __name__=='__main__':unittest.main()
