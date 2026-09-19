# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge
# Repository: https://github.com/dizzynote-cell/codex-remote-bridge

"""Human requests from app-server, kept separate from chat/turn submissions."""
import copy
import hashlib
import ipaddress
import json
import re
import threading
import time
import uuid
from urllib.parse import urlparse


class InteractionError(ValueError):
    pass


PC_HELP = "请回到主力 PC，或使用远程协助完成操作。桥网页不能解锁 Windows、代填验证码或操作系统弹窗。"
PC_PATTERN = re.compile(
    r"验证码|人机验证|扫码|扫描二维码|解锁|锁屏|系统弹窗|UAC|安全桌面|"
    r"captcha|verification code|one[- ]time (?:code|password)|\botp\b|"
    r"unlock|locked (?:screen|desktop)|scan.{0,20}qr|secure desktop", re.I)


def text(value, limit=4000):
    return str(value or "")[:limit]


def pc_required(value):
    return bool(PC_PATTERN.search(value) and re.search(
        r"请|需要|手动|完成|输入|填写|当前.{0,12}锁|已锁|被锁|"
        r"please|need|must|manually|complete|enter|solve|scan|unlock|is locked", value, re.I))


def form_fields(schema):
    """Only advertise forms that we can validate completely. Others stay on PC."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    if set(schema) - {"type", "properties", "required", "additionalProperties", "title", "description", "$schema"}:
        return None
    properties = schema.get("properties", {})
    if not isinstance(properties, dict) or len(properties) > 12:
        return None
    fields = []
    for name, spec in properties.items():
        if not isinstance(spec, dict) or spec.get("type") not in {"string", "boolean", "integer", "number"}:
            return None
        if set(spec) - {"type", "title", "description", "enum", "enumNames", "minLength", "maxLength", "minimum", "maximum", "default"}:
            return None
        if PC_PATTERN.search(name + " " + json.dumps(spec, ensure_ascii=False)) or re.search(r"password|secret|密码|口令", name + " " + str(spec), re.I):
            return None
        choices = spec.get("enum")
        if choices is not None and (not isinstance(choices, list) or len(choices) > 30):
            return None
        fields.append({"id": name, "label": text(spec.get("title") or name, 200),
                       "description": text(spec.get("description"), 1000),
                       "required": name in schema.get("required", []), **copy.deepcopy(spec)})
    if not set(schema.get("required", [])).issubset(properties):
        return None
    return fields


def describe(method, params):
    prompt = text(params.get("message") or params.get("reason"))
    view = {"kind": "unsupported", "category": "pc", "title": "此请求需要在 PC 查看",
            "message": prompt, "help": PC_HELP, "actions": ["cancel"]}
    if method == "item/tool/requestUserInput":
        questions = params.get("questions") or []
        if not isinstance(questions, list) or not questions or len(questions) > 12:
            return view
        safe = [{"id": text(q.get("id"), 200), "header": text(q.get("header"), 200),
                 "question": text(q.get("question")), "secret": bool(q.get("isSecret")),
                 "options": [{"label": text(o.get("label"), 500), "description": text(o.get("description"), 1000)}
                             for o in (q.get("options") or [])[:30]]} for q in questions]
        if len({q['id'] for q in safe}) != len(safe) or any(not q['id'] for q in safe): return view
        for q in safe: q['pc'] = q['secret'] or pc_required(q['question'])
        pc = any(q['pc'] for q in safe)
        view.update(kind="questions", category="pc" if pc else "web", questions=safe,
                    title="需要在主力 PC 操作" if pc else "Codex 需要你的回答",
                    actions=["manual_done", "cancel"] if pc else ["answer", "cancel"],
                    help=PC_HELP if pc else "在这里回答即可，不需要操作主力 PC。")
    elif method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval",
                    "item/permissions/requestApproval", "execCommandApproval", "applyPatchApproval"}:
        # Approval grants permission; it never pretends a desktop action was completed.
        view.update(kind="approval", category="web", title="需要你的授权确认",
                    actions=["accept", "decline"], help="允许仅回答当前请求，不会替你完成登录、解锁或验证码操作。")
        command = params.get("command")
        if isinstance(command, list): command = " ".join(map(str, command))
        details = {k: params[k] for k in ("cwd", "permissions", "fileChanges", "grantRoot") if params.get(k) is not None}
        if command: details["command"] = command
        view["details"] = text(json.dumps(details, ensure_ascii=False, indent=2), 16000)
    elif method == "mcpServer/elicitation/request":
        view.update(kind="elicitation", title="工具需要你的确认")
        if params.get("mode") == "url":
            url = str(params.get("url") or "")
            parsed = urlparse(url)
            # A localhost redirect would target the phone rather than the PC.
            host = parsed.hostname or ''
            try: local = not ipaddress.ip_address(host).is_global
            except ValueError: local = host == 'localhost' or host.endswith(('.localhost', '.local'))
            remote = parsed.scheme == "https" and host and not local and not parsed.username
            if remote and not pc_required(prompt):
                view.update(category="web", url=url, actions=["manual_done", "cancel"],
                            help="打开授权页面完成操作，再点击“我已完成”。若页面要求本机操作，请回到主力 PC 或使用远程协助。")
            else:
                view.update(title="需要在主力 PC 操作", actions=["manual_done", "cancel"])
        else:
            fields = form_fields(params.get("requestedSchema"))
            if fields is not None and not pc_required(prompt):
                view.update(category="web", fields=fields, actions=["answer", "cancel"],
                            help="填写后返回给当前工具请求。")
            else:
                view.update(title="此工具请求需要在 PC 处理",
                            help=PC_HELP + " 此表单无法在桥网页安全填写；处理后可关闭此请求，再在对话中发送“继续”。")
    return view


def build_result(method, params, view, payload):
    action = payload.get("action")
    if action not in view["actions"]:
        raise InteractionError("不支持这个回答动作，请刷新请求")
    if method == "item/tool/requestUserInput":
        if action == "cancel": return {"answers": {}}
        incoming = payload.get("answers", {})
        if not isinstance(incoming, dict): raise InteractionError("请填写回答")
        answers = {}
        for q in view["questions"]:
            if action == 'manual_done' and q.get('pc'):
                answers[q['id']] = {'answers': ['用户反馈：已在主力 PC 完成操作，请重新检查实际状态；未提供密码或验证码。']}
                continue
            value = incoming.get(q["id"])
            if not isinstance(value, str) or not value.strip() or len(value) > 8000:
                raise InteractionError("请回答所有问题（每项不超过 8000 字）")
            answers[q["id"]] = {"answers": [value.strip()]}
        return {"answers": answers}
    if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
        return {"decision": action}
    if method in {"execCommandApproval", "applyPatchApproval"}:
        return {"decision": "approved" if action == "accept" else "abort"}
    if method == "item/permissions/requestApproval":
        requested = params.get("permissions") or {}
        return {"permissions": {k: v for k, v in requested.items() if k in {"fileSystem", "network"}} if action == "accept" else {}, "scope": "turn"}
    if method == "mcpServer/elicitation/request":
        if action == "cancel": return {"action": "cancel", "content": None}
        if action == "manual_done": return {"action": "accept", "content": None}
        incoming = payload.get("content")
        if not isinstance(incoming, dict): raise InteractionError("请填写工具表单")
        content = {}
        for field in view.get("fields", []):
            key = field["id"]
            if key not in incoming:
                if field["required"]: raise InteractionError("请填写：" + field["label"])
                continue
            value = incoming[key]; kind = field["type"]
            valid = (kind == "string" and isinstance(value, str) or kind == "boolean" and isinstance(value, bool)
                     or kind == "integer" and type(value) is int or kind == "number" and type(value) in (int, float))
            if not valid: raise InteractionError("字段类型错误：" + field["label"])
            if "enum" in field and value not in field["enum"]: raise InteractionError("请选择有效选项")
            if isinstance(value, str) and not field.get("minLength", 0) <= len(value) <= min(field.get("maxLength", 8000), 8000):
                raise InteractionError("字段长度不符合要求")
            if type(value) in (int, float) and not field.get("minimum", float('-inf')) <= value <= field.get("maximum", float('inf')):
                raise InteractionError("数字超出范围")
            content[key] = value
        return {"action": "accept", "content": content}
    raise InteractionError("这个请求不能在网页回答")


class Interactions:
    def __init__(self, send):
        self.send = send
        self.session = uuid.uuid4().hex
        self.started = time.time()
        self.revision = 0
        self.entries = {}
        self.lock = threading.RLock()

    def request(self, message):
        method = message["method"]; params = message.get("params") or {}
        view = describe(method, params)
        if view["kind"] == "unsupported":
            # Missing host tools are not permission prompts. Fail explicitly.
            if method == "item/tool/call":
                self.send({"id": message["id"], "result": {"success": False, "contentItems": [
                    {"type": "inputText", "text": "桥尚未接入此客户端工具，请使用可用工具或在主力 PC 客户端继续。"}]}})
            else:
                self.send({"id": message["id"], "error": {"code": -32601, "message": "Bridge does not support this server request"}})
            self.notice(params, "桥尚未接入此客户端交互，请在主力 PC 客户端查看，或使用远程协助。")
            return
        with self.lock:
            if any(e.get("wireId") == message["id"] and e["status"] == "pending" for e in self.entries.values()): return
            key = uuid.uuid4().hex
            self.entries[key] = {**view, "id": key, "session": self.session,
                "threadId": text(params.get("threadId") or params.get("conversationId"), 200),
                "turnId": text(params.get("turnId"), 200), "createdAt": time.time(), "status": "pending",
                "wireId": message["id"], "method": method, "params": copy.deepcopy(params)}
            self.revision += 1
    def notice(self, params, message):
        with self.lock:
            thread = text(params.get("threadId"), 200); turn = text(params.get("turnId"), 200)
            if any(e.get("kind") == "notice" and e["threadId"] == thread and e["turnId"] == turn for e in self.entries.values()): return
            key = uuid.uuid4().hex
            self.entries[key] = {"id": key, "session": self.session, "threadId": thread, "turnId": turn,
                "category": "pc", "kind": "notice", "title": "需要在主力 PC 操作", "message": text(message),
                "help": PC_HELP + " 处理后请在对话中发送“继续”；关闭提示不会向 Codex 宣称操作已成功。",
                "actions": ["dismiss"], "createdAt": time.time(), "status": "pending"}
            self.revision += 1

    def notification(self, method, params):
        with self.lock:
            if method == "item/completed":
                item = params.get("item") or {}; body = text(item.get("text"))
                # Only explicit requests to a human, not arbitrary discussion of CAPTCHAs.
                if item.get("type") == "agentMessage" and pc_required(body) and re.search(r"请.{0,35}(?:手动|解锁|扫码|验证码|远程)|(?:please|you need to).{0,60}(?:unlock|captcha|verification|manually|scan)", body, re.I):
                    self.notice(params, body)
            for entry in self.entries.values():
                if entry["status"] != "pending": continue
                if entry['kind'] == 'notice':
                    if method == 'turn/started' and params.get('threadId') == entry['threadId'] and (params.get('turn') or {}).get('id') != entry['turnId']:
                        entry.update(status='resolved', closedAt=time.time()); self.revision += 1
                    continue
                same_thread = not params.get("threadId") or params["threadId"] == entry["threadId"]
                resolved = method == "serverRequest/resolved" and str(params.get("requestId")) == str(entry.get("wireId")) and same_thread
                completed = method == "turn/completed" and same_thread and entry["turnId"] and entry["turnId"] == (params.get("turn") or {}).get("id")
                if resolved or completed:
                    entry["status"] = "resolved"; self.revision += 1

    def snapshot(self):
        with self.lock:
            now = time.time()
            # Answer bodies/params never enter the cloud snapshot. Closed entries live briefly for acknowledgements.
            for key, e in list(self.entries.items()):
                if e["status"] != "pending" and now - e.get("closedAt", e["createdAt"]) > 600:
                    del self.entries[key]; self.revision += 1
            safe = [{k: copy.deepcopy(v) for k, v in e.items() if k not in {"wireId", "method", "params", "answerHash"}}
                    for e in self.entries.values()]
            return {"session": self.session, "startedAt": self.started, "revision": self.revision, "requests": safe}

    def respond(self, payload):
        with self.lock:
            if not isinstance(payload, dict): raise InteractionError("回答格式错误")
            entry = self.entries.get(payload.get("id"))
            if not entry or payload.get("session") != self.session or payload.get("threadId", "") != entry["threadId"] or payload.get("turnId", "") != entry["turnId"]:
                raise InteractionError("请求已失效或不属于当前会话，请刷新")
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if entry["status"] == "answered" and entry.get("answerHash") == digest:
                return {"ok": True, "status": "answered"}
            if entry["status"] != "pending": raise InteractionError("请求已被处理，不能重复回答")
            if entry["kind"] == "notice":
                if payload.get("action") != "dismiss": raise InteractionError("请选择关闭提示")
            else:
                result = build_result(entry["method"], entry["params"], entry, payload)
                self.send({"id": entry["wireId"], "result": result})
            entry.update(status="answered", answerHash=digest, closedAt=time.time())
            self.revision += 1
            return {"ok": True, "status": "answered"}

    def disconnect(self):
        with self.lock:
            for e in self.entries.values():
                if e["status"] == "pending": e.update(status="disconnected", closedAt=time.time())
            self.revision += 1

