# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

import json
import base64
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from http.cookies import SimpleCookie
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor"))

from dotenv import load_dotenv
import lark_oapi as lark
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from lark_oapi.api.im.v1 import *
from codex_rpc import CodexRpc

ENV_FILE = ROOT / "config" / ".env"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
WEB_DIR = ROOT / "web"
INBOX_DIR = DATA_DIR / "feishu-inbox"
WEB_INBOX_DIR = DATA_DIR / "web-inbox"
STATE_FILE = DATA_DIR / "state.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
INBOX_DIR.mkdir(parents=True, exist_ok=True)
WEB_INBOX_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(ENV_FILE)

APP_ID = (os.getenv("FEISHU_APP_ID") or "").strip()
APP_SECRET = (os.getenv("FEISHU_APP_SECRET") or "").strip()
if not APP_ID or not APP_SECRET:
    raise RuntimeError("配置缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")


def log(message: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {message}"
    print(line, flush=True)
    with (LOG_DIR / "bridge.log").open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def is_valid_thread_id(value: str) -> bool:
    try:
        uuid.UUID(str(value).removeprefix("urn:uuid:"))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"owner_open_id": None, "seen_message_ids": []}
    except Exception as error:
        log(f"状态文件读取失败，将重新建立：{error}")
        return {"owner_open_id": None, "seen_message_ids": []}


state = load_state()
seen = set(state.get("seen_message_ids", []))
codex_lock = threading.RLock()
codex_rpc = CodexRpc()
active_turns: dict[str, str] = {}
thread_message_locks: dict[str, threading.Lock] = {}
thread_message_locks_guard = threading.Lock()
mode_state = {"desktop_running": None, "mode": "detecting", "changed_at": time.time()}
feishu_lock = threading.RLock()
feishu_token = {"value": None, "expires_at": 0.0}
web_sessions: dict[str, float] = {}
web_sessions_lock = threading.RLock()
local_web_tasks: dict[str, dict] = {}
local_web_tasks_lock = threading.RLock()
cloud_runtime_state = {"last_history_sync": 0.0, "last_error": "", "detected_working": False,
                       "detected_thread_ids": [], "detected_at": 0.0}
message_chat_ids: dict[str, str] = {}
http = requests.Session()
http.mount("https://", HTTPAdapter(max_retries=Retry(
    total=4,
    connect=4,
    read=4,
    status=4,
    backoff_factor=0.6,
    allowed_methods=None,
    status_forcelist=(429, 500, 502, 503, 504),
)))


def is_codex_desktop_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ChatGPT.exe", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "ChatGPT.exe" in result.stdout
    except Exception as error:
        log(f"检测 Codex 客户端状态失败：{error}")
        return False


def bridge_mode() -> dict:
    desktop = is_codex_desktop_running()
    return {
        "mode": "desktop" if desktop else "mobile",
        "desktopRunning": desktop,
        "label": "电脑模式：Codex 客户端优先，飞书只读" if desktop else "手机模式：桥可执行飞书任务",
    }


def account_quota() -> dict:
    with codex_lock:
        result = codex_rpc.call("account/rateLimits/read", {})
    snapshot = result.get("rateLimits") or {}
    primary = snapshot.get("primary") or {}
    used = max(0, min(100, int(primary.get("usedPercent") or 0)))
    return {"available": bool(primary), "usedPercent": used, "remainingPercent": 100 - used,
            "resetsAt": primary.get("resetsAt"), "planType": snapshot.get("planType")}


def reset_codex_rpc(reason: str) -> None:
    global codex_rpc
    with codex_lock:
        try:
            codex_rpc.close()
        except Exception:
            pass
        codex_rpc = CodexRpc()
    log(f"Codex 本地服务已重置：{reason}")


def monitor_desktop_mode() -> None:
    while True:
        desktop = is_codex_desktop_running()
        previous = mode_state.get("desktop_running")
        if previous is None:
            mode_state.update(desktop_running=desktop, mode="desktop" if desktop else "mobile", changed_at=time.time())
            log("进入电脑模式：Codex 客户端优先" if desktop else "进入手机模式：桥可执行飞书任务")
        elif desktop != previous:
            mode_state.update(desktop_running=desktop, mode="desktop" if desktop else "mobile", changed_at=time.time())
            reset_codex_rpc("检测到 Codex 客户端启动，释放桥的写入权" if desktop else "检测到 Codex 客户端退出，启用手机执行模式")
            log("进入电脑模式：Codex 客户端优先" if desktop else "进入手机模式：桥可执行飞书任务")
        time.sleep(5)


def save_state() -> None:
    compact = {
        "owner_open_id": state.get("owner_open_id"),
        "seen_message_ids": list(seen)[-500:],
        "selected_thread_id": state.get("selected_thread_id"),
        "last_thread_ids": state.get("last_thread_ids", []),
        "chat_bindings": state.get("chat_bindings", {}),
        "selected_project_cwd": state.get("selected_project_cwd"),
        "last_project_cwds": state.get("last_project_cwds", []),
    }
    STATE_FILE.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")


def get_feishu_token(force_refresh: bool = False) -> str:
    with feishu_lock:
        now = time.monotonic()
        if not force_refresh and feishu_token["value"] and now < feishu_token["expires_at"]:
            return feishu_token["value"]
        token_response = http.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": APP_ID, "app_secret": APP_SECRET},
            timeout=(10, 20),
        )
        token_response.raise_for_status()
        token_data = token_response.json()
        if token_data.get("code") != 0:
            raise RuntimeError(f"获取飞书令牌失败：{token_data.get('msg')}")
        feishu_token["value"] = token_data["tenant_access_token"]
        expires_in = int(token_data.get("expire", 7200))
        feishu_token["expires_at"] = now + max(60, expires_in - 300)
        return feishu_token["value"]


def reply_text(message_id: str, text: str) -> None:
    reply_message(message_id, "text", {"text": text})


def reply_message(message_id: str, msg_type: str, content: dict) -> None:
    token = get_feishu_token()
    response = http.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        },
        timeout=(10, 30),
    )
    result = response.json()
    if result.get("code") in {99991663, 99991664, 99991668}:
        token = get_feishu_token(force_refresh=True)
        response = http.post(
            f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
            timeout=(10, 30),
        )
        result = response.json()
    if result.get("code") == 230011 and message_chat_ids.get(message_id):
        log(f"原飞书消息已撤回，改为向会话直接发送 message={message_id}")
        send_chat_message(message_chat_ids[message_id], msg_type, content)
        return
    response.raise_for_status()
    if result.get("code") != 0:
        raise RuntimeError(f"回复失败 code={result.get('code')}, msg={result.get('msg')}")


def send_chat_message(chat_id: str, msg_type: str, content: dict) -> None:
    token = get_feishu_token()
    response = http.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={"Authorization": f"Bearer {token}"},
        json={"receive_id": chat_id, "msg_type": msg_type,
              "content": json.dumps(content, ensure_ascii=False)},
        timeout=(10, 30),
    )
    result = response.json()
    response.raise_for_status()
    if result.get("code") != 0:
        raise RuntimeError(f"发送会话消息失败 code={result.get('code')}, msg={result.get('msg')}")


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".ico", ".tiff", ".heic"}
AUTO_UPLOAD_SUFFIXES = IMAGE_SUFFIXES | {
    ".md", ".txt", ".pdf",
    ".doc", ".docx", ".docm", ".dot", ".dotx",
    ".xls", ".xlsx", ".xlsm", ".xlsb", ".csv",
    ".ppt", ".pptx", ".pptm", ".pps", ".ppsx",
}
WINDOWS_PATH_RE = re.compile(r"(?i)(?:[A-Z]:\\[^\r\n<>\"|?*]+)")
DIRECT_FILE_LIMIT = 10 * 1024 * 1024
DIRECT_BATCH_LIMIT = 30 * 1024 * 1024


