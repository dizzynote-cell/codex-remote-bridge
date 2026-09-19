import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).parents[1]
local = load("local_thread_organizer", ROOT / "app" / "thread_organizer.py")
cloud = load("cloud_thread_organizer", ROOT / "cloud" / "thread_organizer.py")
THREAD_ID = "12345678-1234-4234-8234-123456789abc"


class LocalOrganizerTests(unittest.TestCase):
    def test_persists_and_merges_newer_cloud_state(self):
        with tempfile.TemporaryDirectory() as directory:
            organizer = local.Organizer(Path(directory) / "organizer.json")
            first = organizer.update(THREAD_ID, name="本机名称", pinned=True, project="项目甲")
            self.assertTrue(organizer.get(THREAD_ID)["pinned"])
            organizer.merge({"threads": {THREAD_ID: {"name": "旧云端", "updated": first["updated"] - 1}}})
            self.assertEqual(organizer.get(THREAD_ID)["name"], "本机名称")
            organizer.merge({"threads": {THREAD_ID: {"name": "新云端", "pinned": False, "project": "项目乙", "updated": first["updated"] + 1}}})
            self.assertEqual(organizer.get(THREAD_ID)["name"], "新云端")
            self.assertFalse(organizer.get(THREAD_ID)["pinned"])


class CloudOrganizerTests(unittest.TestCase):
    def test_update_validation_and_newer_state_wins(self):
        db = sqlite3.connect(":memory:")
        cloud.initialize(db)
        item = cloud.update(db, {"threadId": THREAD_ID, "name": "网页名称", "pinned": True})
        cloud.merge(db, {"threads": {THREAD_ID: {"name": "过期名称", "updated": item["updated"] - 1}}})
        self.assertEqual(cloud.snapshot(db)["threads"][THREAD_ID]["name"], "网页名称")
        with self.assertRaises(ValueError):
            cloud.update(db, {"threadId": "not-a-uuid", "pinned": True})


if __name__ == "__main__":
    unittest.main()


