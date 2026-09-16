"""Offline checks for the optional TTS cache (no API calls or credentials)."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import voice_tts


class VoiceCacheTests(unittest.TestCase):
    def test_key_matches_browser_json_payload(self):
        config = {"voice": "voice-example", "resource": "resource-example"}
        text = "你好，Codex"
        expected = hashlib.sha256(json.dumps(
            [text, config["voice"], config["resource"], "v3-sse-mp3-rate25"],
            ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        self.assertEqual(voice_tts.key(text, config), expected)

    def test_cache_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with self.assertRaises(ValueError):
                voice_tts.cache_file(cache, "../private")
            self.assertFalse(voice_tts.cached(cache, "a" * 64))


if __name__ == "__main__":
    unittest.main()
