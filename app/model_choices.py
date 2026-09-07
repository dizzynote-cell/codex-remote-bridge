"""Model catalog and per-thread choices stored only in private runtime data."""
import json
import os
import threading
import time
from pathlib import Path


class ModelChoices:
    def __init__(self, root, rpc, lock):
        self.path = Path(root) / "model-choices.json"
        self.rpc, self.rpc_lock = rpc, lock
        self.lock = threading.RLock()
        self.catalog = []
        self.checked = 0
        self.defaults = {}
        self.defaults_checked = 0
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.data = {"choices": {}, "turns": {}}

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def models(self):
        # Never acquire the RPC lock while holding the data lock.
        with self.lock:
            if self.catalog and time.time() - self.checked < 300:
                return list(self.catalog)
        catalog, cursor = [], None
        with self.rpc_lock:
            while True:
                params = {"limit": 100}
                if cursor:
                    params["cursor"] = cursor
                result = self.rpc().call("model/list", params)
                catalog.extend(m for m in result.get("data", []) if not m.get("hidden"))
                cursor = result.get("nextCursor")
                if not cursor:
                    break
        with self.lock:
            self.catalog, self.checked = catalog, time.time()
        return list(catalog)

    def read_defaults(self):
        if time.time() - self.defaults_checked < 15:
            return
        with self.rpc_lock:
            config = self.rpc().call("config/read", {"includeLayers": False}).get("config", {})
        with self.lock:
            self.defaults = {"model": config.get("model"), "effort": config.get("model_reasoning_effort"), "source": "Codex 本机配置"}
            self.defaults_checked = time.time()

    def snapshot(self, refresh=True):
        if refresh:
            self.models()
            self.read_defaults()
        with self.lock:
            return {"models": list(self.catalog), "choices": dict(self.data["choices"]), "defaults": dict(self.defaults)}

    def validate(self, model):
        if model not in {m["model"] for m in self.models()}:
            raise ValueError("模型不可用，请刷新模型列表重新选择")
        return model

    def validate_effort(self, model, effort):
        self.validate(model)
        entry = next(m for m in self.models() if m["model"] == model)
        if effort not in {e["reasoningEffort"] for e in entry.get("supportedReasoningEfforts", [])}:
            raise ValueError("该模型不支持所选推理强度，请重新选择")
        return effort

    def choose(self, thread_id, model, updated=None, effort=None):
        if model:
            self.validate(model)
            if effort:
                self.validate_effort(model, effort)
        self.merge({thread_id: {"model": model, "effort": effort, "updated": updated or time.time()}})

    def merge(self, choices):
        # Heartbeats must not wait on Codex RPC. Validate against the cached catalog.
        with self.lock:
            allowed = {m["model"] for m in self.catalog}
            changed = False
            for thread_id, choice in choices.items():
                if not isinstance(choice, dict) or (choice.get("model") is not None and choice.get("model") not in allowed):
                    continue
                stamp = choice.get("updated")
                if not isinstance(stamp, (int, float)) or not 0 < stamp < time.time() + 60:
                    continue
                if stamp > self.data["choices"].get(thread_id, {}).get("updated", 0):
                    self.data["choices"][thread_id] = {"model": choice.get("model"), "effort": choice.get("effort"), "updated": stamp}
                    changed = True
            if changed:
                self.save()

    def start(self, thread_id, codex_input, requested=None, fallback=None, effort=None):
        models = self.models()
        self.read_defaults()
        with self.lock:
            choice = self.data["choices"].get(thread_id, {})
        model = requested or choice.get("model") or self.defaults.get("model") or fallback
        entry = next((m for m in models if m["model"] == model), {})
        effort = effort or (choice.get("effort") if choice.get("model") == model else None) or (self.defaults.get("effort") if self.defaults.get("model") == model else None) or entry.get("defaultReasoningEffort")
        self.validate(model)
        self.validate_effort(model, effort)
        result = self.rpc().call("turn/start", {"threadId": thread_id, "input": codex_input, "model": model, "effort": effort})
        turn = result.get("turn") or {}
        record = {"requested": model, "effort": effort, "actual": turn.get("model")}
        if turn.get("id"):
            with self.lock:
                self.data["turns"][turn["id"]] = record
                self.save()
        result["bridgeModel"] = record
        return result

    def enrich(self, thread):
        with self.lock:
            thread["bridgeModelChoice"] = self.data["choices"].get(thread.get("id"))
            for turn in thread.get("turns", []):
                turn["bridgeModel"] = self.data["turns"].get(turn.get("id"))
        return thread
