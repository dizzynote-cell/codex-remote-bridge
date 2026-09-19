# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

import json
import subprocess
import threading
import time
from pathlib import Path
from rpc_interactions import Interactions

ROOT = Path(__file__).resolve().parent.parent
CODEX_EXE = ROOT / "app" / "codex-app-server.exe"


class CodexRpc:
    def __init__(self):
        self.process = subprocess.Popen(
            [str(CODEX_EXE), "app-server", "--stdio"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._next_id = 1
        self._write_lock = threading.Lock()
        self._responses = {}
        self._condition = threading.Condition()
        self._closed = False
        self._pending = set()
        self.interactions = Interactions(self._send)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        self.call("initialize", {
            "clientInfo": {
                "name": "codex-feishu-bridge",
                "title": "Codex Feishu Bridge",
                "version": "0.2.0",
            },
            "capabilities": {"experimentalApi": True},
        })
        self._send({"method": "initialized", "params": {}})

    def _send(self, payload):
        with self._write_lock:
            if self._closed or self.process.poll() is not None:
                raise RuntimeError("Codex 连接已关闭，请检查主力 PC 上的桥")
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                try: message = json.loads(line)
                except json.JSONDecodeError: continue
                if not isinstance(message, dict): continue
                if "method" in message:
                    try:
                        if "id" in message: self.interactions.request(message)
                        else: self.interactions.notification(message["method"], message.get("params") or {})
                    except (ValueError, TypeError, KeyError, AttributeError):
                        if "id" in message:
                            self._send({"id": message["id"], "error": {"code": -32602, "message": "Unsupported interaction format"}})
                elif "id" in message:
                    with self._condition:
                        if str(message["id"]) in self._pending: self._responses[str(message["id"])] = message
                        self._condition.notify_all()
        except (OSError, RuntimeError): pass
        finally:
            with self._condition:
                self._closed = True; self._condition.notify_all()
            self.interactions.disconnect()

    def _drain_stderr(self):
        for _ in self.process.stderr:
            pass

    def call(self, method, params, timeout=30):
        with self._condition:
            request_id = str(self._next_id)
            self._next_id += 1
            self._pending.add(request_id)
        try:
            self._send({"id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + timeout
            with self._condition:
                while request_id not in self._responses:
                    if self._closed: raise RuntimeError("Codex 连接已关闭")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise TimeoutError(f"Codex RPC 超时：{method}")
                    self._condition.wait(remaining)
                response = self._responses.pop(request_id)
        finally:
            with self._condition:
                self._pending.discard(request_id); self._responses.pop(request_id, None)
        if "error" in response:
            raise RuntimeError(f"Codex RPC 错误：{response['error']}")
        return response.get("result")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()


if __name__ == "__main__":
    rpc = CodexRpc()
    try:
        result = rpc.call("thread/list", {
            "limit": 10,
            "sortKey": "updated_at",
            "sortDirection": "desc",
            "archived": False,
        })
        threads = result.get("data", []) if isinstance(result, dict) else []
        print(json.dumps({
            "count": len(threads),
            "threads": [
                {"id": item.get("id"), "name": item.get("name"), "cwd": item.get("cwd")}
                for item in threads
            ],
        }, ensure_ascii=False, indent=2))
    finally:
        rpc.close()
