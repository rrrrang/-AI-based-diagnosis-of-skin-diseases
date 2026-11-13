import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class StartupTests(unittest.TestCase):
    def test_startup_and_doctors(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "backend.sqlite3"
            with patch.dict(os.environ, {"SKINAI_DB_PATH": str(database)}):
                with TestClient(app) as client:
                    health = client.get("/api/health")
                    doctors = client.get("/api/doctors")
                    missing = client.get("/api/missing")

            self.assertTrue(database.is_file())
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json(), {"status": "ok"})
            self.assertEqual(doctors.status_code, 200)
            self.assertEqual(len(doctors.json()), 3)
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["request_id"], missing.headers["X-Request-ID"])
