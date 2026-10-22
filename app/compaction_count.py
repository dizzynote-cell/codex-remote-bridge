"""Count completed compactions from the RPC-supplied rollout, incrementally."""
import json
import threading
from pathlib import Path


class CompactionCounter:
    def __init__(self):
        self.cache = {}
        self.lock = threading.Lock()

    def count(self, rollout):
        if not rollout:
            return None
        try:
            path = Path(rollout)
            if path.suffix != '.jsonl':
                return None
            with self.lock, path.open('rb') as stream:
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
                key = str(path)
                old = self.cache.get(key)
                if (old and old['identity'] == identity and old['size'] == stat.st_size
                        and old['mtime'] == stat.st_mtime_ns):
                    return old['count']
                reset = (not old or old['identity'] != identity or stat.st_size < old['size']
                         or stat.st_size == old['size'])
                offset, count = (0, 0) if reset else (old['offset'], old['count'])
                stream.seek(offset)
                while True:
                    line = stream.readline()
                    if not line or not line.endswith(b'\n'):
                        break  # Retry a partially written final record next time.
                    if line.strip():
                        record = json.loads(line)
                        if record.get('type') == 'compacted':
                            count += 1
                    offset = stream.tell()
                if len(self.cache) >= 64 and key not in self.cache:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[key] = dict(identity=identity, size=stat.st_size,
                                       mtime=stat.st_mtime_ns, offset=offset, count=count)
                return count
        except (OSError, ValueError, TypeError, AttributeError):
            return None


counter = CompactionCounter()
