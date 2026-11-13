import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


class StartupTests(unittest.TestCase):
    def test_case_intake_and_private_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"SKINAI_DB_PATH": str(root / "db"), "SKINAI_PHOTO_DIR": str(root / "photos")}):
                with TestClient(app) as client:
                    from PIL import Image
                    from io import BytesIO

                    image = BytesIO()
                    Image.new("RGB", (8, 8)).save(image, format="PNG")
                    result = client.post("/api/cases", data={
                        "doctorId": "d1", "date": "2026-11-13", "time": "10:00",
                        "patientName": "Demo", "age": "25", "gender": "none",
                    }, files={key: ("photo.png", image.getvalue(), "image/png")
                              for key in ("photo0", "photo1")})
                    self.assertEqual(result.status_code, 201, result.text)
                    body = result.json()
                    url = f"/api/cases/{body['id']}"
                    headers = {"Authorization": f"Bearer {body['accessToken']}"}
                    self.assertEqual(client.get(url).status_code, 401)
                    self.assertEqual(client.get(url, headers=headers).json()["patientName"], "Demo")
                    photo = client.get(url + "/photos/0", headers=headers)
                    self.assertEqual(photo.content, image.getvalue())
                    self.assertEqual(client.get(url + "/photos/1", headers=headers).status_code, 200)
                    self.assertEqual(client.get(url + "/photos/2", headers=headers).status_code, 404)
                    self.assertEqual(client.post(url + "/analyze", headers=headers).status_code, 503)

                    from app.jobs import claim, heartbeat
                    from app.worker import run_job
                    from unittest.mock import Mock

                    second = client.post("/api/cases", data={
                        "doctorId": "d1", "date": "2026-11-13", "time": "10:00",
                        "patientName": "Demo", "age": "25", "gender": "none",
                    }, files={key: ("photo.png", image.getvalue(), "image/png")
                              for key in ("photo0", "photo1", "photo2")}).json()
                    url = f"/api/cases/{second['id']}"
                    headers = {"Authorization": f"Bearer {second['accessToken']}"}
                    self.assertEqual(client.post(url + "/analyze", headers=headers).status_code, 503)
                    heartbeat("test-worker")
                    queued = client.post(url + "/analyze", headers=headers)
                    self.assertEqual(queued.status_code, 202)
                    self.assertEqual(client.post(url + "/analyze", headers=headers).json(), queued.json())
                    job = claim()
                    self.assertEqual(job["photo_index"], 1)
                    model = Mock()
                    model.predict.return_value = {"decision": "deferred", "candidate": None}
                    self.assertTrue(run_job(job, model, {"yolo": "mock"}))
                    self.assertEqual(client.get(url, headers=headers).json()["aiState"], "완료")
                    with patch.dict(os.environ, {"SKINAI_DEMO_DOCTOR_TOKENS": '{"d1":"test-one","d2":"test-two"}'}):
                        doctor = {"Authorization": "Bearer test-one"}
                        other = {"Authorization": "Bearer test-two"}
                        self.assertEqual(client.get(url, headers=doctor).json()["analysis"]["decision"], "deferred")
                        self.assertNotIn("analysis", client.get(url, headers=headers).json())
                        self.assertEqual(client.get(url + "/photos/2", headers=other).status_code, 404)
                        self.assertEqual(len(client.get("/api/cases", headers=doctor).json()), 2)
                        self.assertEqual(client.get("/api/cases?doctorId=d1", headers=other).status_code, 403)
                        review = {"diagnosis": "", "opinion": "Demo opinion", "visitRequired": False,
                                  "visitMessage": "", "reviewState": "임시 저장"}
                        self.assertEqual(client.patch(url + "/review", headers=other, json=review).status_code, 404)
                        self.assertEqual(client.patch(url + "/review", headers=doctor, json=review).status_code, 200)
                        self.assertNotIn("opinion", client.get(url, headers=headers).json())
                        review["reviewState"] = "결과 전달 완료"
                        self.assertEqual(client.patch(url + "/review", headers=doctor, json=review).status_code, 200)
                        self.assertEqual(client.get(url, headers=headers).json()["opinion"], "Demo opinion")

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
