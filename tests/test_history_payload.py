import ast
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cloud'))
from thread_payload import for_web


class HistoryPayloadTests(unittest.TestCase):
    def test_image_bytes_removed_without_changing_source_or_text(self):
        image = {'type': 'imageGeneration', 'result': 'a' * 5000000,
                 'savedPath': 'image.png', 'status': 'completed', 'revisedPrompt': 'prompt'}
        thread = {'id': 't', 'bridgeTotalTurns': 16, 'turns': [
            {'id': 'turn', 'items': [image, {'type': 'agentMessage', 'text': 'answer'}]}]}
        result = for_web(thread)
        self.assertLess(len(json.dumps(result)), 1000)
        self.assertEqual(len(image['result']), 5000000)
        self.assertEqual(result['turns'][0]['items'][0]['savedPath'], 'image.png')
        self.assertEqual(result['turns'][0]['items'][1]['text'], 'answer')
        self.assertEqual(result['bridgeTotalTurns'], 16)

    def test_small_image_reference_is_preserved(self):
        thread = {'turns': [{'items': [{'type': 'imageGeneration', 'result': 'image.png'}]}]}
        self.assertEqual(for_web(thread), thread)

    def post_handler(self, reader, length, lock, calls, path=""):
        tree = ast.parse((ROOT / 'cloud/app.py').read_text(encoding='utf-8'))
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'H')
        method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == 'do_POST')
        scope = {'DB_LOCK': lock}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<do_POST>', 'exec'), scope)
        obj = SimpleNamespace(path=path, headers={'Content-Length': str(length)}, rfile=reader, auth_gate=lambda:True,
                              connection=SimpleNamespace(settimeout=lambda _: None),
                              _do_POST=lambda body: calls.append(body),
                              json=lambda body, status: calls.append(status))
        return lambda: scope['do_POST'](obj)

    def test_slow_upload_does_not_block_history_database_lock(self):
        started, release = threading.Event(), threading.Event()
        def read(_):
            started.set()
            release.wait(3)
            return b'{}'
        lock, calls = threading.RLock(), []
        worker = threading.Thread(target=self.post_handler(SimpleNamespace(read=read), 2, lock, calls))
        worker.start()
        try:
            self.assertTrue(started.wait(1))
            acquired = lock.acquire(timeout=.2)
            if acquired: lock.release()
            self.assertTrue(acquired, 'Upload held the shared history lock')
        finally:
            release.set()
            worker.join(3)
        self.assertEqual(calls, [b'{}'])

    def test_truncated_upload_is_not_parsed(self):
        calls = []
        self.post_handler(io.BytesIO(b'{'), 50, threading.RLock(), calls)()
        self.assertEqual(calls, [])

    def test_oversized_upload_is_rejected(self):
        calls = []
        self.post_handler(io.BytesIO(b''), 25*1024*1024, threading.RLock(), calls)()
        self.assertEqual(calls, [413])





    def test_authentication_does_not_hold_history_lock(self):
        class UnavailableHistoryLock:
            def __enter__(self):
                raise AssertionError('authentication must not wait on history lock')
            def __exit__(self, *args):
                return False
        calls=[]
        self.post_handler(io.BytesIO(b'{}'),2,UnavailableHistoryLock(),calls,path='/api/auth/feishu')()
        self.assertEqual(calls,[b'{}'])


if __name__ == '__main__':
    unittest.main()
