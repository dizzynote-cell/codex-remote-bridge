"""Read recorded turn/item times from Codex rollouts without rewriting history."""
import json
import threading
from pathlib import Path


class MessageTimes:
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    def enrich(self, thread):
        rollout = thread.get('path')
        if not rollout:
            return thread
        try:
            path = Path(rollout)
            if path.suffix != '.jsonl':
                return thread
            with self.lock, path.open('rb') as stream:
                stat = path.stat()
                key = str(path)
                old = self.cache.get(key)
                identity = (stat.st_dev, stat.st_ino)
                if (not old or old['identity'] != identity or stat.st_size < old['size']
                        or (stat.st_size == old['size'] and stat.st_mtime_ns != old['mtime'])):
                    old = dict(identity=identity, offset=0, turns={}, items={})
                stream.seek(old['offset'])
                while True:
                    line = stream.readline()
                    if not line or not line.endswith(b'\n'):
                        break
                    old['offset'] = stream.tell()
                    try:
                        record = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    payload = record.get('payload') or {}
                    if record.get('type') != 'event_msg' or not isinstance(payload, dict):
                        continue
                    kind, tid = payload.get('type'), payload.get('turn_id')
                    stamp = record.get('timestamp')
                    if tid and kind in ('task_started', 'task_complete'):
                        name = 'bridgeStartedAt' if kind == 'task_started' else 'bridgeEndedAt'
                        old['turns'].setdefault(tid, {})[name] = payload.get('started_at' if kind == 'task_started' else 'completed_at') or stamp
                    item = payload.get('item') or {}
                    if kind == 'item_completed' and tid and isinstance(item, dict) and item.get('id'):
                        # User items may complete before execution starts; use their recorded start.
                        old['items'][(tid, item['id'])] = payload.get('started_at_ms') or payload.get('completed_at_ms') or stamp
                old.update(size=stat.st_size, mtime=stat.st_mtime_ns)
                if len(self.cache) >= 64 and key not in self.cache:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[key] = old
                for turn in thread.get('turns') or []:
                    tid = turn.get('id')
                    turn.update({k: v for k, v in old['turns'].get(tid, {}).items() if v})
                    for item in turn.get('items') or []:
                        stamp = old['items'].get((tid, item.get('id')))
                        if stamp:
                            item['bridgeTimestamp'] = stamp
        except (OSError, ValueError, TypeError, AttributeError):
            pass  # Missing or older records stay unknown, never use fetch/file times.
        return thread


message_times = MessageTimes()
