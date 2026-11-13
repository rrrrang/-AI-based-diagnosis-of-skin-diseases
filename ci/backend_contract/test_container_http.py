"""HTTP-only checks against the separately running backend container."""
import argparse
import io
import json
import re
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from PIL import Image


REVIEW_KEYS = ("diagnosis", "opinion", "visitRequired", "visitMessage", "reviewState")


class ContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = httpx.Client(base_url=cls.base_url, timeout=15,
                                 trust_env=False, follow_redirects=False)
        cls.addClassCleanup(cls.client.close)
        response = cls.client.get("/api/health")
        if response.status_code != 200 or response.json().get("status") != "ok":
            raise RuntimeError("Test backend is not healthy")
        # Check both doctor identities before creating any test records.
        for doctor in ("d1", "d2"):
            response = cls.client.get("/api/cases", params={"doctorId": doctor},
                                      headers=cls.auth(cls.tokens[doctor]))
            if response.status_code != 200:
                raise RuntimeError("Doctor test settings do not match this server")
        stream = io.BytesIO()
        Image.new("RGB", (32, 32), (120, 140, 160)).save(stream, format="PNG")
        cls.photo = stream.getvalue()

    @staticmethod
    def auth(token):
        return {"Authorization": "Bearer " + token} if token else {}

    def new_case(self, doctor="d1"):
        name = "CI 가상 검사자 " + uuid4().hex[:8]
        response = self.client.post("/api/cases", data={
            "doctorId": doctor, "date": date.today().isoformat(), "time": "10:00",
            "patientName": name, "age": "25", "gender": "none",
            "symptoms": ["가려움", "붉어짐"], "description": "합성 사진 API 검사",
        }, files={key: ("synthetic.png", self.photo, "image/png")
                  for key in ("photo0", "photo1")})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(isinstance(data.get("id"), str) and data["id"].startswith("CASE-"))
        self.assertTrue(isinstance(data.get("accessToken"), str) and bool(data["accessToken"]))
        self.assertEqual(data.get("aiState"), "대기")
        self.assertEqual(data.get("reviewState"), "검토 대기")
        return "/api/cases/" + data["id"], data["accessToken"], name

    def detail(self, url, token):
        response = self.client.get(url, headers=self.auth(token))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def hidden(self, data, *, patient=True):
        self.assertEqual(data.get("reviewState"), "검토 대기")
        keys = (*REVIEW_KEYS[:-1], "analysis") if patient else REVIEW_KEYS[:-1]
        for key in keys:
            self.assertNotIn(key, data, "Unpublished field exposed: " + key)

    def review_matches(self, data, expected):
        for key in REVIEW_KEYS:
            self.assertEqual(data.get(key), expected[key], key)

    def save_review(self, url, token, review, expected=200):
        response = self.client.patch(url + "/review", headers=self.auth(token), json=review)
        self.assertEqual(response.status_code, expected)

    @staticmethod
    def draft():
        return {"diagnosis": "검사용 판단", "opinion": "검사용 안내",
                "visitRequired": True, "visitMessage": "검사용 방문 안내",
                "reviewState": "임시 저장"}

    def test_01_photo_intake_and_read(self):
        url, patient, name = self.new_case()
        for token in (patient, self.tokens["d1"]):
            detail = self.detail(url, token)
            self.assertEqual(detail["patientName"], name)
            self.assertEqual(detail["symptoms"], ["가려움", "붉어짐"])
            self.assertEqual(detail["photoCount"], 2)
            for index in (0, 1):
                response = self.client.get(url + f"/photos/{index}", headers=self.auth(token))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, self.photo)
                self.assertEqual(response.headers.get("cache-control"), "private, no-store")

    def test_02_other_patient_blocked(self):
        first, first_token, _ = self.new_case()
        second, second_token, _ = self.new_case()
        self.assertNotEqual(first, second)
        self.assertTrue(first_token != second_token, "Patient tokens must differ")
        for url, other in ((first, second_token), (second, first_token)):
            for suffix in ("", "/photos/0", "/photos/1"):
                for token, expected in ((None, 401), (other, 404)):
                    with self.subTest(suffix=suffix, expected=expected):
                        response = self.client.get(url + suffix, headers=self.auth(token))
                        self.assertEqual(response.status_code, expected)
            response = self.client.post(url + "/analyze", headers=self.auth(other))
            self.assertEqual(response.status_code, 404)
        response = self.client.get("/api/cases", headers=self.auth(first_token))
        self.assertEqual(response.status_code, 403)

    def test_03_other_doctor_blocked(self):
        first, _, _ = self.new_case("d1")
        second, _, _ = self.new_case("d2")
        for own, other, doctor, other_doctor in (
            (first, second, "d1", "d2"), (second, first, "d2", "d1")
        ):
            headers = self.auth(self.tokens[doctor])
            for suffix in ("", "/photos/0", "/photos/1"):
                self.assertEqual(self.client.get(own + suffix, headers=headers).status_code, 200)
                self.assertEqual(self.client.get(other + suffix, headers=headers).status_code, 404)
            response = self.client.get("/api/cases", headers=headers)
            self.assertEqual(response.status_code, 200)
            rows = response.json()
            self.assertIsInstance(rows, list)
            self.assertTrue(all(row["doctorId"] == doctor for row in rows))
            ids = {row["id"] for row in rows}
            self.assertIn(own.rsplit("/", 1)[1], ids)
            self.assertNotIn(other.rsplit("/", 1)[1], ids)
            response = self.client.get("/api/cases", params={"doctorId": other_doctor}, headers=headers)
            self.assertEqual(response.status_code, 403)

    def test_04_unauthorized_confirmation_blocked(self):
        url, patient, _ = self.new_case()
        _, other_patient, _ = self.new_case()
        review = {**self.draft(), "reviewState": "결과 전달 완료"}
        for token, expected in ((None, 403), (patient, 403), (other_patient, 403),
                                (self.tokens["d2"], 404)):
            self.save_review(url, token, review, expected)
            self.hidden(self.detail(url, patient))
            self.hidden(self.detail(url, self.tokens["d1"]), patient=False)

    def test_05_draft_and_published_result(self):
        url, patient, _ = self.new_case()
        _, other_patient, _ = self.new_case()
        doctor = self.tokens["d1"]
        self.hidden(self.detail(url, patient))
        draft = self.draft()
        self.save_review(url, doctor, draft)
        self.hidden(self.detail(url, patient))
        self.review_matches(self.detail(url, doctor), draft)
        published = {**draft, "reviewState": "결과 전달 완료"}
        self.save_review(url, doctor, published)
        self.review_matches(self.detail(url, patient), published)
        self.review_matches(self.detail(url, doctor), published)
        self.assertNotIn("analysis", self.detail(url, patient))
        changed = {"diagnosis": "미공개 변경", "opinion": "미공개 안내",
                   "visitRequired": False, "visitMessage": "미공개 방문 안내",
                   "reviewState": "임시 저장"}
        self.save_review(url, doctor, changed)
        self.review_matches(self.detail(url, doctor), changed)
        self.review_matches(self.detail(url, patient), published)
        self.assertNotIn("analysis", self.detail(url, patient))
        for token in (other_patient, self.tokens["d2"]):
            self.assertEqual(self.client.get(url, headers=self.auth(token)).status_code, 404)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18140")
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost")
            or not url.port or url.username or url.password or url.path not in ("", "/")
            or url.query or url.fragment):
        parser.error("Use a local test server URL with an explicit port")
    try:
        lines = Path(args.env_file).read_text(encoding="utf-8-sig").splitlines()
        values = [line.partition("=")[2] for line in lines
                  if line.startswith("SKINAI_DEMO_DOCTOR_TOKENS=")]
        if len(values) != 1:
            raise ValueError()
        tokens = json.loads(values[0])
        if (not isinstance(tokens, dict) or
                any(not isinstance(tokens.get(key), str) or
                    not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", tokens[key]) for key in ("d1", "d2")) or
                tokens["d1"] == tokens["d2"]):
            raise ValueError()
    except (OSError, UnicodeError, ValueError, TypeError):
        parser.error("Read failed: provide the env file with distinct d1/d2 test tokens")
    ContainerTests.base_url = args.base_url.rstrip("/")
    ContainerTests.tokens = tokens
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContainerTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and result.testsRun == 5 and not result.skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
