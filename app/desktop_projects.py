"""Read desktop project presentation without changing Codex's private state."""
import json
import threading
from pathlib import Path


class DesktopProjects:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.signature = None
        self.saved = {'projects': [], 'assignments': {}}

    def snapshot(self):
        with self.lock:
            try:
                stat = self.path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if signature == self.signature:
                    return self.saved
                data = json.loads(self.path.read_text(encoding='utf-8'))
                local = data.get('local-projects') or {}
                assignments = data.get('thread-project-assignments') or {}
                order = list(data.get('project-order') or local.keys())
                for item in assignments.values():
                    if isinstance(item, dict) and item.get('projectKind') == 'local':
                        pid = item.get('projectId')
                        if pid in local and pid not in order:
                            order.append(pid)
                projects = []
                by_id = {}
                for pid in order:
                    p = local.get(pid) or {}
                    roots = [r for r in (p.get('rootPaths') or []) if isinstance(r, str) and r]
                    if not roots:
                        continue
                    entry = dict(id=pid, key='desktop:' + pid,
                                 name=p.get('name') or Path(roots[0]).name,
                                 cwd=roots[0], rootPaths=roots, order=len(projects), kind='local')
                    projects.append(entry)
                    by_id[pid] = entry
                resolved = {}
                for tid, item in assignments.items():
                    if isinstance(item, dict) and item.get('projectKind') == 'local':
                        p = by_id.get(item.get('projectId'))
                        if p:
                            resolved[tid] = p
                for tid in data.get('projectless-thread-ids') or []:
                    if isinstance(tid, str) and tid not in resolved:
                        resolved[tid] = dict(id='', key='desktop:projectless', name='独立会话',
                                             cwd='', order=len(projects), kind='projectless')
                self.saved = {'projects': projects, 'assignments': resolved}
                self.signature = signature
            except (OSError, ValueError, TypeError, AttributeError):
                pass  # Keep the last complete snapshot during an atomic desktop update.
            return self.saved

    def enrich(self, thread):
        return dict(thread, desktopProject=self.snapshot()['assignments'].get(thread.get('id')))
