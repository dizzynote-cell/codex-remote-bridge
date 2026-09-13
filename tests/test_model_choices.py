"""Offline regression tests: no real Codex turns, credentials, or production DB."""
import ast
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from model_choices import ModelChoices

THREAD = "11111111-1111-4111-8111-111111111111"
MODELS = [{"model": name, "isDefault": name == "test-a", "defaultReasoningEffort": "low",
           "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}]}
          for name in ("test-a", "test-b")]


class FakeRpc:
    def __init__(self):
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, dict(params)))
        if method == "config/read":
            return {"config": {"model": "test-a", "model_reasoning_effort": "low"}}
        if method == "model/list":
            return {"data": MODELS, "nextCursor": None}
        if method == "turn/start":
            return {"turn": {"id": "test-turn"}}
        return {}


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rpc = FakeRpc()
        self.settings = ModelChoices(self.temp.name, lambda: self.rpc, threading.RLock())

    def tearDown(self):
        self.temp.cleanup()

    def test_request_snapshot_and_history_survive_restart(self):
        self.settings.choose(THREAD, "test-a")
        self.settings.choose(THREAD, "test-b")
        self.settings.start(THREAD, [], "test-a")
        self.assertEqual(self.rpc.calls[-1][1]["model"], "test-a")
        reloaded = ModelChoices(self.temp.name, lambda: self.rpc, threading.RLock())
        thread = reloaded.enrich({"id": THREAD, "turns": [{"id": "test-turn"}, {"id": "old"}]})
        self.assertEqual(thread["bridgeModelChoice"]["model"], "test-b")
        self.assertEqual(thread["turns"][0]["bridgeModel"]["requested"], "test-a")
        self.assertIsNone(thread["turns"][1]["bridgeModel"])

    def test_effort_is_persisted_and_sent(self):
        self.settings.choose(THREAD, "test-b", effort="high")
        self.settings.start(THREAD, [])
        self.assertEqual(self.rpc.calls[-1][1]["effort"], "high")
        with self.assertRaises(ValueError):
            self.settings.start(THREAD, [], "test-b", effort="ultra")
        self.settings.choose(THREAD, None)
        self.settings.start(THREAD, [])
        self.assertEqual(self.rpc.calls[-1][1]["model"], "test-a")
        self.assertEqual(self.rpc.calls[-1][1]["effort"], "low")

    def test_follow_defaults_not_catalog_recommendation(self):
        self.settings.snapshot()
        self.settings.defaults = {"model": "test-b", "effort": "high"}
        self.settings.start(THREAD, [])
        self.assertEqual(self.rpc.calls[-1][1]["model"], "test-b")
        self.assertEqual(self.rpc.calls[-1][1]["effort"], "high")

    def test_invalid_model_does_not_start(self):
        with self.assertRaises(ValueError):
            self.settings.start(THREAD, [], "invalid")
        self.assertFalse(any(m == "turn/start" for m, _ in self.rpc.calls))

    def test_stale_choice_and_heartbeat_do_not_call_rpc(self):
        self.settings.choose(THREAD, "test-b")
        count = len(self.rpc.calls)
        self.settings.merge({THREAD: {"model": "test-a", "updated": time.time() - 60}})
        self.assertEqual(self.settings.snapshot(False)["choices"][THREAD]["model"], "test-b")
        self.assertEqual(len(self.rpc.calls), count)

    def test_default_and_feishu_choice(self):
        self.settings.start(THREAD, [])
        self.assertEqual(self.rpc.calls[-1][1]["model"], "test-a")
        self.settings.choose(THREAD, "test-b")
        self.settings.start(THREAD, [])
        self.assertEqual(self.rpc.calls[-1][1]["model"], "test-b")

    def test_pagination_filters_hidden(self):
        class Paged:
            def call(self, method, params):
                if not params.get("cursor"):
                    return {"data": [MODELS[0]], "nextCursor": "page2"}
                return {"data": [MODELS[1], {"model": "hidden", "hidden": True}]}
        paged = ModelChoices(self.temp.name, Paged, threading.RLock())
        self.assertEqual([m["model"] for m in paged.models()], ["test-a", "test-b"])

    def test_local_steering_does_not_start_or_switch_running_turn(self):
        # Evaluate only the executor, not bridge startup or credential loading.
        tree = ast.parse((ROOT / "app/bridge.py").read_text(encoding="utf-8-sig"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_local_web_task")
        updates = []
        self.settings.choose(THREAD, "test-b")
        from datetime import datetime
        env = dict(Path=Path, datetime=datetime, is_valid_thread_id=lambda _: True,
                   model_choices=self.settings, WEB_INBOX_DIR=Path(self.temp.name),
                   set_local_web_task=lambda *a, **kw: updates.append(kw),
                   codex_lock=threading.RLock(), active_turns={THREAD: "running-turn"},
                   codex_rpc=self.rpc, log=lambda _: None)
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<executor-test>", "exec"), env)
        env["execute_local_web_task"]("task", THREAD, "additional guidance", [], requested_model="test-b")
        self.assertEqual(self.rpc.calls[-1][0], "turn/steer")
        self.assertNotIn("model", self.rpc.calls[-1][1])
        self.assertTrue(updates[-1]["steered"])
        self.assertEqual(self.settings.snapshot(False)["choices"][THREAD]["model"], "test-b")


class CloudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        tree = ast.parse((ROOT / "cloud/app.py").read_text(encoding="utf-8-sig"))
        # Exclude the server's final serve_forever invocation; bind a test-only port.
        tree.body = tree.body[:-1]
        cls.env = {"__file__": str(ROOT / "cloud/app.py"), "__name__": "cloud_test"}
        with patch.dict(os.environ, {"CODEX_HISTORY_DB": str(Path(cls.temp.name) / "history.db"),
                                    "PUBLIC_BASE_URL": "https://example.invalid",
                                    "FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test",
                                    "FEISHU_OWNER_OPEN_ID": "test", "SYNC_TOKEN": "test-sync"}):
            exec(compile(tree, "<cloud-test>", "exec"), cls.env)
        cls.env["SESSIONS"]["test-session"] = time.time() + 1000
        cls.server = cls.env["ThreadingHTTPServer"](("127.0.0.1", 0), cls.env["H"])
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.env["db"].close()
        cls.temp.cleanup()

    def request(self, method, path, data=None, auth="user"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if auth == "user":
            headers["Cookie"] = "codex_history=test-session"
        if auth == "device":
            headers["Authorization"] = "Bearer test-sync"
        conn.request(method, path, json.dumps(data) if data is not None else None, headers)
        response = conn.getresponse()
        result = (response.status, json.loads(response.read()))
        conn.close()
        return result

    def test_thread_history_defaults_to_six_and_expands(self):
        thread_id = "22222222-2222-4222-8222-222222222222"
        payload = {"id": thread_id, "name": "long", "turns": [{"id": str(i)} for i in range(14)]}
        raw = json.dumps(payload)
        self.env["db"].execute(
            "INSERT OR REPLACE INTO threads VALUES(?,?,?,?,?,?,?,?,?)",
            (thread_id, "long", "", "completed", "", "", raw, "hash", int(time.time())),
        )
        self.env["db"].commit()
        code, result = self.request("GET", f"/api/thread/{thread_id}")
        self.assertEqual(code, 200)
        self.assertEqual([t["id"] for t in result["thread"]["turns"]], [str(i) for i in range(8, 14)])
        self.assertEqual(result["thread"]["bridgeTotalTurns"], 14)
        _, expanded = self.request("GET", f"/api/thread/{thread_id}?turnLimit=12")
        self.assertEqual(len(expanded["thread"]["turns"]), 12)
        self.assertEqual(expanded["thread"]["turns"][0]["id"], "2")

    def test_model_auth_and_queue_snapshot(self):
        self.assertEqual(self.request("GET", "/api/models", auth=None)[0], 401)
        self.assertEqual(self.request("POST", "/api/model-choice", {}, auth=None)[0], 401)
        code, _ = self.request("POST", "/api/device/heartbeat",
                               {"modelSettings": {"models": MODELS, "choices": {}}}, "device")
        self.assertEqual(code, 200)
        self.assertEqual(self.request("GET", "/api/models")[1]["models"], MODELS)
        self.assertEqual(self.request("POST", "/api/model-choice",
                                     {"threadId": THREAD, "model": "unknown"})[0], 400)
        self.request("POST", "/api/model-choice", {"threadId": THREAD, "model": "test-a"})
        code, _ = self.request("POST", "/api/tasks",
                              {"threadId": THREAD, "text": "test", "model": "test-a", "effort": "high"})
        self.assertEqual(code, 202)
        self.request("POST", "/api/model-choice", {"threadId": THREAD, "model": "test-b"})
        _, task = self.request("GET", "/api/device/tasks", auth="device")
        self.assertEqual(task["task"]["model"], "test-a")
        self.assertEqual(task["task"]["effort"], "high")
        _, reply = self.request("POST", "/api/device/heartbeat",
                                {"modelSettings": {"choices": {THREAD: {"model": "test-a", "updated": 1}}}}, "device")
        self.assertEqual(reply["modelChoices"][THREAD]["model"], "test-b")


if __name__ == "__main__":
    unittest.main()
