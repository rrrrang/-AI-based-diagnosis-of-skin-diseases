import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from app.db import connect, init_db
from app.jobs import LEASE_SECONDS, MAX_CLAIMS, claim, enqueue, finish, heartbeat, latest, renew
from app.worker import run_job


class AnalysisQueueTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            "SKINAI_DB_PATH": str(root / "test.sqlite"),
            "SKINAI_PHOTO_DIR": str(root / "photos"),
        }))
        self.clock = self.enterContext(patch("app.jobs.time.time", return_value=1000))
        init_db()
        with closing(connect()) as db, db:
            db.execute("INSERT INTO cases (id, doctor_id, token_hash, intake) VALUES ('demo','d1','test','{}')")
            db.execute("INSERT INTO photos VALUES ('demo', 1, 'image/png')")
        photo_dir = root / "photos" / "demo"
        photo_dir.mkdir(parents=True)
        Image.new("RGB", (8, 8)).save(photo_dir / "1", format="PNG")
        heartbeat("test-worker")

    def read_job(self):
        with closing(connect()) as db:
            return latest(db, "demo")

    def test_concurrent_requests_create_only_one_job(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(enqueue, ["demo"] * 4))
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len({job["id"] for job, _ in results}), 1)
        self.assertIsNotNone(claim())
        self.assertIsNone(claim())

    def test_renewal_prevents_reclaim_until_new_expiry(self):
        enqueue("demo")
        job = claim()
        self.clock.return_value += LEASE_SECONDS / 2
        self.assertTrue(renew(job))
        self.clock.return_value = job["expires"]
        self.assertIsNone(claim())
        self.assertTrue(finish(job, result={"decision": "undetermined"}))
        self.assertEqual(self.read_job()["state"], "completed")

    def test_expired_lease_is_reclaimed_and_old_worker_cannot_write(self):
        enqueue("demo")
        first = claim()
        self.clock.return_value = first["expires"]
        recovered = claim()
        self.assertEqual(recovered["id"], first["id"])
        self.assertEqual(recovered["attempts"], 2)
        self.assertNotEqual(recovered["lease"], first["lease"])
        self.assertFalse(renew(first))
        self.assertFalse(finish(first, result={"decision": "deferred"}))
        self.assertTrue(finish(recovered, result={"decision": "undetermined"}))
        self.assertEqual(json.loads(self.read_job()["result"]), {"decision": "undetermined"})

    def test_recovery_stops_at_claim_limit(self):
        enqueue("demo")
        for attempt in range(1, MAX_CLAIMS + 1):
            job = claim()
            self.assertEqual(job["attempts"], attempt)
            self.clock.return_value = job["expires"]
        self.assertIsNone(claim())
        job = self.read_job()
        self.assertEqual((job["state"], job["error"]), ("failed", "worker_lease_expired"))
        self.assertIsNone(job["lease"])

    def test_model_failure_requires_explicit_retry(self):
        first, _ = enqueue("demo")
        model = Mock()
        model.predict.side_effect = RuntimeError("simulated inference failure")
        with self.assertLogs(level="ERROR"):
            self.assertTrue(run_job(claim(), model, {}))
        existing, created = enqueue("demo")
        self.assertFalse(created)
        self.assertEqual((existing["id"], existing["state"], existing["error"]),
                         (first["id"], "failed", "inference_failed"))
        retry, created = enqueue("demo", retry=True)
        self.assertTrue(created)
        self.assertNotEqual(retry["id"], first["id"])
        self.assertEqual(retry["state"], "pending")
