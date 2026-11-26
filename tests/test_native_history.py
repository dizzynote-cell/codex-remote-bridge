"""Native cursors bound reads; partial pages are never presented as full history."""
import importlib.util
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'cloud'))
from thread_history import read_history
import history_store as store


class NativeHistoryTests(unittest.TestCase):
    def reader(self, count=21, batch=None):
        calls = []
        turns = [{'id':str(i), 'status':'completed', 'itemsView':'full', 'items':[{'type':'agentMessage','text':str(i)}]} for i in range(count)]
        def call(method, params):
            calls.append((method, dict(params)))
            if method == 'thread/read':
                self.assertFalse(params['includeTurns'])
                return {'thread':{'id':'example','turns':[],'historyMode':'paginated'}}
            self.assertEqual(method, 'thread/turns/list')
            self.assertEqual(params['sortDirection'], 'desc')
            self.assertEqual(params['itemsView'], 'full')
            offset = int(params.get('cursor', '0'))
            n = min(params['limit'], batch or params['limit'])
            page = list(reversed(turns))[offset:offset+n]
            following = offset + len(page)
            return {'data':page, 'nextCursor':str(following) if following < count else None}
        return call, calls

    def test_default_fetches_only_six_full_turns_and_keeps_unknown_total(self):
        call, calls = self.reader(2000)
        thread = read_history(call, 'example')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1][1]['limit'], 6)
        self.assertEqual([t['id'] for t in thread['turns']], [str(i) for i in range(1994,2000)])
        self.assertIsNone(thread['bridgeTotalTurns'])
        self.assertTrue(thread['bridgeHasMoreTurns'])

    def test_short_page_continues_using_native_cursor(self):
        call, calls = self.reader(21, batch=4)
        thread = read_history(call, 'example', 12)
        self.assertEqual(len(thread['turns']), 12)
        self.assertEqual([c[1].get('cursor') for c in calls[1:]], [None,'4','8'])
        self.assertEqual(thread['turns'][0]['id'], '9')

    def test_all_is_explicit_and_pages_in_bounded_chunks(self):
        call, calls = self.reader(107)
        thread = read_history(call, 'example', 'all')
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(p['limit'] == 50 for _,p in calls[1:]))
        self.assertEqual(thread['bridgeTotalTurns'], 107)
        self.assertFalse(thread['bridgeHasMoreTurns'])
        self.assertEqual(thread['turns'][0]['id'], '0')

    def test_empty_and_short_histories_have_exact_totals(self):
        for count in (0,3,6):
            call, _ = self.reader(count)
            thread = read_history(call, 'example')
            self.assertEqual(thread['bridgeTotalTurns'], count)
            self.assertFalse(thread['bridgeHasMoreTurns'])

    def test_transport_error_never_retries_as_full_history(self):
        calls = []
        def call(method, params):
            calls.append(method)
            if method == 'thread/read': return {'thread':{'id':'example'}}
            raise RuntimeError('RPC timed out')
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            read_history(call, 'example')
        self.assertEqual(calls, ['thread/read','thread/turns/list'])

    def test_native_recorded_item_times_are_preserved_without_fetch_times(self):
        items = [{'type':'userMessage','startedAtMs':1793078100000},
                 {'type':'agentMessage','completedAtMs':1793078200000}]
        def call(method, params):
            return {'thread':{'id':'example'}} if method == 'thread/read' else {
                'data':[{'id':'one','itemsView':'full','items':items}], 'nextCursor':None}
        result = read_history(call,'example')['turns'][0]['items']
        self.assertEqual(result[0]['bridgeTimestamp'],1793078100000)
        self.assertEqual(result[1]['bridgeTimestamp'],1793078200000)
        self.assertNotIn('bridgeTimestamp',items[0])

    def test_only_an_explicit_old_runtime_error_allows_legacy_fallback(self):
        calls = []
        def call(method, params):
            calls.append((method,params))
            if method == 'thread/turns/list': raise RuntimeError('-32601 Method not found')
            return {'thread':{'id':'example','turns':[{'id':str(i)} for i in range(20)] if params['includeTurns'] else []}}
        thread = read_history(call, 'example')
        self.assertFalse(thread['bridgeNativeHistory'])
        self.assertEqual(len(thread['turns']), 6)
        self.assertEqual(thread['bridgeTotalTurns'], 20)
        self.assertTrue(calls[-1][1]['includeTurns'])

    def test_looping_cursor_and_incomplete_items_are_errors(self):
        for bad_page in ({'data':[], 'nextCursor':'loop'}, {'data':[{'id':'one','itemsView':'summary'}], 'nextCursor':None}):
            def call(method, params):
                return {'thread':{'id':'example'}} if method == 'thread/read' else bad_page
            with self.assertRaises(ValueError): read_history(call, 'example', 12)


class NativeHistoryCacheTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE threads(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,status TEXT,preview TEXT,updated_at TEXT,payload TEXT,content_hash TEXT,synced_at INTEGER);CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);')
        store.initialize(self.db)

    def snapshot(self, start, stop, more=True, request_id=None):
        t = {'id':'example','turns':[{'id':str(i),'status':'completed','items':[]} for i in range(start,stop)],
             'bridgeTotalTurns':None if more else stop-start,'bridgeHasMoreTurns':more}
        if request_id: t['bridgeRequestId'] = request_id
        store.ingest(self.db, {'threads':[t]})

    def request_id(self):
        return store.interests(self.db)[0]['requestId']

    def test_default_storage_is_six_and_expansion_uses_separate_window(self):
        self.snapshot(14,20)
        initial = store.read(self.db,'example','6')['thread']
        self.assertEqual(len(initial['turns']),6)
        self.assertIsNone(initial['bridgeTotalTurns'])
        self.assertTrue(initial['bridgeHasMoreTurns'])
        store.read(self.db,'example','12')
        self.snapshot(8,20,request_id=self.request_id())
        expanded = store.read(self.db,'example','12')['thread']
        self.assertEqual(len(expanded['turns']),12)
        self.assertTrue(expanded['bridgeHasMoreTurns'])
        self.assertFalse(expanded['bridgeSync']['pending'])
        raw = json.loads(self.db.execute('SELECT payload FROM threads').fetchone()[0])
        self.assertEqual(len(raw['turns']),6)

    def test_live_refresh_keeps_requested_history_and_updates_overlapping_turns(self):
        self.snapshot(14,20)
        store.read(self.db,'example','all')
        self.snapshot(0,20,more=False,request_id=self.request_id())
        self.snapshot(15,21)
        result = store.read(self.db,'example','all')['thread']
        self.assertEqual(len(result['turns']),21)
        self.assertEqual(result['bridgeTotalTurns'],21)
        self.assertFalse(result['bridgeHasMoreTurns'])
        # A subsequent ordinary six-turn requested snapshot must not replace it.
        self.snapshot(15,21,request_id=self.request_id())
        self.assertEqual(len(store.read(self.db,'example','all')['thread']['turns']),21)

    def test_disjoint_window_is_not_used_to_fill_a_gap(self):
        self.snapshot(14,20)
        store.read(self.db,'example','all')
        self.snapshot(0,20,more=False,request_id=self.request_id())
        self.snapshot(30,36)
        result = store.read(self.db,'example','all')['thread']
        self.assertEqual([t['id'] for t in result['turns']], [str(i) for i in range(30,36)])
        self.assertTrue(result['bridgeHasMoreTurns'])
        self.assertTrue(result['bridgeSync']['pending'])

    def test_reverted_tail_does_not_keep_removed_turns(self):
        self.snapshot(14,20)
        store.read(self.db,'example','all')
        self.snapshot(0,20,more=False,request_id=self.request_id())
        self.snapshot(9,15)
        result = store.read(self.db,'example','all')['thread']
        self.assertEqual(len(result['turns']),15)
        self.assertEqual(result['turns'][-1]['id'],'14')


class HistoryCallerTests(unittest.TestCase):
    def voice_check(self, read):
        import ast
        tree = ast.parse((ROOT/'app/bridge.py').read_text(encoding='utf8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'voice_text_in_completed_turn')
        scope = {'read_thread':read, 'is_valid_thread_id':lambda _:True}
        exec(compile(ast.Module(body=[fn],type_ignores=[]), '<voice-history-check>', 'exec'),scope)
        return scope['voice_text_in_completed_turn']

    def test_recent_voice_reply_does_not_fetch_all_history(self):
        calls=[]
        def read(tid, limit):
            calls.append(limit)
            return {'bridgeHasMoreTurns':True,'turns':[{'status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':'answer'}]}]}
        self.assertTrue(self.voice_check(read)('example','answer'))
        self.assertEqual(calls,[6])

    def test_explicit_voice_reply_can_validate_an_older_turn(self):
        calls=[]
        def read(tid, limit):
            calls.append(limit)
            return {'bridgeHasMoreTurns':limit != 'all','turns':[] if limit != 'all' else [{'status':'completed','items':[{'type':'agentMessage','text':'older answer'}]}]}
        self.assertTrue(self.voice_check(read)('example','older answer'))
        self.assertEqual(calls,[6,'all'])


if __name__ == '__main__': unittest.main()