def existing_attachments(turn: dict) -> tuple[list[Path], list[Path]]:
    displayable: list[Path] = []
    referenced: list[Path] = []
    for item in turn.get("items", []):
        for raw in WINDOWS_PATH_RE.findall(item_text(item)):
            candidate = Path(raw.rstrip(" .,:;，。；：）)]}"))
            if candidate.is_file():
                referenced.append(candidate)
        if item.get("type") == "fileChange":
            for change in item.get("changes", []):
                raw = change.get("path")
                if raw:
                    candidate = Path(raw)
                    if candidate.is_file() and candidate.suffix.lower() in AUTO_UPLOAD_SUFFIXES:
                        displayable.append(candidate)
    displayable.extend(path for path in referenced if path.suffix.lower() in AUTO_UPLOAD_SUFFIXES)

    def unique_paths(paths: list[Path]) -> list[Path]:
        unique, seen_paths = [], set()
        for path in paths:
            resolved = path.resolve()
            key = str(resolved).lower()
            if key not in seen_paths:
                seen_paths.add(key)
                unique.append(resolved)
        return unique[:10]

    displayable_paths = unique_paths(displayable)
    displayable_keys = {str(path).lower() for path in displayable_paths}
    local_only_paths = [path for path in unique_paths(referenced) if str(path).lower() not in displayable_keys]
    return displayable_paths, local_only_paths


def agent_disk_dir() -> Path | None:
    raw = (os.getenv("CODEX_LARGE_FILE_DIR") or "").strip()
    return Path(raw).resolve() if raw else None


def copy_batch_to_agent_disk(paths: list[Path], turn_id: str) -> dict[str, Path]:
    root = agent_disk_dir()
    if not root:
        return {}
    folder = root / "Codex Outputs" / datetime.now().strftime("%Y-%m-%d") / (turn_id[-8:] or secrets.token_hex(4))
    folder.mkdir(parents=True, exist_ok=True)
    copied = {}
    for source in paths:
        target = folder / source.name
        if target.exists() and target.stat().st_size != source.stat().st_size:
            target = folder / f"{source.stem}-{secrets.token_hex(3)}{source.suffix}"
        if source.resolve() != target.resolve() and not target.exists():
            shutil.copy2(source, target)
        copied[str(source.resolve()).lower()] = target
    return copied


def cloud_storage_available(required: int) -> tuple[bool, str]:
    base = cloud_base_url()
    token = (os.getenv("CODEX_HISTORY_SYNC_TOKEN") or "").strip()
    if not base or not token:
        return False, "未配置公网附件服务"
    try:
        response = http.get(f"{base}/api/device/storage", headers={"Authorization": f"Bearer {token}"}, timeout=(10, 30))
        response.raise_for_status()
        data = response.json()
        return bool(data.get("available") and int(data.get("freeBytes") or 0) - required >= 2 * 1024 ** 3), str(data.get("message") or "")
    except Exception as error:
        return False, f"云端存储检查失败：{error}"


def upload_cloud_output(path: Path) -> str:
    base = cloud_base_url()
    token = (os.getenv("CODEX_HISTORY_SYNC_TOKEN") or "").strip()
    stamp = f"{path.resolve()}|{path.stat().st_mtime_ns}|{path.stat().st_size}".encode("utf-8")
    file_id = __import__("hashlib").sha256(stamp).hexdigest()[:32]
    response = http.post(f"{base}/api/device/output-files/{file_id}",
        headers={"Authorization": f"Bearer {token}", "X-File-Name": requests.utils.quote(path.name),
                 "X-File-Mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream"},
        data=path.read_bytes(), timeout=(10, 120))
    response.raise_for_status()
    return file_id


def attachment_plan(turn: dict, upload_cloud: bool = False) -> list[dict]:
    paths, local_only_paths = existing_attachments(turn)
    local_only = [{"name": path.name, "size": path.stat().st_size,
                   "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                   "localPath": str(path), "delivery": "local_only",
                   "reason": "该文件类型不直接上传；文件保存在本机"}
                  for path in local_only_paths]
    if not paths:
        return local_only
    total = sum(path.stat().st_size for path in paths)
    fallback = any(path.stat().st_size > DIRECT_FILE_LIMIT for path in paths) or total > DIRECT_BATCH_LIMIT
    reason = "单文件超过10 MB" if any(path.stat().st_size > DIRECT_FILE_LIMIT for path in paths) else "单次回复附件合计超过30 MB"
    if upload_cloud and not fallback:
        available, storage_message = cloud_storage_available(total)
        if not available:
            fallback, reason = True, storage_message or "云端可用空间不足"
    if upload_cloud and not fallback:
        try:
            cloud_ids = {str(path).lower(): upload_cloud_output(path) for path in paths}
        except Exception as error:
            fallback, reason = True, f"云端附件上传失败：{error}"
            cloud_ids = {}
    else:
        cloud_ids = {}
    copied = copy_batch_to_agent_disk(paths, str(turn.get("id") or "output")) if fallback else {}
    result = []
    for path in paths:
        item = {"name": path.name, "size": path.stat().st_size, "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "localPath": str(path), "delivery": "local", "reason": "文件保存在本机"}
        if fallback:
            target = copied.get(str(path.resolve()).lower())
            item.update({"delivery": "agent_disk" if target else "local_fallback", "agentDiskPath": str(target) if target else None,
                         "reason": reason if target else f"{reason}；未配置 Agent Disk"})
        elif upload_cloud:
            item.update({"delivery": "cloud", "cloudFileId": cloud_ids[str(path).lower()], "reason": "点击查看或下载"})
        else:
            item.update({"delivery": "local", "reason": "点击查看或下载"})
        result.append(item)
    return result + local_only


def enrich_thread_attachments(thread: dict, upload_cloud: bool = False) -> dict:
    for turn in thread.get("turns", []):
        turn["bridgeAttachments"] = attachment_plan(turn, upload_cloud)
    return thread


def upload_feishu_attachment(path: Path) -> tuple[str, dict]:
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"附件为空：{path.name}")
    token = get_feishu_token()
    headers = {"Authorization": f"Bearer {token}"}
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() in IMAGE_SUFFIXES and size <= 10 * 1024 * 1024:
        with path.open("rb") as stream:
            response = http.post("https://open.feishu.cn/open-apis/im/v1/images", headers=headers,
                data={"image_type": "message"}, files={"image": (path.name, stream, mime)}, timeout=(10, 120))
        result = response.json()
        if result.get("code") == 99991672:
            raise RuntimeError("飞书应用缺少 im:resource:upload（上传图片或文件资源）权限")
        response.raise_for_status()
        if result.get("code") != 0:
            raise RuntimeError(f"飞书图片上传失败：{result.get('msg')}")
        return "image", {"image_key": result["data"]["image_key"]}
    if size > 30 * 1024 * 1024:
        raise RuntimeError(f"{path.name} 超过飞书 30 MB 文件限制")
    with path.open("rb") as stream:
        response = http.post("https://open.feishu.cn/open-apis/im/v1/files", headers=headers,
            data={"file_type": "stream", "file_name": path.name},
            files={"file": (path.name, stream, mime)}, timeout=(10, 180))
    result = response.json()
    if result.get("code") == 99991672:
        raise RuntimeError("飞书应用缺少 im:resource:upload（上传图片或文件资源）权限")
    response.raise_for_status()
    if result.get("code") != 0:
        raise RuntimeError(f"飞书文件上传失败：{result.get('msg')}")
    return "file", {"file_key": result["data"]["file_key"]}


