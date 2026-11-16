from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

SUPPORT = Path(__file__).resolve().parents[1] / "support"
spec = importlib.util.spec_from_file_location("release_worker_health", SUPPORT / "worker_health.py")
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class WorkerHealthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "queue.sqlite3"
        self.state = self.root / "worker.json"
        self.worker_id = "a" * 32
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE analysis_workers (id TEXT PRIMARY KEY, expires REAL)")
        self.state.write_text(json.dumps({
            "worker_id": self.worker_id, "started_at": 100.0, "pid": 1,
        }), encoding="utf-8")

    def heartbeat(self, worker_id, expires):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO analysis_workers VALUES (?, ?)", (worker_id, expires))

    def test_current_worker_after_model_load_is_ready(self):
        self.heartbeat(self.worker_id, 180.0)
        self.assertTrue(health.is_ready(self.database, self.state, now=120.0))

    def test_live_sibling_cannot_make_this_worker_ready(self):
        self.heartbeat("b" * 32, 180.0)
        self.assertFalse(health.is_ready(self.database, self.state, now=120.0))

    def test_expired_heartbeat_is_not_ready(self):
        self.heartbeat(self.worker_id, 119.0)
        self.assertFalse(health.is_ready(self.database, self.state, now=120.0))

    def test_no_post_load_marker_is_not_ready(self):
        self.heartbeat(self.worker_id, 180.0)
        self.state.unlink()
        self.assertFalse(health.is_ready(self.database, self.state, now=120.0))

    def test_missing_database_is_not_created(self):
        missing = self.root / "missing.sqlite3"
        self.assertFalse(health.is_ready(missing, self.state, now=120.0))
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
