# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

"""Persistent webpage organization keyed by stable Codex thread UUIDs."""
import json, os, threading, time
from pathlib import Path

class Organizer:
    def __init__(self, path: Path): self.path=path; self.lock=threading.RLock()
    def _read(self):
        try:
            data=json.loads(self.path.read_text(encoding="utf-8"));return data if isinstance(data,dict) else {}
        except (FileNotFoundError,ValueError):return {}
    def snapshot(self):
        with self.lock:return {"threads":self._read()}
    def get(self,thread_id):
        with self.lock:return self._read().get(thread_id,{})
    def update(self,thread_id,*,name=None,pinned=None,project=None):
        with self.lock:
            data=self._read();item=data.get(thread_id,{})
            if name is not None:item["name"]=name
            if pinned is not None:item["pinned"]=bool(pinned)
            if project is not None:
                if project:item["project"]=project
                else:item.pop("project",None)
            item["updated"]=time.time();data[thread_id]=item;self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix(".tmp");temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8");os.replace(temporary,self.path)
            return dict(item)
    def merge(self,incoming):
        if not isinstance(incoming,dict):return self.snapshot()
        incoming=incoming.get("threads",incoming)
        if not isinstance(incoming,dict):return self.snapshot()
        with self.lock:
            data=self._read();changed=False
            for thread_id,item in incoming.items():
                if not isinstance(item,dict):continue
                if float(item.get("updated") or 0)<=float(data.get(thread_id,{}).get("updated") or 0):continue
                data[thread_id]={key:item[key] for key in ("name","pinned","project","updated") if key in item};changed=True
            if changed:
                self.path.parent.mkdir(parents=True,exist_ok=True);temporary=self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8");os.replace(temporary,self.path)
            return {"threads":data}


