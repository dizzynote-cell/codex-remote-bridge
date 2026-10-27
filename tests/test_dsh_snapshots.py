import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'cloud'))
from dsh_snapshots import DshSnapshots
from dsh_gateway import DshGateway
from test_dsh_gateway import Handler

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=DshSnapshots(Path(self.temp.name)/'dsh.db')
    def tearDown(self):self.store.close();self.temp.cleanup()
    def ingest(self,**kw):return self.store.ingest(dict(version=1,**kw))
    def history(self,count):
        return {'id':'session-demo','name':'Synthetic','cwd':'D:/demo','bridgeTotalTurns':count,'updatedAt':1700000000000,'turns':[{'id':str(i),'status':'completed','items':[{'type':'agentMessage','text':str(i)}]} for i in range(count)]}
    def test_six_turn_cache_and_requested_older_window(self):
        self.ingest(summaries=[{'id':'session-demo','name':'Synthetic','updatedAt':1700000000000}],threads=[self.history(10)])
        result=self.store.read('/dsh/api/thread/session-demo?turnLimit=6',True)
        self.assertEqual(len(result['thread']['turns']),6)
        self.assertEqual(result['thread']['turns'][0]['id'],'4')
        self.store.read('/dsh/api/thread/session-demo?turnLimit=all',True)
        request=self.store.requests()[0];thread=self.history(10);thread['bridgeRequestId']=request['requestId']
        self.ingest(threads=[thread])
        self.assertEqual(len(self.store.read('/dsh/api/thread/session-demo?turnLimit=all',False)['thread']['turns']),10)
        self.assertTrue(self.store.read('/dsh/api/thread/session-demo',False)['thread']['bridgeSync']['stale'])
        self.assertIsNone(self.store.read('/dsh/api/local-tasks',True))
    def test_catalog_isolated_pin_hide_restore_and_stale_preference(self):
        self.ingest(metadata={'status':{'mode':'local'}});self.assertFalse(self.store.available)
        rows=[{'id':'old','name':'Old','updatedAt':1},{'id':'new','name':'New','updatedAt':2}]
        self.ingest(summaries=rows,metadata={'library':{'threads':{'old':{'pinned':True,'updatedAt':1}}}})
        self.assertTrue(self.store.available)
        self.assertEqual(self.store.read('/dsh/api/threads?limit=1',False)['threads'][0]['id'],'old')
        self.store.confirmed_write('/dsh/api/thread-library',{'threadId':'old'},{'thread':{'hidden':True,'pinned':True,'updatedAt':3}})
        self.ingest(metadata={'library':{'threads':{'old':{'hidden':False,'updatedAt':2}}}})
        self.assertEqual([r['id'] for r in self.store.read('/dsh/api/threads',True)['threads']],['new'])
        self.store.confirmed_write('/dsh/api/thread-library',{'threadId':'old'},{'thread':{'hidden':False,'pinned':True,'updatedAt':4}})
        self.assertEqual(len(self.store.read('/dsh/api/threads',True)['threads']),2)
        with self.assertRaises(ValueError):self.store.read('/dsh/api/thread/%2e%2e%2fother',True)
    def test_control_cache_invalidation_and_no_write_cache(self):
        path='/dsh/api/models?threadId=session-demo'
        self.store.cache_control(path,{'session':{'model':'test'}})
        self.assertEqual(self.store.read(path,True)['session']['model'],'test')
        self.store.confirmed_write('/dsh/api/models',{'threadId':'session-demo'},{'ok':True})
        self.assertIsNone(self.store.read(path,True))
    def test_static_and_snapshot_reads_work_offline_but_still_require_login(self):
        web=Path(self.temp.name)/'web';web.mkdir();(web/'index.html').write_text('<!-- bridge-boot -->');(web/'app.js').write_text('// fixture')
        gateway=DshGateway('t'*48,'https://bridge.example.test',snapshot_path=Path(self.temp.name)/'gateway.db',web_root=web)
        try:
            self.assertFalse(gateway.online)
            anonymous=Handler('/dsh/');gateway.handle(anonymous);self.assertEqual(anonymous.status,302)
            page=Handler('/dsh/',authed=True);gateway.handle(page);self.assertEqual(page.status,200);self.assertIn(b'remote:true',page.wfile.getvalue());self.assertEqual(len(gateway.jobs),0)
            asset=Handler('/dsh/app.js',authed=True);gateway.handle(asset);self.assertIn('max-age=300',asset.response_headers['cache-control'])
            cached=Handler('/dsh/app.js',authed=True,headers={'If-None-Match':asset.response_headers['etag']});gateway.handle(cached);self.assertEqual(cached.status,304)
            gateway.snapshots.ingest({'version':1,'summaries':[],'metadata':{'balance':{'available':True,'display':{'label':'synthetic'}}}})
            data=Handler('/dsh/api/balance',authed=True);gateway.handle(data);self.assertEqual(data.status,200);self.assertTrue(json.loads(data.wfile.getvalue())['stale'])
            bad=Handler('/dsh/%2e%2e/secret',authed=True);gateway.handle(bad);self.assertEqual(bad.status,404)
            wrong=Handler('/api/device/dsh-relay/snapshot','POST',headers={'Authorization':'Bearer wrong'},body=b'{}');gateway.handle(wrong);self.assertEqual(wrong.status,401)
        finally:gateway.snapshots.close()
    def test_invalid_metadata_rolls_back(self):
        with self.assertRaises((ValueError,AttributeError)):
            self.ingest(metadata={'status':{'mode':'bad'},'library':{'threads':[]}})
        self.assertIsNone(self.store.meta('status'))
