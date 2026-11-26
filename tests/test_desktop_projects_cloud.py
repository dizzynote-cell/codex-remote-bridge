import json
import sys
import threading
from types import SimpleNamespace
from pathlib import Path
from urllib.parse import unquote

from test_interactions import HttpTests as Base
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cloud'))
import history_store


class DesktopCloudTests(Base):
    def setUp(self):
        super().setUp()
        self.db.executescript('''
            CREATE TABLE threads(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,status TEXT,preview TEXT,updated_at TEXT,payload TEXT,content_hash TEXT,synced_at INTEGER);
            CREATE TABLE thread_organizer(thread_id TEXT PRIMARY KEY,name TEXT,pinned INTEGER,project TEXT,updated REAL);
            CREATE TABLE hidden_threads(thread_id TEXT PRIMARY KEY);
        ''')
        history_store.initialize(self.db)
        self.ns.update(HISTORY_LOCK=self.ns['DB_LOCK'], history_store=history_store,
                       unquote=unquote, MODEL_REFRESH=threading.Condition(),
                       model_refresh_requested=0, model_refresh_completed=0,
                       model_settings=lambda: {'models': []},

                       sync_visibility=lambda _: {},
                       thread_organizer=SimpleNamespace(merge=lambda *_: {}),
                       merge_model_settings=lambda _: {'choices': {}})
        self.tid = '33333333-3333-4333-8333-333333333333'
        history_store.ingest(self.db, {'threads': [dict(id=self.tid, name='Example', cwd='C:/old',
                                                         turns=[], desktopProject={'id': 'stale'})]})
        self.cookie = {'Cookie': 'codex_history=test-session'}

    def test_metadata_move_updates_list_and_body_without_resyncing_history(self):
        for pid in ('cleanup', 'moved-again'):
            project = dict(id=pid, key='desktop:' + pid, name=pid, cwd='D:/new')
            state = {'projects': [project], 'assignments': {self.tid: project}}
            status, _ = self.request('/api/device/heartbeat', {'desktopProjectState': state},
                                     {'Authorization': 'Bearer test-only-token'})
            self.assertEqual(status, 200)
            status, listing = self.request('/api/threads', headers=self.cookie)
            self.assertEqual(status, 200)
            self.assertEqual(listing['threads'][0]['desktopProject']['id'], pid)
            self.assertEqual(listing['threads'][0]['cwd'], 'C:/old')
            self.assertEqual(listing['projects'][0]['key'], 'desktop:' + pid)
            status, body = self.request('/api/thread/' + self.tid, headers=self.cookie)
            self.assertEqual(status, 200)
            self.assertEqual(body['thread']['desktopProject']['id'], pid)
        self.assertEqual(self.request('/api/threads')[0], 401)

    def test_model_refresh_requested_once_per_reload_and_acknowledged_by_device(self):
        device = {'Authorization': 'Bearer test-only-token'}
        self.assertEqual(self.request('/api/models')[0], 401)
        status, first = self.request('/api/models', headers=self.cookie)
        self.assertEqual(status, 200)
        generation = first['refreshRequest']
        self.assertEqual(self.request('/api/models', headers=self.cookie)[1]['refreshRequest'], generation)
        self.assertEqual(self.request('/api/device/heartbeat', {}, device)[1]['modelRefreshRequest'], generation)
        ack = {'modelRefreshCompleted': generation}
        self.assertEqual(self.request('/api/device/heartbeat', ack, device)[1]['modelRefreshRequest'], '')
        self.assertEqual(self.request('/api/models?after=' + generation, headers=self.cookie), (200, {'models': []}))
        self.assertNotEqual(self.request('/api/models', headers=self.cookie)[1]['refreshRequest'], generation)


del Base
