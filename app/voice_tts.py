"""On-demand Volcengine speech synthesis and bounded local MP3 cache."""
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values

_LOCK = threading.RLock()
_INFLIGHT = {}
_LIMIT = 10 * 1024**3
_TRIGGER = 9 * 1024**3
_TARGET = 6 * 1024**3
_FREE_FLOOR = 20 * 1024**3


def settings(root: Path) -> dict:
    source = Path(os.getenv("VOLC_TTS_ENV_FILE") or (root / "config" / "voiceapi.env"))
    values = dotenv_values(source) if source.is_file() else {}
    return {
        "api_key": values.get("VOLC_API_KEY") or os.getenv("VOLC_API_KEY") or "",
        "voice": values.get("VOLC_VOICE_ID") or os.getenv("VOLC_VOICE_ID") or "",
        "resource": values.get("X-Api-Resource-Id") or values.get("VOLC_RESOURCE_ID")
        or os.getenv("VOLC_RESOURCE_ID") or "",
    }


def key(text: str, config: dict) -> str:
    payload = json.dumps([text, config["voice"], config["resource"], "v3-sse-mp3"], ensure_ascii=False,separators=(",",":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_file(cache: Path, digest: str) -> Path:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid voice cache key")
    return cache / (digest + ".mp3")


def cached(cache: Path, digest: str) -> bool:
    file = cache_file(cache, digest)
    return file.is_file() and file.stat().st_size > 0


def trim(cache: Path, required: int = 0) -> None:
    """Capacity-only cleanup. Never relies on a timer while the PC is off."""
    cache.mkdir(parents=True, exist_ok=True)
    files = sorted((p for p in cache.glob("*.mp3") if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    free = shutil.disk_usage(cache).free
    if total + required < _TRIGGER and free - required >= _FREE_FLOOR:
        return
    target = min(_TARGET, max(0, total + free - _FREE_FLOOR - required))
    for file in files:
        if total + required <= target and free - required >= _FREE_FLOOR:
            break
        if file.stem in _INFLIGHT:
            continue
        size = file.stat().st_size
        file.unlink()
        total -= size
        free += size
    if total + required > _LIMIT or free - required < _FREE_FLOOR:
        raise OSError("local_voice_cache_storage_low")


def synthesize(text: str, cache: Path, config: dict) -> tuple[str, Path]:
    if not all(config.values()):
        raise ValueError("voice_not_configured")
    text = text.strip()
    if not text or len(text) > 12000:
        raise ValueError("voice_text_empty_or_too_long")
    digest = key(text, config)
    with _LOCK:
        file = cache_file(cache, digest)
        if cached(cache, digest):
            os.utime(file, None)
            return digest, file
        if digest in _INFLIGHT:
            event = _INFLIGHT[digest]
            producer = False
        else:
            event = threading.Event()
            _INFLIGHT[digest] = event
            producer = True
    if not producer:
        event.wait(180)
        if cached(cache, digest):
            return digest, file
        raise RuntimeError("voice_synthesis_failed_or_timed_out")
    try:
        chunks = []
        with requests.post(
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
            headers={"X-Api-Key": config["api_key"], "X-Api-Resource-Id": config["resource"],
                     "X-Api-Request-Id": str(uuid.uuid4()), "Content-Type": "application/json"},
            json={"user": {"uid": "codex-bridge"}, "req_params": {
                "text": text, "speaker": config["voice"],
                "audio_params": {"format": "mp3", "bit_rate": 64000}}},
            stream=True, timeout=(10, 120),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line or not line.startswith(b"data:"):
                    continue
                data = json.loads(line[5:])
                if data.get("code") not in (None, 0, 20000000):
                    raise RuntimeError("voice_provider_error:" + str(data.get("code")))
                if data.get("data"):
                    import base64
                    chunks.append(base64.b64decode(data["data"], validate=True))
                if sum(map(len, chunks)) > 20 * 1024**2:
                    raise ValueError("voice_audio_too_large")
        audio = b"".join(chunks)
        if not audio:
            raise RuntimeError("voice_provider_returned_no_audio")
        with _LOCK:
            trim(cache, len(audio))
            temp = cache / (digest + "." + uuid.uuid4().hex + ".tmp")
            try:
                temp.write_bytes(audio)
                os.replace(temp, file)
            finally:
                temp.unlink(missing_ok=True)
        return digest, file
    finally:
        with _LOCK:
            _INFLIGHT.pop(digest, None)
            event.set()
