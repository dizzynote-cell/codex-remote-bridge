import ast
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from turn_routing import running_turn, reconcile, release_owned, steer_or_idle


def thread(state='completed', turn='latest'):
    return {'id': 't', 'turns': [{'id': turn, 'status': state}]}


class RoutingTests(unittest.TestCase):
    def test_last_terminal_turn_wins_over_old_running_turn(self):
        snapshot = thread()
        snapshot['turns'].insert(0, {'id': 'old', 'status': 'inProgress'})
        active = {'t': 'old', 'other': 'working'}
        reconcile(active, snapshot)
        self.assertEqual(active, {'other': 'working'})
        call = Mock()
        self.assertIsNone(steer_or_idle('t', [], lambda _: snapshot, call))
        call.assert_not_called()

    def test_real_running_turn_is_steered(self):
        active = {'t': 'stale'}
        snapshot = thread({'type': 'inProgress'}, 'new')
        reconcile(active, snapshot)
        self.assertEqual(active['t'], 'new')
        call = Mock()
        self.assertEqual(steer_or_idle('t', [], lambda _: snapshot, call), 'new')
        self.assertEqual(call.call_args.args[1]['expectedTurnId'], 'new')

    def test_finished_between_read_and_steer_is_rechecked(self):
        snapshots = iter([thread('inProgress'), thread()])
        call = Mock(side_effect=RuntimeError('no active turn to steer'))
        self.assertIsNone(steer_or_idle('t', [], lambda _: next(snapshots), call))
        self.assertEqual(call.call_count, 1)

    def test_successor_turn_receives_steering_instead_of_duplicate_task(self):
        snapshots = iter([thread('inProgress', 'a'), thread('inProgress', 'b')])
        call = Mock(side_effect=[RuntimeError('no active turn to steer'), {}])
        self.assertEqual(steer_or_idle('t', [], lambda _: next(snapshots), call), 'b')
        self.assertEqual(call.call_count, 2)

    def test_transport_error_is_not_retried_or_treated_as_idle(self):
        read = Mock(return_value=thread('inProgress'))
        call = Mock(side_effect=RuntimeError('RPC timeout'))
        with self.assertRaisesRegex(RuntimeError, 'timeout'):
            steer_or_idle('t', [], read, call)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(read.call_count, 1)

    def test_unknown_status_does_not_start_or_steer(self):
        call = Mock()
        with self.assertRaises(RuntimeError):
            steer_or_idle('t', [], lambda _: thread(None), call)
        call.assert_not_called()

    def test_old_worker_cannot_remove_new_turn_or_another_thread(self):
        active = {'t': 'new', 'other': 'working'}
        release_owned(active, 't', 'old')
        self.assertEqual(active, {'t': 'new', 'other': 'working'})
        release_owned(active, 't', 'new')
        self.assertEqual(active, {'other': 'working'})

    def test_cloud_timeout_cleans_owned_marker(self):
        self.run_cloud_timeout(False)

    def test_cloud_timeout_preserves_newer_worker_marker(self):
        self.run_cloud_timeout(True)

    def run_cloud_timeout(self, newer):
        tree = ast.parse((ROOT / 'app/bridge.py').read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'execute_cloud_task')
        active = {'t': 'stale'}
        events = []
        def report(*args, **kwargs):
            events.append((args, kwargs))
            if newer and args[1] == 'error':
                active['t'] = 'another-worker'
        clock = iter([0, 1801])
        call = Mock(return_value={})
        start = Mock(return_value={'turn': {'id': 'owned'}})
        ns = dict(time=SimpleNamespace(monotonic=lambda: next(clock)), codex_lock=threading.RLock(),
                  active_turns=active, read_thread=lambda _: thread(), steer_or_idle=steer_or_idle,
                  release_owned=release_owned, cloud_task_report=report, log=lambda _: None,
                  is_valid_thread_id=lambda _: True, download_cloud_task_files=lambda _: [],
                  codex_rpc=SimpleNamespace(call=call), model_choices=SimpleNamespace(start=start))
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<cloud-worker>', 'exec'), ns)
        ns['execute_cloud_task']({'id': 'task', 'threadId': 't', 'text': 'test'})
        start.assert_called_once()
        self.assertFalse(any(args[0] == 'turn/steer' for args, _ in call.call_args_list))
        self.assertEqual(active.get('t'), 'another-worker' if newer else None)
        self.assertTrue(any(args[1] == 'error' for args, _ in events))


if __name__ == '__main__':
    unittest.main()
