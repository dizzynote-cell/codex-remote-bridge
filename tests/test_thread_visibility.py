import importlib.util
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('visibility',Path(__file__).parents[1]/'app/thread_visibility.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class VisibilityTests(unittest.TestCase):
    def test_restore_tombstone_prevents_stale_rehide(self):
        with tempfile.TemporaryDirectory() as temp:
            local=module.Visibility(Path(temp)/'local.json')
            remote=module.Visibility(Path(temp)/'remote.json')
            key='12345678-1234-4234-8234-123456789abc'
            hidden=local.set(key,True,'Example')
            remote.merge(hidden)
            restored=remote.set(key,False,'Example')
            local.merge(restored)
            local.merge(hidden)
            self.assertFalse(local.snapshot()[key]['hidden'])
            self.assertFalse(module.Visibility(local.path).snapshot()[key]['hidden'])

    def test_invalid_identifier_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            store=module.Visibility(Path(temp)/'state.json')
            with self.assertRaises(ValueError):store.set('invalid',True)
            self.assertEqual(store.snapshot(),{})
