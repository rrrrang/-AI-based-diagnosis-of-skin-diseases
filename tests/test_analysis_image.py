"""AI 표시 그림(analysis-image) 테스트. 모델 대신 가짜 앙상블을 쓴다."""
import builtins
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
        self.photos_dir = root / "photos"
        self.analysis_dir = root / "analysis"
        doctor_tokens = new_doctor_tokens()
        self.enterContext(patch.dict(os.environ, {
            "SKINAI_DB_PATH": str(root / "db"),
            "SKINAI_PHOTO_DIR": str(self.photos_dir),
            "SKINAI_ANALYSIS_DIR": str(self.analysis_dir),
            **doctor_environment(doctor_tokens),
        }))
        self.client = self.enterContext(TestClient(app))
        body = self.client.post("/api/cases", data={
            "doctorId": "d1", "date": "2026-11-17", "time": "10:00",
            "patientName": "Demo", "age": "25", "gender": "none",
        }, files={key: ("photo.png", png(), "image/png") for key in ("photo0", "photo1")}).json()
        self.case_id = body["id"]
        self.url = f"/api/cases/{self.case_id}"
        self.patient = patient_headers(body)
        self.doctor = bearer_headers(doctor_tokens["d1"])
        self.other = bearer_headers(doctor_tokens["d2"])

    def analyze(self, ensemble):
        heartbeat("test-worker")
        self.assertEqual(self.client.post(self.url + "/analyze", headers=self.patient).status_code, 202)
        job = claim()
        self.assertTrue(run_job(job, ensemble, {}))
        return job

    def image(self, headers=None):
        return self.client.get(self.url + "/analysis-image", headers=headers or {})

    def photo_snapshot(self):
        return {path.relative_to(self.photos_dir): path.read_bytes()
                for path in self.photos_dir.rglob("*") if path.is_file()}

    def assert_overlay_failed(self):
        detail = self.client.get(self.url, headers=self.doctor).json()
        self.assertEqual(detail["aiState"], "완료")
        self.assertEqual(detail["analysis"]["candidate"], "acne")
        self.assertFalse(detail["analysis"]["overlayAvailable"])
        self.assertEqual(self.image(self.doctor).status_code, 404)

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

    def test_overlay_saves_separately_with_readonly_source_photos(self):
        before = self.photo_snapshot()
        original_open = builtins.open

        def readonly_photos(file, mode="r", *args, **kwargs):
            # Windows directory chmod does not enforce read-only mounts. Reject
            # source writes at the file boundary on every test platform instead.
            if isinstance(file, (str, os.PathLike)) and any(flag in mode for flag in "wax+"):
                if Path(file).resolve().is_relative_to(self.photos_dir.resolve()):
                    raise PermissionError("Source photo storage is read-only")
            return original_open(file, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=readonly_photos):
            job = self.analyze(FakeEnsemble(Image.new("RGB", (16, 16))))

        output = self.analysis_dir / self.case_id / f"overlay-{job['id']}.png"
        self.assertTrue(output.is_file())
        self.assertEqual(self.image(self.doctor).status_code, 200)
        self.assertEqual(self.photo_snapshot(), before)
        self.assertEqual(list(output.parent.iterdir()), [output])

    def test_only_assigned_doctor_can_see_overlay(self):
        self.analyze(FakeEnsemble(Image.new("RGB", (16, 16))))
        self.assertEqual(self.image().status_code, 401)              # 로그인 없음
        self.assertEqual(self.image(self.patient).status_code, 403)  # 환자 본인도 못 봄
        self.assertEqual(self.image(self.other).status_code, 404)    # 다른 의사

    def test_overlay_failure_keeps_analysis_result(self):
        with self.assertLogs(level="ERROR"):
            self.analyze(FakeEnsemble(error=RuntimeError("simulated CAM failure")))
        self.assert_overlay_failed()

    def test_overlay_directory_failure_keeps_analysis_result_and_photos(self):
        before = self.photo_snapshot()
        self.analysis_dir.write_bytes(b"A file prevents output directory creation")
        with self.assertLogs(level="ERROR"):
            self.analyze(FakeEnsemble(Image.new("RGB", (16, 16))))
        self.assert_overlay_failed()
        self.assertEqual(self.photo_snapshot(), before)

    def test_overlay_save_failure_removes_partial_file_and_keeps_analysis(self):
        before = self.photo_snapshot()

        def fail_save(image, path, **kwargs):
            Path(path).write_bytes(b"partial PNG")
            raise PermissionError("Output storage rejected the write")

        with patch.object(Image.Image, "save", fail_save), self.assertLogs(level="ERROR"):
            self.analyze(FakeEnsemble(Image.new("RGB", (16, 16))))
        self.assert_overlay_failed()
        self.assertEqual(list((self.analysis_dir / self.case_id).iterdir()), [])
        self.assertEqual(self.photo_snapshot(), before)

    def test_legacy_overlay_is_readable_without_moving_or_changing_it(self):
        job = self.analyze(FakeEnsemble(Image.new("RGB", (16, 16), (255, 0, 0))))
        output = self.analysis_dir / self.case_id / f"overlay-{job['id']}.png"
        legacy = self.photos_dir / self.case_id / output.name
        output.replace(legacy)  # Fixture representing a pre-migration result.
        before = self.photo_snapshot()
        self.assertEqual(self.image(self.doctor).content, legacy.read_bytes())
        self.assertFalse(output.exists())
        self.assertEqual(self.photo_snapshot(), before)
        self.assertEqual(self.image(self.patient).status_code, 403)
        self.assertEqual(self.image(self.other).status_code, 404)

    def test_new_overlay_takes_precedence_over_legacy_copy(self):
        job = self.analyze(FakeEnsemble(Image.new("RGB", (16, 16), (255, 0, 0))))
        output = self.analysis_dir / self.case_id / f"overlay-{job['id']}.png"
        legacy = self.photos_dir / self.case_id / output.name
        legacy.write_bytes(png(color=(0, 255, 0)))
        self.assertEqual(self.image(self.doctor).content, output.read_bytes())

    def test_model_without_overlay_returns_404(self):
        self.analyze(FakeEnsemble(overlay=None))
        self.assertFalse(self.client.get(self.url, headers=self.doctor).json()["analysis"]["overlayAvailable"])
        self.assertEqual(self.image(self.doctor).status_code, 404)
