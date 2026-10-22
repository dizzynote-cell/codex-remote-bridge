import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from compaction_count import CompactionCounter


class CompactionTests(unittest.TestCase):
    def test_append_and_partial_record_do_not_double_count(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'rollout.jsonl'
            p.write_bytes(b'{"type":"compacted","payload":{}}\n')
            counter = CompactionCounter()
            self.assertEqual(counter.count(p), 1)
            self.assertEqual(counter.count(p), 1)
            with p.open('ab') as f:
                f.write(b'{"type":"compacted"')
            self.assertEqual(counter.count(p), 1)
            with p.open('ab') as f:
                f.write(b',"payload":{}}\n')
            self.assertEqual(counter.count(p), 2)

    def test_rewritten_rollout_is_recounted(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'rollout.jsonl'
            p.write_text(json.dumps({'type': 'compacted'}) + '\n', encoding='utf-8')
            counter = CompactionCounter()
            self.assertEqual(counter.count(p), 1)
            p.write_text('{}\n', encoding='utf-8')
            self.assertEqual(counter.count(p), 0)

    def test_unavailable_or_corrupt_rollout_is_unknown(self):
        counter = CompactionCounter()
        self.assertIsNone(counter.count(None))
        self.assertIsNone(counter.count('missing.jsonl'))
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'rollout.jsonl'
            p.write_text('bad json\n', encoding='utf-8')
            self.assertIsNone(counter.count(p))

    def test_unrelated_events_and_summary_text_are_not_compactions(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'rollout.jsonl'
            records = [{'type': 'event_msg', 'payload': {'type': 'token_count'}},
                       {'type': 'response_item', 'payload': {'text': 'compacted'}}]
            p.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')
            self.assertEqual(CompactionCounter().count(p), 0)


if __name__ == '__main__':
    unittest.main()
