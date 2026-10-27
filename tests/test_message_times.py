import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from message_times import MessageTimes

class MessageTimesTests(unittest.TestCase):
    def test_incremental_exact_item_matching_partial_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rollout.jsonl'
            def record(kind, **payload):
                return json.dumps(dict(type='event_msg', timestamp='2026-10-27T05:15:00Z', payload=dict(type=kind, turn_id='t', **payload))) + '\n'
            path.write_text(record('task_started') + record('item_completed', item={'id':'u'}, started_at_ms=1793078100000), encoding='utf8')
            thread = dict(path=str(path), turns=[dict(id='t',items=[dict(id='u'),dict(id='a'),dict(id='steer')])])
            index=MessageTimes()
            index.enrich(thread)
            self.assertEqual(thread['turns'][0]['items'][0]['bridgeTimestamp'],1793078100000)
            self.assertNotIn('bridgeTimestamp',thread['turns'][0]['items'][1])
            line=record('item_completed',item={'id':'a'},completed_at_ms=1793078200000)
            with path.open('a',encoding='utf8') as out:out.write(line[:-1])
            index.enrich(thread)
            self.assertNotIn('bridgeTimestamp',thread['turns'][0]['items'][1])
            with path.open('a',encoding='utf8') as out:out.write('\n')
            index.enrich(thread)
            self.assertEqual(thread['turns'][0]['items'][1]['bridgeTimestamp'],1793078200000)
            self.assertNotIn('bridgeTimestamp',thread['turns'][0]['items'][2])
            self.assertNotIn('bridgeTimestamp',index.enrich({'turns':[{'items':[{}]}]})['turns'][0]['items'][0])

    def test_same_size_rewrite_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'rollout.jsonl'
            p.write_text('invalid\n',encoding='utf8')
            index=MessageTimes()
            self.assertEqual(index.enrich({'path':str(p),'turns':[]})['turns'],[])
            p.write_text('',encoding='utf8')
            index.enrich({'path':str(p),'turns':[]})
            self.assertEqual(index.cache[str(p)]['offset'],0)