def list_threads(limit: int = 10) -> list:
    with codex_lock:
        result = codex_rpc.call("thread/list", {
            "limit": limit,
            "sortKey": "updated_at",
            "sortDirection": "desc",
            "archived": False,
        })
    return result.get("data", [])


def list_threads_page(limit: int = 50, cursor: str | None = None) -> dict:
    params = {
        "limit": limit,
        "sortKey": "updated_at",
        "sortDirection": "desc",
        "archived": False,
    }
    if cursor:
        params["cursor"] = cursor
    with codex_lock:
        return codex_rpc.call("thread/list", params)


def read_thread(thread_id: str) -> dict:
    with codex_lock:
        result = codex_rpc.call("thread/read", {
            "threadId": thread_id,
            "includeTurns": True,
        })
    return result.get("thread", {})


class DashboardHandler(BaseHTTPRequestHandler):
    def is_local_request(self) -> bool:
        host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
        return host in {"127.0.0.1", "localhost", "[::1]"}

    def session_token(self) -> str:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
            return cookie.get("bridge_session").value if cookie.get("bridge_session") else ""
        except Exception:
            return ""

    def is_authenticated(self) -> bool:
        if self.is_local_request():
            return True
        token = self.session_token()
        with web_sessions_lock:
            expires_at = web_sessions.get(token, 0)
            if expires_at > time.time():
                return True
            web_sessions.pop(token, None)
        return False

    def require_auth(self) -> bool:
        if self.is_authenticated():
            return True
        self.send_json({"error": "feishu_login_required"}, 401)
        return False

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/config":
                self.send_json({
                    "appId": APP_ID,
                    "authRequired": not self.is_local_request(),
                    "authenticated": self.is_authenticated(),
                    "ownerConfigured": bool(state.get("owner_open_id")),
                    "projectsRoot": os.getenv("CODEX_PROJECTS_ROOT") or str(ROOT.parent / "CodexProjects"),
                    "standaloneDir": os.getenv("CODEX_STANDALONE_DIR") or str(DATA_DIR / "standalone"),
                })
                return
            if parsed.path.startswith("/api/") and not self.require_auth():
                return
            if parsed.path == "/api/threads":
                query = parse_qs(parsed.query)
                limit = min(max(int(query.get("limit", [50])[0]), 1), 100)
                cursor = query.get("cursor", [None])[0]
                result = list_threads_page(limit, cursor)
                threads = result.get("data", [])
                self.send_json({"threads": [{
                    "id": item.get("id"),
                    "name": item.get("name") or "未命名对话",
                    "cwd": item.get("cwd"),
                    "status": item.get("status"),
                    "preview": item.get("preview"),
                    "updatedAt": item.get("updatedAt"),
                } for item in threads], "nextCursor": result.get("nextCursor")})
                return
            if parsed.path == "/api/status":
                self.send_json(bridge_mode())
                return
            if parsed.path == "/api/quota":
                self.send_json(account_quota())
                return
            if parsed.path.startswith("/api/local-task/"):
                task_id = parsed.path.removeprefix("/api/local-task/")
                with local_web_tasks_lock:
                    task = dict(local_web_tasks.get(task_id) or {})
                self.send_json(task or {"error": "task_not_found"}, 200 if task else 404)
                return
            if parsed.path in {"/api/attachment", "/api/open-attachment"}:
                raw_path = parse_qs(parsed.query).get("path", [""])[0]
                file_path = Path(raw_path).resolve()
                if not file_path.is_file():
                    self.send_error(404, "Attachment not found")
                    return
                if parsed.path == "/api/open-attachment":
                    os.startfile(str(file_path))
                    self.send_json({"ok": True})
                    return
                body = file_path.read_bytes()
                content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{requests.utils.quote(file_path.name)}")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.startswith("/api/thread/"):
                thread_id = parsed.path.removeprefix("/api/thread/")
                thread = enrich_thread_attachments(read_thread(thread_id), False)
                self.send_json({"thread": thread})
                return
            if parsed.path in {"/", "/index.html"}:
                file_path = WEB_DIR / "index.html"
            else:
                file_path = WEB_DIR / parsed.path.lstrip("/")
            if not file_path.is_file() or WEB_DIR not in file_path.resolve().parents:
                self.send_error(404)
                return
            body = file_path.read_bytes()
            content_type = "text/css" if file_path.suffix == ".css" else "application/javascript" if file_path.suffix == ".js" else "text/html"
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as error:
            log(f"只读界面请求失败：{error}")
            self.send_json({"error": str(error)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/feishu":
                size = min(int(self.headers.get("Content-Length") or 0), 8192)
                payload = json.loads(self.rfile.read(size) or b"{}")
                code = str(payload.get("code") or "").strip()
                if not code:
                    self.send_json({"error": "missing_code"}, 400)
                    return
                app_response = http.post(
                    "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal",
                    json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=(10, 20),
                )
                app_response.raise_for_status()
                app_data = app_response.json()
                if app_data.get("code") != 0:
                    raise RuntimeError(f"获取应用令牌失败：{app_data.get('msg')}")
                user_response = http.post(
                    "https://open.feishu.cn/open-apis/authen/v1/access_token",
                    headers={"Authorization": f"Bearer {app_data['app_access_token']}",
                             "Content-Type": "application/json; charset=utf-8"},
                    json={"grant_type": "authorization_code", "code": code}, timeout=(10, 20),
                )
                user_response.raise_for_status()
                user_data = user_response.json()
                if user_data.get("code") != 0:
                    raise RuntimeError(f"飞书免登失败：{user_data.get('msg')}")
                identity = user_data.get("data") or {}
                open_id = identity.get("open_id")
                owner = state.get("owner_open_id")
                if not owner or not open_id or open_id != owner:
                    log(f"网页应用拒绝非所有者登录：open_id={open_id or 'missing'}")
                    self.send_json({"error": "owner_mismatch"}, 403)
                    return
                token = secrets.token_urlsafe(32)
                with web_sessions_lock:
                    now = time.time()
                    for old_token, expiry in list(web_sessions.items()):
                        if expiry <= now:
                            web_sessions.pop(old_token, None)
                    web_sessions[token] = now + 12 * 60 * 60
                body = json.dumps({"ok": True, "name": identity.get("name") or "飞书用户"}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                secure = "; Secure" if not self.is_local_request() else ""
                self.send_header("Set-Cookie", f"bridge_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200{secure}")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/auth/logout":
                token = self.session_token()
                with web_sessions_lock:
                    web_sessions.pop(token, None)
                self.send_response(204)
                self.send_header("Set-Cookie", "bridge_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
                self.end_headers()
                return
            if parsed.path == "/api/local-tasks":
                if not self.is_local_request():
                    self.send_json({"error": "local_only"}, 403)
                    return
                size = min(int(self.headers.get("Content-Length") or 0), 24 * 1024 * 1024)
                payload = json.loads(self.rfile.read(size) or b"{}")
                operation = str(payload.get("op") or "message").strip()
                thread_id = str(payload.get("threadId") or "").strip()
                text = str(payload.get("text") or "").strip()
                if operation == "new_thread":
                    if not text or not str(payload.get("cwd") or "").strip() or not str(payload.get("title") or "").strip():
                        self.send_json({"error": "missing_new_thread_fields"}, 400)
                        return
                elif not thread_id or not text:
                    self.send_json({"error": "missing_thread_or_text"}, 400)
                    return
                task_id = secrets.token_urlsafe(12)
                with local_web_tasks_lock:
                    local_web_tasks[task_id] = {"id": task_id, "status": "queued", "message": "已提交到本机桥"}
                threading.Thread(target=execute_local_web_task,
                                 args=(task_id, thread_id, text, payload.get("files") or [], operation,
                                       str(payload.get("cwd") or ""), str(payload.get("title") or "")), daemon=True).start()
                self.send_json({"taskId": task_id})
                return
            self.send_error(404)
        except Exception as error:
            log(f"飞书网页认证失败：{error}")
            self.send_json({"error": "feishu_auth_failed", "message": str(error)}, 502)

    def log_message(self, *_):
        return


def set_local_web_task(task_id: str, **values) -> None:
    with local_web_tasks_lock:
        task = local_web_tasks.setdefault(task_id, {"id": task_id})
        task.update(values)


def execute_local_web_task(task_id: str, thread_id: str, text: str, files: list,
                           operation: str = "message", cwd_value: str = "", title: str = "") -> None:
    """Run a localhost UI request without requiring the cloud relay."""
    try:
        if operation == "new_thread":
            cwd = Path(cwd_value.strip())
            if not cwd.is_absolute():
                raise RuntimeError("项目目录必须是本机绝对路径")
            cwd.mkdir(parents=True, exist_ok=True)
            set_local_web_task(task_id, status="running", message="正在创建新对话")
            with codex_lock:
                result = codex_rpc.call("thread/start", {"cwd": str(cwd), "sandbox": "danger-full-access",
                                                         "approvalPolicy": "never", "ephemeral": False})
                thread_id = (result.get("thread") or {}).get("id")
                if not thread_id:
                    raise RuntimeError("Codex 没有返回新对话 ID")
                codex_rpc.call("thread/name/set", {"threadId": thread_id, "name": title.strip()})
            set_local_web_task(task_id, status="running", message="新对话已创建，正在发送第一条消息",
                               threadId=thread_id, title=title.strip(), cwd=str(cwd))
        if not is_valid_thread_id(thread_id):
            raise RuntimeError("所选条目不是有效的 Codex 对话，请刷新列表后重新选择")
        saved_files = []
        day_dir = WEB_INBOX_DIR / datetime.now().strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        for item in files[:3]:
            name = Path(str(item.get("name") or "attachment.bin")).name
            raw = base64.b64decode(str(item.get("data") or ""), validate=True)
            if len(raw) > 10 * 1024 * 1024:
                raise RuntimeError("单个附件不能超过 10 MB")
            target = day_dir / f"{secrets.token_hex(5)}-{name}"
            target.write_bytes(raw)
            saved_files.append(target)
        if saved_files:
            text += "\n\n我从本地网页上传了以下文件，请读取并处理：\n" + "\n".join(str(path) for path in saved_files)
        codex_input = [{"type": "text", "text": text, "text_elements": []}]
        for path in saved_files:
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
                codex_input.append({"type": "localImage", "path": str(path)})
        set_local_web_task(task_id, status="running", message="Codex 正在处理")
        with codex_lock:
            active_turn_id = active_turns.get(thread_id)
            if not active_turn_id:
                snapshot = read_thread(thread_id)
                for candidate in reversed(snapshot.get("turns", [])):
                    status = candidate.get("status")
                    status_name = status.get("type") if isinstance(status, dict) else status
                    if status_name not in {"completed", "failed", "interrupted", "cancelled"}:
                        active_turn_id = candidate.get("id")
                        break
            if active_turn_id:
                try:
                    codex_rpc.call("turn/steer", {"threadId": thread_id, "expectedTurnId": active_turn_id, "input": codex_input})
                    set_local_web_task(task_id, status="completed", message="已作为补充引导追加", turnId=active_turn_id, steered=True)
                    return
                except RuntimeError:
                    if active_turns.get(thread_id) == active_turn_id:
                        active_turns.pop(thread_id, None)
            before = read_thread(thread_id)
            previous_turn_ids = {turn.get("id") for turn in before.get("turns", [])}
            codex_rpc.call("thread/resume", {"threadId": thread_id, "sandbox": "danger-full-access", "approvalPolicy": "never"})
            result = codex_rpc.call("turn/start", {"threadId": thread_id, "input": codex_input})
            turn_id = (result.get("turn") or {}).get("id")
            if turn_id:
                active_turns[thread_id] = turn_id
        set_local_web_task(task_id, status="started", message="Codex 已开始处理", turnId=turn_id)
        deadline = time.monotonic() + 1800
        last_progress = ""
        while time.monotonic() < deadline:
            time.sleep(1)
            thread = read_thread(thread_id)
            target = next((item for item in reversed(thread.get("turns", [])) if item.get("id") == turn_id), None)
            if target is None:
                target = next((item for item in reversed(thread.get("turns", [])) if item.get("id") not in previous_turn_ids), None)
            if not target:
                continue
            status = target.get("status")
            status_name = status.get("type") if isinstance(status, dict) else status
            progress = turn_progress_summary(target)
            if progress and progress != last_progress:
                set_local_web_task(task_id, status="running", message=f"Codex 正在处理\n\n{progress[:12000]}", turnId=turn_id)
                last_progress = progress
            if status_name in {"completed", "failed", "interrupted", "cancelled"}:
                with codex_lock:
                    if active_turns.get(thread_id) == turn_id:
                        active_turns.pop(thread_id, None)
                set_local_web_task(task_id, status="completed" if status_name == "completed" else "failed",
                                   message="任务已完成" if status_name == "completed" else f"任务已结束：{status_name}", turnId=turn_id)
                return
        raise RuntimeError("Codex 执行超过30分钟")
    except Exception as error:
        log(f"本地网页任务失败 {task_id}: {error}")
        set_local_web_task(task_id, status="failed", message=str(error))


def start_dashboard():
    server = ThreadingHTTPServer(("127.0.0.1", 8765), DashboardHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log("只读管理界面已启动：http://127.0.0.1:8765")
    return server


def sync_cloud_history() -> None:
    """Push text-only Codex history to the isolated cloud viewer."""
    url = (os.getenv("CODEX_HISTORY_URL") or "").strip()
    token = (os.getenv("CODEX_HISTORY_SYNC_TOKEN") or "").strip()
    ssh_host = (os.getenv("CODEX_HISTORY_SSH_HOST") or "").strip()
    ssh_key = (os.getenv("CODEX_HISTORY_SSH_KEY") or "").strip()
    if not url or not token:
        return
    last_hashes = {}
    cached_quota = None
    next_quota_read = 0.0
    while True:
        try:
            page = list_threads_page(50, None)
            changed = []
            pending_hashes = {}
            detected_working = False
            detected_thread_ids = []
            for summary in page.get("data", []):
                thread_id = summary.get("id")
                if not thread_id:
                    continue
                thread = enrich_thread_attachments(read_thread(thread_id), True)
                for turn in thread.get("turns", []):
                    turn_status = turn.get("status")
                    turn_status = turn_status.get("type") if isinstance(turn_status, dict) else turn_status
                    if turn_status in {"inProgress", "in_progress", "running", "active", "started"}:
                        detected_working = True
                        detected_thread_ids.append(thread_id)
                        break
                raw = json.dumps(thread, ensure_ascii=False, sort_keys=True, default=str)
                digest = __import__("hashlib").sha256(raw.encode("utf-8")).hexdigest()
                if last_hashes.get(thread_id) != digest:
                    changed.append(thread)
                    pending_hashes[thread_id] = digest
            if time.monotonic() >= next_quota_read:
                try:
                    fresh_quota = account_quota()
                    if fresh_quota.get("available"):
                        cached_quota = fresh_quota
                    next_quota_read = time.monotonic() + 300
                except Exception as quota_error:
                    log(f"额度读取暂时失败，继续使用缓存：{quota_error}")
                    next_quota_read = time.monotonic() + 60
            payload = {"threads": changed, "quota": cached_quota}
            try:
                response = http.post(url, headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=(10, 60))
                response.raise_for_status()
            except Exception as https_error:
                if not (ssh_host and ssh_key):
                    raise
                log(f"HTTPS 历史同步暂时失败，改用 SSH 备用通道：{https_error}")
                result = subprocess.run(
                    ["ssh", "-i", ssh_key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                     ssh_host, "python3 /opt/codex-history/import_sync.py"],
                    input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True,
                    encoding="utf-8", errors="replace", timeout=90,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or f"SSH 同步退出码 {result.returncode}")
            last_hashes.update(pending_hashes)
            cloud_runtime_state.update(last_history_sync=time.time(), last_error="",
                                       detected_working=detected_working,
                                       detected_thread_ids=detected_thread_ids, detected_at=time.time())
        except Exception as error:
            cloud_runtime_state["last_error"] = str(error)[:300]
            log(f"云端只读历史同步失败：{error}")
        time.sleep(2 if active_turns else 5)


def cloud_base_url() -> str:
    sync_url = (os.getenv("CODEX_HISTORY_URL") or "").strip().rstrip("/")
    return sync_url.split("/api/", 1)[0] if "/api/" in sync_url else sync_url


def cloud_heartbeat_worker() -> None:
    """Report liveness independently so slow history reads cannot look like an outage."""
    base = cloud_base_url()
    token = (os.getenv("CODEX_HISTORY_SYNC_TOKEN") or "").strip()
    if not base or not token:
        return
    while True:
        try:
            last_sync = float(cloud_runtime_state.get("last_history_sync") or 0)
            detected_recently = bool(cloud_runtime_state.get("detected_working")) and time.time() - float(cloud_runtime_state.get("detected_at") or 0) < 120
            active_thread_ids = list(dict.fromkeys(list(active_turns) +
                (list(cloud_runtime_state.get("detected_thread_ids") or []) if detected_recently else [])))
            response = requests.post(f"{base}/api/device/heartbeat",
                headers={"Authorization": f"Bearer {token}"},
                json={"working": bool(active_thread_ids) or bool(active_turns) or detected_recently,
                      "activeThreadIds": active_thread_ids,
                      "historySyncAge": max(0, int(time.time() - last_sync)) if last_sync else None,
                      "historyError": cloud_runtime_state.get("last_error") or ""}, timeout=(8, 15))
            response.raise_for_status()
        except Exception as error:
            log(f"云端心跳暂时失败：{error}")
        time.sleep(10)


def cloud_task_report(task_id: str, kind: str, payload: dict, status: str | None = None,
                      result: str | None = None, error: str | None = None) -> None:
    base = cloud_base_url()
    token = (os.getenv("CODEX_HISTORY_SYNC_TOKEN") or "").strip()
    if not base or not token:
        return
    body = {"kind": kind, "payload": payload}
    if status:
        body["status"] = status
    if result is not None:
        body["result"] = result
    if error is not None:
        body["error"] = error
    response = http.post(f"{base}/api/device/tasks/{task_id}",
                         headers={"Authorization": f"Bearer {token}"}, json=body, timeout=(10, 30))
    response.raise_for_status()


def download_cloud_task_files(task: dict) -> list[Path]:
    base = cloud_base_url()
    token = (os.getenv("CODEX_HISTORY_SYNC_TOKEN") or "").strip()
    folder = WEB_INBOX_DIR / datetime.now().strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    received_ids = []
    for item in task.get("files") or []:
        safe_name = re.sub(r'[^\w.()\-\u4e00-\u9fff]+', '_', str(item.get("name") or "file"), flags=re.UNICODE).strip('._') or "file"
        target = folder / f"{task['id'][-10:]}-{safe_name}"
        response = http.get(f"{base}/api/device/files/{item['id']}",
                            headers={"Authorization": f"Bearer {token}"}, timeout=(10, 90), stream=True)
        response.raise_for_status()
        size = 0
        with target.open("wb") as file:
            for chunk in response.iter_content(256 * 1024):
                size += len(chunk)
                if size > 10 * 1024 * 1024:
                    raise RuntimeError("网页附件超过10 MB限制")
                file.write(chunk)
        paths.append(target)
        received_ids.append(item["id"])
    if received_ids:
        cloud_task_report(task["id"], "files_received", {"fileIds": received_ids,
                          "message": "附件已安全下载到本机，云端临时副本已删除"})
    return paths


def execute_cloud_task(task: dict) -> None:
    task_id = task["id"]
    try:
        operation = task.get("op") or "message"
        if operation == "new_thread":
            cloud_task_report(task_id, "status", {"message": "正在创建新对话"}, "running")
            cwd = Path(str(task.get("cwd") or "").strip())
            if not cwd.is_absolute():
                raise RuntimeError("项目目录必须是本机绝对路径")
            cwd.mkdir(parents=True, exist_ok=True)
            with codex_lock:
                result = codex_rpc.call("thread/start", {
                    "cwd": str(cwd), "sandbox": "danger-full-access",
                    "approvalPolicy": "never", "ephemeral": False,
                })
                thread_id = (result.get("thread") or {}).get("id")
                if not thread_id:
                    raise RuntimeError("Codex 没有返回新对话 ID")
                codex_rpc.call("thread/name/set", {"threadId": thread_id, "name": task["title"]})
            cloud_task_report(task_id, "created", {"message": "新对话已创建", "threadId": thread_id,
                              "title": task["title"], "cwd": str(cwd)}, "running")
            if not (task.get("text") or "").strip():
                cloud_task_report(task_id, "completed", {"message": "新对话已创建", "threadId": thread_id},
                                  "completed", result=thread_id)
                return
            task = dict(task)
            task["threadId"] = thread_id

        thread_id = task.get("threadId")
        text = (task.get("text") or "").strip()
        if not thread_id or not text:
            raise RuntimeError("网页任务缺少对话或文字")
        if not is_valid_thread_id(thread_id):
            raise RuntimeError("所选条目不是有效的 Codex 对话，请刷新列表后重新选择")
        local_files = download_cloud_task_files(task)
        if local_files:
            text += "\n\n我从网页端上传了以下本机临时文件，请读取并处理：\n" + "\n".join(str(path) for path in local_files)
        codex_input = [{"type": "text", "text": text, "text_elements": []}]
        for path in local_files:
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
                codex_input.append({"type": "localImage", "path": str(path)})
        cloud_task_report(task_id, "status", {"message": "本机桥已接收任务"}, "running")

        with codex_lock:
            active_turn_id = active_turns.get(thread_id)
            if not active_turn_id:
                snapshot = read_thread(thread_id)
                for candidate in reversed(snapshot.get("turns", [])):
                    status = candidate.get("status")
                    status_name = status.get("type") if isinstance(status, dict) else status
                    if status_name not in {"completed", "failed", "interrupted", "cancelled"}:
                        active_turn_id = candidate.get("id")
                        break
            if active_turn_id:
                codex_rpc.call("turn/steer", {"threadId": thread_id, "expectedTurnId": active_turn_id,
                                               "input": codex_input})
                cloud_task_report(task_id, "steered", {"message": "已作为补充引导追加到当前任务",
                                  "turnId": active_turn_id}, "completed", result="steered")
                return

            before = read_thread(thread_id)
            previous_turn_ids = {turn.get("id") for turn in before.get("turns", [])}
            codex_rpc.call("thread/resume", {"threadId": thread_id, "sandbox": "danger-full-access",
                                             "approvalPolicy": "never"})
            result = codex_rpc.call("turn/start", {"threadId": thread_id, "input": codex_input})
            turn_id = (result.get("turn") or {}).get("id")
            if turn_id:
                active_turns[thread_id] = turn_id
        cloud_task_report(task_id, "started", {"message": "Codex 已开始处理", "turnId": turn_id}, "running")

        deadline = time.monotonic() + 1800
        last_progress = ""
        while time.monotonic() < deadline:
            time.sleep(1)
            thread = read_thread(thread_id)
            turns = thread.get("turns", [])
            target = next((item for item in reversed(turns) if item.get("id") == turn_id), None)
            if target is None:
                target = next((item for item in reversed(turns) if item.get("id") not in previous_turn_ids), None)
            if not target:
                continue
            status = target.get("status")
            status_name = status.get("type") if isinstance(status, dict) else status
            progress = turn_progress_summary(target)
            if progress and progress != last_progress:
                cloud_task_report(task_id, "progress", {"summary": progress[:12000], "turnId": turn_id})
                last_progress = progress
            if status_name in {"completed", "failed", "interrupted", "cancelled"}:
                with codex_lock:
                    if active_turns.get(thread_id) == turn_id:
                        active_turns.pop(thread_id, None)
                _, answer = turn_pair(target)
                final_status = "completed" if status_name == "completed" else "failed"
                cloud_task_report(task_id, "final", {"answer": answer, "turnId": turn_id,
                                  "codexStatus": status_name}, final_status, result=answer,
                                  error=None if final_status == "completed" else status_name)
                return
        raise RuntimeError("Codex 执行超过30分钟")
    except Exception as error:
        log(f"网页任务处理失败 {task_id}: {error}")
        try:
            cloud_task_report(task_id, "error", {"message": str(error)}, "failed", error=str(error))
        except Exception as report_error:
            log(f"网页任务错误状态回传失败 {task_id}: {report_error}")


def cloud_task_worker() -> None:
    base = cloud_base_url()
    token = (os.getenv("CODEX_HISTORY_SYNC_TOKEN") or "").strip()
    if not base or not token:
        return
    while True:
        try:
            response = http.get(f"{base}/api/device/tasks",
                                headers={"Authorization": f"Bearer {token}"}, timeout=(10, 30))
            response.raise_for_status()
            task = response.json().get("task")
            if task:
                threading.Thread(target=execute_cloud_task, args=(task,), daemon=True).start()
                time.sleep(0.15)
                continue
        except Exception as error:
            log(f"网页任务通道暂时不可用：{error}")
        time.sleep(1)


def item_text(item: dict) -> str:
    if item.get("type") == "userMessage":
        return "\n".join(
            part.get("text", "") for part in item.get("content", [])
            if part.get("type") == "text"
        ).strip()
    if item.get("type") == "agentMessage":
        return (item.get("text") or "").strip()
    return ""


def turn_pair(turn: dict) -> tuple[str, str]:
    user_text = ""
    agent_messages = []
    for item in turn.get("items", []):
        text = item_text(item)
        if item.get("type") == "userMessage" and text:
            user_text = text
        elif item.get("type") == "agentMessage" and text:
            agent_messages.append((item.get("phase"), text))
    final_candidates = [text for phase, text in agent_messages if phase != "commentary"]
    agent_text = (final_candidates or [text for _, text in agent_messages] or [""])[-1]
    return user_text, agent_text


def turn_progress_summary(turn: dict) -> str:
    """Return the first user-readable plan/progress note for Feishu."""
    for item in turn.get("items", []):
        if item.get("type") == "agentMessage" and item.get("phase") == "commentary":
            text = item_text(item)
            if text:
                return text
    for item in turn.get("items", []):
        if item.get("type") != "reasoning":
            continue
        value = item.get("summary") or item.get("summaries") or item.get("text") or ""
        if isinstance(value, list):
            parts = []
            for part in value:
                parts.append(part if isinstance(part, str) else str(part.get("text") or ""))
            value = "\n\n".join(part for part in parts if part)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def turn_live_summary(turn: dict) -> str:
    """Build the user-visible incremental timeline used by the web client."""
    parts = []
    for item in turn.get("items", []):
        item_type = item.get("type")
        if item_type == "agentMessage" and item.get("phase") == "commentary":
            value = item_text(item).strip()
            if value:
                parts.append(value)
        elif item_type == "reasoning":
            value = item.get("summary") or item.get("summaries") or item.get("text") or ""
            if isinstance(value, list):
                value = "\n\n".join(part if isinstance(part, str) else str(part.get("text") or "") for part in value)
            if isinstance(value, str) and value.strip():
                parts.append("推理摘要：\n" + value.strip())
        elif item_type in {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall"}:
            label = {"commandExecution": "终端操作", "fileChange": "文件修改",
                     "mcpToolCall": "工具调用", "dynamicToolCall": "工具调用"}[item_type]
            status = item.get("status") or item.get("state") or "进行中"
            parts.append(f"{label} · {status}")
    unique = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    return "\n\n".join(unique)[-12000:]


def selected_thread_id(chat_id: str | None = None) -> str | None:
    bindings = state.get("chat_bindings", {})
    return bindings.get(chat_id) if chat_id and bindings.get(chat_id) else state.get("selected_thread_id")


def current_thread(chat_id: str | None = None) -> dict | None:
    selected = selected_thread_id(chat_id)
    if not selected:
        return None
    try:
        return read_thread(selected)
    except Exception:
        return None


def format_threads(threads: list, chat_id: str | None = None) -> str:
    selected = selected_thread_id(chat_id)
    lines = ["最近的 Codex 对话："]
    for index, thread in enumerate(threads, 1):
        marker = " ✓" if thread.get("id") == selected else ""
        name = thread.get("name") or "未命名对话"
        status = thread.get("status") or "未知"
        lines.append(f"{index}. {name}{marker}\n   状态：{status}")
    lines.append("\n单聊发送 /选择 2；群聊发送 /绑定 2")
    return "\n".join(lines)


def handle_command(message_id: str, chat_id: str, chat_type: str, text: str) -> bool:
    stripped = text.strip()
    if stripped in {"/任务", "/对话", "/列表"}:
        threads = list_threads(10)
        state["last_thread_ids"] = [item.get("id") for item in threads]
        save_state()
        reply_text(message_id, format_threads(threads, chat_id))
        return True

    if stripped.startswith("/选择"):
        argument = stripped[len("/选择"):].strip()
        thread_id = None
        if argument.isdigit():
            index = int(argument) - 1
            current_threads = list_threads(max(index + 1, 50))
            if 0 <= index < len(current_threads):
                thread_id = current_threads[index].get("id")
        elif argument:
            thread_id = argument
        if not thread_id:
            reply_text(message_id, "没有找到这个编号。请先发送 /任务 获取最新列表。")
            return True
        thread = read_thread(thread_id)
        state["selected_thread_id"] = thread_id
        save_state()
        reply_text(message_id, f"已选择：{thread.get('name') or '未命名对话'}\n对话 ID：{thread_id}\n目录：{thread.get('cwd') or '未知'}")
        return True

    if stripped.startswith("/绑定"):
        argument = stripped[len("/绑定"):].strip()
        thread_id = None
        if argument.isdigit():
            index = int(argument) - 1
            current_threads = list_threads(max(index + 1, 50))
            if 0 <= index < len(current_threads):
                thread_id = current_threads[index].get("id")
        elif argument:
            thread_id = argument
        if not thread_id:
            reply_text(message_id, "没有找到这个编号。请先发送 /任务。")
            return True
        thread = read_thread(thread_id)
        state.setdefault("chat_bindings", {})[chat_id] = thread_id
        save_state()
        number_text = f"\n实时序号：{int(argument)}" if argument.isdigit() else ""
        reply_text(message_id, f"当前飞书对话已绑定：{thread.get('name') or '未命名对话'}{number_text}\n对话 ID：{thread_id}\n以后直接发消息即可继续它。")
        return True

    if stripped == "/解绑":
        removed = state.setdefault("chat_bindings", {}).pop(chat_id, None)
        save_state()
        reply_text(message_id, "当前飞书对话已解绑。" if removed else "当前飞书对话没有独立绑定。")
        return True

    if stripped in {"/项目", "/项目列表"}:
        threads = list_threads(100)
        cwds = []
        for thread in threads:
            cwd = thread.get("cwd")
            if cwd and cwd not in cwds:
                cwds.append(cwd)
        state["last_project_cwds"] = cwds
        save_state()
        lines = ["可用于新对话的项目目录："]
        for index, cwd in enumerate(cwds, 1):
            marker = " ✓" if cwd == state.get("selected_project_cwd") else ""
            lines.append(f"{index}. {cwd}{marker}")
        lines.append("\n发送 /项目选择 2")
        reply_text(message_id, "\n".join(lines)[:12000])
        return True

    if stripped.startswith("/项目选择"):
        argument = stripped[len("/项目选择"):].strip()
        if not argument.isdigit():
            reply_text(message_id, "格式：/项目选择 2。请先发送 /项目。")
            return True
        index = int(argument) - 1
        cwds = state.get("last_project_cwds", [])
        if not (0 <= index < len(cwds)):
            reply_text(message_id, "没有找到这个项目编号。请重新发送 /项目。")
            return True
        state["selected_project_cwd"] = cwds[index]
        save_state()
        reply_text(message_id, f"新对话项目已选择：\n{cwds[index]}")
        return True

    if stripped.startswith("/新建"):
        title = stripped[len("/新建"):].strip()
        if not title:
            reply_text(message_id, "格式：/新建 对话标题\n首次使用请先发送 /项目 并选择项目。")
            return True
        if is_codex_desktop_running():
            reply_text(message_id, "当前是电脑模式：Codex 客户端正在运行。请完全退出客户端后再从飞书新建对话。")
            return True
        cwd = state.get("selected_project_cwd")
        if not cwd:
            active = current_thread(chat_id)
            cwd = active.get("cwd") if active else None
        if not cwd:
            reply_text(message_id, "尚未选择项目。请先发送 /项目，再发送 /项目选择 编号。")
            return True
        with codex_lock:
            result = codex_rpc.call("thread/start", {
                "cwd": cwd,
                "sandbox": "danger-full-access",
                "approvalPolicy": "never",
                "ephemeral": False,
            })
            new_thread = result.get("thread", {})
            new_id = new_thread.get("id")
            if not new_id:
                raise RuntimeError("Codex 没有返回新对话 ID")
            codex_rpc.call("thread/name/set", {"threadId": new_id, "name": title})
        if chat_type == "p2p":
            state["selected_thread_id"] = new_id
        else:
            state.setdefault("chat_bindings", {})[chat_id] = new_id
        save_state()
        reply_text(message_id, f"已新建 Codex 对话：{title}\n项目：{cwd}\n当前飞书对话已自动切换到它。")
        return True

    if stripped == "/当前":
        mode = bridge_mode()["label"]
        thread = current_thread(chat_id)
        if not thread:
            reply_text(message_id, f"{mode}\n\n尚未选择对话。请发送 /任务。")
        else:
            reply_text(message_id, f"{mode}\n\n当前对话：{thread.get('name') or '未命名对话'}\n状态：{thread.get('status') or '未知'}\n目录：{thread.get('cwd') or '未知'}")
        return True

    if stripped.startswith("/历史"):
        thread = current_thread(chat_id)
        if not thread:
            reply_text(message_id, "尚未选择对话。请发送 /任务。")
            return True
        argument = stripped[len("/历史"):].strip()
        count = min(max(int(argument) if argument.isdigit() else 3, 1), 10)
        turns = thread.get("turns", [])[-count:]
        blocks = [f"{thread.get('name') or '当前对话'}｜最近 {len(turns)} 轮"]
        for turn in turns:
            user_text, agent_text = turn_pair(turn)
            blocks.append(f"你：{user_text[:1000] or '（无文字）'}\nCodex：{agent_text[:2500] or '（尚无最终回复）'}")
        reply_text(message_id, "\n\n".join(blocks)[:12000])
        return True

    if stripped in {"/帮助", "/help"}:
        reply_text(message_id, "可用命令：\n/任务\n/选择 2（单聊）\n/绑定 2（群聊）\n/解绑\n/当前\n/历史 5\n/项目\n/项目选择 2\n/新建 对话标题\n\n选择或绑定后，直接发送普通文字即可继续 Codex 对话。")
        return True
    return False


def send_to_codex(message_id: str, chat_id: str, text: str, codex_input: list | None = None) -> None:
    thread_id = selected_thread_id(chat_id)
    if not thread_id:
        reply_text(message_id, "尚未选择 Codex 对话。请先发送 /任务，再发送 /选择 编号。")
        return
    if is_codex_desktop_running():
        reply_text(message_id, "当前是电脑模式：Codex 客户端正在运行并拥有优先权。桥没有发送这条指令。完全退出 Codex 客户端后，桥会自动切换到手机模式。")
        return

    # Recover active state from Codex itself after a bridge restart or an RPC hiccup.
    codex_input = codex_input or [{"type": "text", "text": text, "text_elements": []}]
    with codex_lock:
        active_turn_id = active_turns.get(thread_id)
        if not active_turn_id:
            snapshot = read_thread(thread_id)
            for candidate in reversed(snapshot.get("turns", [])):
                status = candidate.get("status")
                status_name = status.get("type") if isinstance(status, dict) else status
                if status_name not in {"completed", "failed", "interrupted", "cancelled"}:
                    active_turn_id = candidate.get("id")
                    if active_turn_id:
                        active_turns[thread_id] = active_turn_id
                    break
        if active_turn_id:
            try:
                codex_rpc.call("turn/steer", {
                    "threadId": thread_id,
                    "expectedTurnId": active_turn_id,
                    "input": codex_input,
                })
                log(f"已向运行中回合追加引导 thread={thread_id} turn={active_turn_id}")
                reply_text(message_id, "已追加到当前正在运行的任务。Codex 会结合这条补充继续处理。")
                return
            except RuntimeError as error:
                # The turn may have completed between message receipt and steering.
                log(f"追加引导时原回合已不可用，将自动启动新回合：{error}")
                if active_turns.get(thread_id) == active_turn_id:
                    active_turns.pop(thread_id, None)

        before = read_thread(thread_id)
        previous_turn_ids = {turn.get("id") for turn in before.get("turns", [])}
        try:
            codex_rpc.call("thread/resume", {
                "threadId": thread_id,
                "sandbox": "danger-full-access",
                "approvalPolicy": "never",
            })
        except RuntimeError as error:
            if "already has an active writer" in str(error):
                raise RuntimeError(
                    "这个对话目前正在 Codex 桌面端占用。请先在电脑端切换到其他对话，稍等片刻后重试；"
                    "或者在飞书绑定一个当前未打开的对话。"
                ) from error
            raise
        result = codex_rpc.call("turn/start", {
            "threadId": thread_id,
            "input": codex_input,
        })
        turn = result.get("turn", {})
        turn_id = turn.get("id")
        if turn_id:
            active_turns[thread_id] = turn_id
    reply_text(message_id, f"已发送到 Codex：{before.get('name') or '当前对话'}")

    deadline = time.monotonic() + 1800
    progress_sent = False
    while time.monotonic() < deadline:
        time.sleep(3)
        thread = read_thread(thread_id)
        turns = thread.get("turns", [])
        target = next((item for item in reversed(turns) if item.get("id") == turn_id), None)
        if target is None:
            target = next((item for item in reversed(turns) if item.get("id") not in previous_turn_ids), None)
        if not target:
            continue
        status = target.get("status")
        if not progress_sent and status not in {"completed", "failed", "interrupted"}:
            progress = turn_live_summary(target)
            if progress:
                reply_text(message_id, f"Codex 执行计划：\n\n{progress[:5000]}")
                progress_sent = True
                log(f"已回传首条执行计划 thread={thread_id} turn={turn_id}")
        if status in {"completed", "failed", "interrupted"}:
            with codex_lock:
                if active_turns.get(thread_id) == turn_id:
                    active_turns.pop(thread_id, None)
            _, agent_text = turn_pair(target)
            if not agent_text:
                agent_text = f"任务状态：{status}，没有取得文字回复。"
            reply_text(message_id, f"Codex 回复：\n\n{agent_text[:12000]}")
            plan = attachment_plan(target, False)
            agent_items = [item for item in plan if item["delivery"] == "agent_disk"]
            local_only_items = [item for item in plan if item["delivery"] == "local_only"]
            local_fallback_items = [item for item in plan if item["delivery"] == "local_fallback"]
            if agent_items:
                lines = [f"{item['name']}\nAgent Disk：{item.get('agentDiskPath') or '未配置'}\n原因：{item['reason']}" for item in agent_items]
                reply_text(message_id, "本次回复附件统一保存到 Agent Disk：\n\n" + "\n\n".join(lines))
            else:
                for item in (item for item in plan if item["delivery"] == "local"):
                    attachment = Path(item["localPath"])
                    try:
                        msg_type, content = upload_feishu_attachment(attachment)
                        reply_message(message_id, msg_type, content)
                    except Exception as attachment_error:
                        log(f"附件回传失败 {attachment}: {attachment_error}")
                        reply_text(message_id, f"附件 {attachment.name} 未能发送到飞书：{attachment_error}\n本机位置：{attachment}")
            if local_only_items:
                reply_text(message_id, "以下文件类型不直接上传，已保存在本机：\n" + "\n".join(
                    f"{item['name']}：{item['localPath']}" for item in local_only_items))
            if local_fallback_items:
                reply_text(message_id, "附件超过直传限制，但尚未配置 Agent Disk；文件仍保存在本机：\n" + "\n".join(
                    f"{item['name']}：{item['localPath']}" for item in local_fallback_items))
            return
    with codex_lock:
        if active_turns.get(thread_id) == turn_id:
            active_turns.pop(thread_id, None)
    reply_text(message_id, "Codex 仍在运行，已超过桥的等待时间。可发送 /当前 查看状态。")


def process_message(message_id: str, chat_id: str, chat_type: str, text: str, codex_input: list | None = None) -> None:
    try:
        if handle_command(message_id, chat_id, chat_type, text):
            return
        thread_id = selected_thread_id(chat_id)
        if not thread_id:
            send_to_codex(message_id, chat_id, text, codex_input)
            return
        send_to_codex(message_id, chat_id, text, codex_input)
    except Exception as error:
        log(f"处理飞书消息失败 {message_id}：{error}")
        try:
            reply_text(message_id, "桥处理遇到临时错误，请稍后重试。详细信息已记录在电脑日志中。")
        except Exception as reply_error:
            log(f"发送错误提示失败：{reply_error}")


def download_feishu_resource(message_id: str, key: str, resource_type: str, name: str) -> Path:
    safe_name = re.sub(r'[^\w.()\-\u4e00-\u9fff]+', '_', name, flags=re.UNICODE).strip('._') or f"feishu-{resource_type}"
    folder = INBOX_DIR / datetime.now().strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{message_id[-10:]}-{safe_name}"
    response = http.get(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{key}",
        params={"type": resource_type}, headers={"Authorization": f"Bearer {get_feishu_token()}"},
        timeout=(10, 90), stream=True,
    )
    response.raise_for_status()
    size = 0
    with target.open("wb") as file:
        for chunk in response.iter_content(1024 * 256):
            size += len(chunk)
            if size > 100 * 1024 * 1024:
                raise RuntimeError("飞书附件超过 100 MB 下载限制")
            file.write(chunk)
    return target


def prepare_feishu_input(message_id: str, message_type: str, content_raw: str) -> tuple[str, list]:
    content = json.loads(content_raw or "{}")
    if message_type == "image":
        path = download_feishu_resource(message_id, content["image_key"], "image", "image.jpg")
        return "请查看并处理我从飞书发送的这张图片。", [
            {"type": "text", "text": "请查看并处理我从飞书发送的这张图片。", "text_elements": []},
            {"type": "localImage", "path": str(path)},
        ]
    if message_type in {"file", "audio", "media"}:
        name = content.get("file_name") or f"feishu-{message_type}"
        path = download_feishu_resource(message_id, content["file_key"], "file", name)
        text = f"我从飞书发送了一个{message_type}附件，已下载到本机：{path}\n请读取并按文件内容处理。"
        return text, [{"type": "text", "text": text, "text_elements": []}]
    raise RuntimeError(f"暂不支持飞书消息类型：{message_type}")


def on_message(data: P2ImMessageReceiveV1) -> None:
    event = data.event
    message = event.message
    sender = event.sender
    message_id = message.message_id
    chat_id = message.chat_id
    chat_type = message.chat_type or "p2p"

    if not message_id or sender.sender_type == "bot":
        return
    if chat_id:
        message_chat_ids[message_id] = chat_id
    if message_id in seen:
        log(f"忽略重复消息 {message_id}")
        return
    seen.add(message_id)

    event_created_ms = 0
    try:
        event_created_ms = int(data.header.create_time or 0) if data.header else 0
    except (TypeError, ValueError):
        pass
    event_age_seconds = max(0.0, (time.time() * 1000 - event_created_ms) / 1000) if event_created_ms else 0.0
    if event_age_seconds > 30:
        save_state()
        log(f"忽略积压飞书消息 {message_id}，事件已延迟 {event_age_seconds:.1f} 秒")
        try:
            reply_text(message_id, "这条消息发送时桥可能未在线，恢复连接时已超过 30 秒，因此没有送入 Codex。请重新发送。")
        except Exception as error:
            log(f"发送积压消息提示失败 {message_id}：{error}")
        return

    open_id = sender.sender_id.open_id if sender.sender_id else None
    if not state.get("owner_open_id") and open_id:
        state["owner_open_id"] = open_id
        log("已自动绑定首位单聊用户为桥的使用者")
    save_state()

    text = ""
    codex_input = None
    if message.message_type == "text":
        try:
            text = json.loads(message.content or "{}").get("text", "")
        except Exception:
            pass

    log(f"收到飞书消息 {message_id}，类型={message.message_type}，会话={chat_type}")
    if message.message_type in {"image", "file", "audio", "media"}:
        try:
            text, codex_input = prepare_feishu_input(message_id, message.message_type, message.content or "{}")
            reply_text(message_id, f"已接收{('图片' if message.message_type == 'image' else '附件')}，正在送入当前 Codex 对话。")
        except Exception as error:
            log(f"飞书附件接收失败 {message_id}：{error}")
            reply_text(message_id, f"附件接收失败：{error}")
            return
    text = re.sub(r"@_user_\d+\s*", "", text).strip()
    if not text:
        reply_text(message_id, "暂不支持这种消息类型，请发送图片、文件、音频、视频或文字。")
        return
    threading.Thread(
        target=process_message,
        args=(message_id, chat_id, chat_type, text.strip(), codex_input),
        daemon=True,
    ).start()


event_handler = (
    lark.EventDispatcherHandler.builder("", "")
    .register_p2_im_message_receive_v1(on_message)
    .build()
)


def main() -> None:
    threading.Thread(target=monitor_desktop_mode, daemon=True).start()
    threading.Thread(target=sync_cloud_history, daemon=True).start()
    threading.Thread(target=cloud_heartbeat_worker, daemon=True).start()
    threading.Thread(target=cloud_task_worker, daemon=True).start()
    start_dashboard()
    log("正在连接飞书开放平台……")
    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    ws_client.start()


if __name__ == "__main__":
    main()
