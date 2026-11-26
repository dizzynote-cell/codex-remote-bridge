import importlib.util,json,sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'cloud'))
import history_store
spec=importlib.util.spec_from_file_location('bridge_catalog_sync',ROOT/'app/history_sync.py')
sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)

class CatalogTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:')
  self.addCleanup(self.db.close)
  self.db.executescript('CREATE TABLE threads(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,status TEXT,preview TEXT,updated_at TEXT,payload TEXT,content_hash TEXT,synced_at INTEGER);CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);')
  history_store.initialize(self.db)
  history_store.ingest(self.db,{'summaries':[{'id':'keep','name':'same title'},{'id':'removed','name':'same title'}]})
 def catalog(self,ids,stamp=100):return {'version':1,'complete':True,'capturedAt':stamp,'ids':ids}
 def test_all_pages_are_required_and_names_do_not_define_identity(self):
  pages=Mock(side_effect=[{'data':[{'id':'keep','name':'same'}],'nextCursor':'more'},{'data':[{'id':'another','name':'same'}],'nextCursor':None}])
  summaries,catalog=sync.collect_catalog(pages)
  self.assertEqual(set(summaries),{'keep','another'})
  self.assertTrue(catalog['complete']);self.assertEqual(pages.call_args_list[1].args,(100,'more'))
 def test_partial_failed_and_looping_pagination_never_produce_a_catalog(self):
  for pages in [Mock(side_effect=[{'data':[{'id':'keep'}],'nextCursor':'more'},RuntimeError('offline')]),Mock(return_value={'data':[]}),Mock(return_value={'data':[],'nextCursor':'loop'})]:
   with self.assertRaises((RuntimeError,ValueError)):sync.collect_catalog(pages,max_pages=3)
  with self.assertRaises(ValueError):sync.collect_catalog(Mock(return_value={'data':[{}],'nextCursor':None}))
 def test_full_catalog_retires_absent_cached_threads_without_deleting_history(self):
  history_store.ingest(self.db,{'threadCatalog':self.catalog(['keep'])})
  self.assertTrue(history_store.retired(self.db,'removed'));self.assertFalse(history_store.retired(self.db,'keep'))
  self.assertEqual(self.db.execute('SELECT count(*) FROM threads').fetchone()[0],2)
  self.assertIsNone(history_store.read(self.db,'removed','6'))
  self.assertEqual(self.db.execute('SELECT count(*) FROM history_requests').fetchone()[0],0)
 def test_partial_catalogs_and_transport_failures_keep_the_last_membership(self):
  for catalog in [None,{},dict(self.catalog([]),complete=False),dict(self.catalog([]),capturedAt=float('nan')),dict(self.catalog([]),ids='keep')]:
   history_store.ingest(self.db,{'threadCatalog':catalog})
   self.assertFalse(history_store.retired(self.db,'removed'))
 def test_old_catalogs_or_late_history_cannot_resurrect_removed_threads(self):
  history_store.ingest(self.db,{'threadCatalog':self.catalog(['keep'])})
  history_store.ingest(self.db,{'threadCatalog':self.catalog(['keep','removed'],90),'threads':[{'id':'removed','turns':[]}]})
  self.assertTrue(history_store.retired(self.db,'removed'))
 def test_returning_threads_restore_automatically_and_empty_catalog_is_explicit(self):
  history_store.ingest(self.db,{'threadCatalog':self.catalog([])})
  self.assertTrue(history_store.retired(self.db,'keep'))
  history_store.ingest(self.db,{'threadCatalog':self.catalog(['keep'],110)})
  self.assertFalse(history_store.retired(self.db,'keep'));self.assertTrue(history_store.retired(self.db,'removed'))

if __name__=='__main__':unittest.main()
