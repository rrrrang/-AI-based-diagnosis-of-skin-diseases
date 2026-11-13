import io
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.db import connect
from main import app


class PhotoContractTests(unittest.TestCase):
    """Real multipart intake contract; synthetic images, no ML accuracy claims."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            "SKINAI_DB_PATH": str(self.root / "backend.sqlite3"),
            "SKINAI_PHOTO_DIR": str(self.root / "photos"),
            "SKINAI_DEMO_DOCTOR_TOKENS": '{"d1":"photo-contract-doctor"}',
        }))
        self.client = self.enterContext(TestClient(app))
        self.fields = {
            "doctorId": "d1", "date": "2026-11-13", "time": "10:00",
            "patientName": "Synthetic photo contract", "age": "25", "gender": "none",
        }
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), (100, 120, 140)).save(buffer, format="PNG")
        self.png = buffer.getvalue()

    def upload(self, names, *, corrupt=None):
        files = [(name, (name + ".png", b"not an image" if name == corrupt else self.png,
                         "image/png")) for name in names]
        return self.client.post("/api/cases", data=self.fields, files=files)

    def assert_rejected_without_persistence(self, names, *, corrupt=None):
        response = self.upload(names, corrupt=corrupt)
        self.assertEqual(response.status_code, 422, response.text)
        with closing(connect()) as connection:
            for table in ("cases", "photos", "analysis_jobs"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(list((self.root / "photos").glob("**/*")), [])

    def assert_accepted(self, names):
        response = self.upload(names)
        self.assertEqual(response.status_code, 201, response.text)
        case = response.json()
        patient = {"Authorization": "Bearer " + case["accessToken"]}
        url = "/api/cases/" + case["id"]
        data = self.client.get(url, headers=patient).json()
        self.assertEqual(data["photoCount"], len(names))
        # This change does not make symptoms or duration mandatory on the API.
        self.assertEqual(data["symptoms"], [])
        self.assertEqual(data["duration"], "")
        for name in names:
            photo = self.client.get(url + "/photos/" + name[-1], headers=patient)
            self.assertEqual(photo.status_code, 200)
            self.assertEqual(photo.content, self.png)
        return url, patient, case["id"]

    def test_two_required_photos_accepted(self):
        self.assert_accepted(["photo0", "photo1"])

    def test_optional_third_photo_accepted(self):
        self.assert_accepted(["photo0", "photo1", "photo2"])

    def test_missing_front_rejected(self):
        self.assert_rejected_without_persistence(["photo1", "photo2"])

    def test_front_only_rejected(self):
        self.assert_rejected_without_persistence(["photo0"])

    def test_optional_photo_does_not_replace_primary_closeup(self):
        self.assert_rejected_without_persistence(["photo0", "photo2"])

    def test_duplicate_photo_parts_rejected(self):
        for names in (["photo0", "photo0", "photo1"],
                      ["photo0", "photo1", "photo1"],
                      ["photo0", "photo1", "photo2", "photo2"]):
            with self.subTest(names=names):
                self.assert_rejected_without_persistence(names)

    def test_unknown_or_fourth_file_rejected(self):
        for names in (["photo0", "photo1", "photo2", "photo3"],
                      ["photo0", "photo1", "attachment"]):
            with self.subTest(names=names):
                self.assert_rejected_without_persistence(names)

    def test_corrupt_optional_photo_leaves_no_partial_case(self):
        self.assert_rejected_without_persistence(["photo0", "photo1", "photo2"], corrupt="photo2")

    def test_openapi_declares_first_two_photos_required(self):
        schema = self.client.get("/openapi.json").json()
        reference = schema["paths"]["/api/cases"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
        body = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]
        self.assertIn("photo0", body["required"])
        self.assertIn("photo1", body["required"])
        self.assertNotIn("photo2", body["required"])

    def test_legacy_front_only_case_still_cannot_start_analysis(self):
        url, patient, case_id = self.assert_accepted(["photo0", "photo1"])
        # Simulate a record created under the OLD front-only intake contract.
        with closing(connect()) as connection, connection:
            connection.execute("DELETE FROM photos WHERE case_id = ? AND photo_index = 1", (case_id,))
        (self.root / "photos" / case_id / "1").unlink()
        response = self.client.post(url + "/analyze", headers=patient)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get(url, headers=patient).status_code, 200)


if __name__ == "__main__":
    unittest.main()
