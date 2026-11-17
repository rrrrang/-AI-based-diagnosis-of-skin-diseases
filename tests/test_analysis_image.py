"""AI 표시 그림(analysis-image) 테스트. 모델 대신 가짜 앙상블을 쓴다."""
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.jobs import claim, heartbeat
from app.worker import run_job
from main import app
from ci.backend_contract.auth_support import (bearer_headers, doctor_environment,
                                               new_doctor_tokens, patient_headers)


class FakeEnsemble:
    def __init__(self, overlay=None, error=None):
        self._overlay, self._error = overlay, error

    def predict(self, image, image_id, role):
        return {"decision": "majority", "candidate": "acne"}

    def overlay(self, image):
        if self._error:
            raise self._error
        return self._overlay


def png(color=(0, 0, 0), size=(8, 8)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class AnalysisImageTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        doctor_tokens = new_doctor_tokens()
        self.enterContext(patch.dict(os.environ, {
            "SKINAI_DB_PATH": str(root / "db"),
            "SKINAI_PHOTO_DIR": str(root / "photos"),
            **doctor_environment(doctor_tokens),
        }))
        self.client = self.enterContext(TestClient(app))
        body = self.client.post("/api/cases", data={
            "doctorId": "d1", "date": "2026-11-17", "time": "10:00",
            "patientName": "Demo", "age": "25", "gender": "none",
        }, files={key: ("photo.png", png(), "image/png") for key in ("photo0", "photo1")}).json()
        self.url = f"/api/cases/{body['id']}"
        self.patient = patient_headers(body)
        self.doctor = bearer_headers(doctor_tokens["d1"])
        self.other = bearer_headers(doctor_tokens["d2"])

    def analyze(self, ensemble):
        heartbeat("test-worker")
        self.assertEqual(self.client.post(self.url + "/analyze", headers=self.patient).status_code, 202)
        self.assertTrue(run_job(claim(), ensemble, {}))

    def image(self, headers=None):
        return self.client.get(self.url + "/analysis-image", headers=headers or {})

    def test_doctor_sees_overlay_after_analysis(self):
        self.assertEqual(self.image(self.doctor).status_code, 404)  # 분석 전
        self.analyze(FakeEnsemble(Image.new("RGB", (16, 16), (255, 0, 0))))

        response = self.image(self.doctor)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        with Image.open(BytesIO(response.content)) as overlay:
            self.assertEqual((overlay.format, overlay.size), ("PNG", (16, 16)))
        analysis = self.client.get(self.url, headers=self.doctor).json()["analysis"]
        self.assertTrue(analysis["overlayAvailable"])

    def test_only_assigned_doctor_can_see_overlay(self):
        self.analyze(FakeEnsemble(Image.new("RGB", (16, 16))))
        self.assertEqual(self.image().status_code, 401)              # 로그인 없음
        self.assertEqual(self.image(self.patient).status_code, 403)  # 환자 본인도 못 봄
        self.assertEqual(self.image(self.other).status_code, 404)    # 다른 의사

    def test_overlay_failure_keeps_analysis_result(self):
        with self.assertLogs(level="ERROR"):
            self.analyze(FakeEnsemble(error=RuntimeError("simulated CAM failure")))
        detail = self.client.get(self.url, headers=self.doctor).json()
        self.assertEqual(detail["aiState"], "완료")
        self.assertEqual(detail["analysis"]["candidate"], "acne")
        self.assertFalse(detail["analysis"]["overlayAvailable"])
        self.assertEqual(self.image(self.doctor).status_code, 404)

    def test_model_without_overlay_returns_404(self):
        self.analyze(FakeEnsemble(overlay=None))
        self.assertFalse(self.client.get(self.url, headers=self.doctor).json()["analysis"]["overlayAvailable"])
        self.assertEqual(self.image(self.doctor).status_code, 404)
