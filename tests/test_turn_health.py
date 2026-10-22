import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from turn_health import TurnHealth

TID = '11111111-1111-4111-8111-111111111111'
TURN = '22222222-2222-4222-8222-222222222222'


def snapshot(items=None, state='inProgress', turn=TURN):
    return {'id': TID, 'turns': [{'id': turn, 'status': state, 'startedAt': 1000,
            'items': items if items is not None else [{'type': 'userMessage', 'content': []}]}]}


class TurnHealthTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.health = TurnHealth(clock=lambda: self.now)

    def test_no_output_becomes_advisory_not_failed(self):
        self.assertIsNone(self.health.snapshot(snapshot()))
        self.now = 1121
        value = self.health.snapshot(snapshot())
        self.assertEqual(value['kind'], 'no_progress')
        self.assertNotIn('失败', value['message'])

    def test_explicit_retry_then_new_output_clears_warning(self):
        self.health.snapshot(snapshot())
        self.now = 1010
        self.health.notification('error', {'threadId': TID, 'turnId': TURN, 'willRetry': True})
        self.assertEqual(self.health.snapshot(snapshot())['kind'], 'retrying')
        self.now = 1011
        self.assertIsNone(self.health.snapshot(snapshot([{'type': 'agentMessage', 'text': 'working'}])))

    def test_long_running_tool_and_user_confirmation_are_not_connection_failure(self):
        self.health.snapshot(snapshot())
        self.now = 1500
        self.assertIsNone(self.health.snapshot(snapshot([{'type': 'commandExecution', 'status': 'inProgress'}])))
        self.assertIsNone(self.health.snapshot(snapshot(), waiting=True))

    def test_final_status_and_unrelated_turn_suppress_old_retry(self):
        self.health.retry(TID, TURN)
        self.assertIsNone(self.health.snapshot(snapshot(state='completed')))
        self.assertIsNone(self.health.snapshot(snapshot(turn='new-turn')))

    def test_stderr_error_is_scoped_and_message_does_not_leak_logs(self):
        self.health.stderr(f'thread_id={TID} turn.id="{TURN}" Request failed secret-do-not-display')
        value = self.health.snapshot(snapshot())
        self.assertEqual(value['kind'], 'retrying')
        self.assertNotIn('secret', str(value))
        other = TurnHealth(clock=lambda: 1000)
        other.stderr('failed to fetch codex rate limits: error sending request')
        self.assertIsNone(other.snapshot(snapshot()))

    def test_real_log_schema_can_detect_retry_after_bridge_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'logs_2.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE logs(id INTEGER PRIMARY KEY,ts INTEGER,target TEXT,feedback_log_body TEXT)')
                db.execute('INSERT INTO logs VALUES(1,1080,?,?)', ('codex_http_client::client',
                           f'thread_id={TID} turn_id={TURN} Request failed method=POST /responses'))
                db.commit()
            health = TurnHealth(directory, clock=lambda: 1100)
            self.assertEqual(health.snapshot(snapshot())['kind'], 'retrying')

    def test_missing_or_malformed_diagnostic_database_does_not_fail_request(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'logs_2.sqlite').write_bytes(b'not a database')
            health = TurnHealth(directory, clock=lambda: 1000)
            self.assertIsNone(health.snapshot(snapshot()))


if __name__ == '__main__':
    unittest.main()
