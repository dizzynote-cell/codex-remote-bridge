# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

"""Persist reversible webpage visibility, independently of Codex history."""
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path

class Visibility:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def snapshot(self):
        with self.lock:
            try: return json.loads(self.path.read_text(encoding='utf-8'))
            except FileNotFoundError: return {}

    def merge(self, incoming):
        with self.lock:
            current = self.snapshot()
            for key, value in incoming.items():
                uuid.UUID(key)
                if not isinstance(value.get('hidden'), bool): raise ValueError('invalid_hidden')
                stamp = float(value['updated'])
                if not math.isfinite(stamp): raise ValueError('invalid_timestamp')
                if stamp > current.get(key, {}).get('updated', 0):
                    current[key] = {'hidden': value['hidden'], 'updated': stamp,
                                    'name': str(value.get('name') or '')[:100]}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(current, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, self.path)
            return current

    def set(self, key, hidden, name=''):
        return self.merge({key: {'hidden': hidden, 'name': name, 'updated': time.time()}})
