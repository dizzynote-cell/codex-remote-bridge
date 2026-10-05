import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location('model_choices', Path(__file__).parents[1] / 'app' / 'model_choices.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeRpc:
    def __init__(self):
        self.sent = []

    def call(self, method, params):
        if method == 'model/list':
            return {'data': [{'model': 'gpt-6-sol', 'serviceTiers': [{'id': 'priority', 'name': 'Fast'}],
                              'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}]}
        if method == 'config/read':
            return {'config': {'model': 'gpt-6-sol', 'model_reasoning_effort': 'low'}}
        if method == 'turn/start':
            self.sent.append(params)
            return {'turn': {'id': f'turn-{len(self.sent)}', 'model': 'gpt-6-sol'}}
        raise AssertionError(method)


class FastModeTests(unittest.TestCase):
    def test_fast_and_standard_are_sent_per_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            rpc = FakeRpc()
            choices = module.ModelChoices(directory, lambda: rpc, threading.RLock())
            self.assertTrue(choices.snapshot()['speedModeSupported'])
            choices.choose('thread-1', 'gpt-6-sol', effort='low', service_tier='priority')
            choices.start('thread-1', [{'type': 'text', 'text': 'test'}])
            self.assertEqual(rpc.sent[-1]['serviceTierForTurn'], 'priority')
            choices.choose('thread-1', 'gpt-6-sol', effort='low', service_tier='default')
            choices.start('thread-1', [{'type': 'text', 'text': 'test'}])
            self.assertEqual(rpc.sent[-1]['serviceTierForTurn'], 'default')

    def test_unsupported_fast_tier_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            choices = module.ModelChoices(directory, FakeRpc, threading.RLock())
            with self.assertRaises(ValueError):
                choices.choose('thread-1', 'gpt-6-sol', effort='low', service_tier='ultrafast')


if __name__ == '__main__':
    unittest.main()
