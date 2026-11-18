"""로그인 테스트: 환자는 전화번호+이름, 의사는 아이디+비밀번호."""
import json
import os
import tempfile
import time
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.db import connect
from ci.backend_contract.auth_support import (
    login_patient, login_doctor, logout_session, patient_headers,
)
from main import app

DOCTORS = {"d1": {"loginId": "doctor1", "password": "doctor-pass-1"},
           "d2": {"loginId": "doctor2", "password": "doctor-pass-2"}}


def png():
    buffer = BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    return buffer.getvalue()


class AuthTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {
            "SKINAI_DB_PATH": str(root / "db"),
            "SKINAI_PHOTO_DIR": str(root / "photos"),
            "SKINAI_DOCTOR_ACCOUNTS": json.dumps(DOCTORS),
            "SKINAI_DEMO_DOCTOR_TOKENS": "{}",  # Login tests must not use the legacy bypass.
        }))
        self.enterContext(patch("app.accounts.PASSWORD_ITERATIONS", 1000))  # 테스트를 빠르게
        self.client = self.enterContext(TestClient(app))

    # 도우미 -----------------------------------------------------------------
    def patient(self, phone="010-1234-5678", name="홍길동", create=True):
        return self.client.post("/api/auth/patient", json={"phone": phone, "name": name, "create": create})

    def patient_session(self, phone="010-1234-5678", name="홍길동"):
        return login_patient(self.client, phone=phone, name=name, create=True).headers()

    def doctor_session(self, login_id="doctor1", password="doctor-pass-1"):
        doctor_id = next(key for key, value in DOCTORS.items() if value["loginId"] == login_id)
        return login_doctor(self.client, login_id=login_id, password=password,
                            doctor_id=doctor_id).headers()

    def submit(self, headers=None):
        return self.client.post("/api/cases", headers=headers or {}, data={
            "doctorId": "d1", "date": "2026-11-20", "time": "10:00",
            "patientName": "홍길동", "age": "25", "gender": "none",
        }, files={key: ("photo.png", png(), "image/png") for key in ("photo0", "photo1")})

    # 환자 -------------------------------------------------------------------
    def test_first_visit_creates_account_then_same_values_log_in(self):
        first = self.patient().json()
        self.assertEqual((first["role"], first["name"], first["loginId"]), ("patient", "홍길동", "01012345678"))
        again = self.patient("01012345678", " 홍길동 ", create=False)  # 하이픈·앞뒤 공백은 무시
        self.assertEqual(again.status_code, 200)
        headers = {"Authorization": f"Bearer {again.json()['accessToken']}"}
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).json()["name"], "홍길동")
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_check_without_account_and_wrong_name(self):
        self.assertEqual(self.patient(create=False).status_code, 401)  # 기록 없이 '내 예약 확인'
        self.patient()
        self.assertEqual(self.patient(name="김철수").status_code, 401)  # 다른 이름으로는 못 들어옴
        self.assertEqual(self.patient(phone="12345", name="홍길동").status_code, 422)
        self.assertEqual(self.patient(name="   ").status_code, 422)

    def test_name_is_stored_only_as_hash(self):
        token = self.patient().json()["accessToken"]
        with closing(connect()) as db:
            stored = db.execute("SELECT password_hash FROM users WHERE login_id = '01012345678'").fetchone()[0]
            sessions = [row[0] for row in db.execute("SELECT token_hash FROM sessions")]
        self.assertNotIn("홍길동", stored)
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertNotIn(token, sessions)

    def test_lockout_after_five_wrong_names(self):
        self.patient()
        for _ in range(5):
            self.assertEqual(self.patient(name="김철수", create=False).status_code, 401)
        self.assertEqual(self.patient(create=False).status_code, 429)  # 맞는 이름도 5분 동안 잠김
        with patch("app.routers.auth.time.time", return_value=time.time() + 301):
            self.assertEqual(self.patient(create=False).status_code, 200)

    def test_my_reservations_show_only_my_cases(self):
        mine = self.patient_session()
        other = self.patient_session("01099998888", "김철수")
        case_id = self.submit(mine).json()["id"]

        items = self.client.get("/api/me/cases", headers=mine).json()
        self.assertEqual([item["id"] for item in items], [case_id])
        self.assertEqual(items[0]["doctorId"], "d1")
        self.assertIn("doctorName", items[0])
        self.assertEqual(items[0]["photoIndices"], [0, 1])
        self.assertNotIn("analysis", items[0])                     # AI 결과는 환자에게 없음
        self.assertEqual(self.client.get("/api/me/cases", headers=other).json(), [])
        self.assertEqual(self.client.get(f"/api/cases/{case_id}/photos/0", headers=mine).status_code, 200)
        self.assertEqual(self.client.get(f"/api/cases/{case_id}/photos/0", headers=other).status_code, 404)
        self.assertEqual(self.client.get(f"/api/cases/{case_id}").status_code, 401)
        self.assertNotEqual(self.client.post(f"/api/cases/{case_id}/analyze", headers=mine).status_code, 404)

    # 의사 -------------------------------------------------------------------
    def test_doctor_login_and_review(self):
        patient = self.patient_session()
        case_id = self.submit(patient).json()["id"]
        doctor = self.doctor_session()
        other = self.doctor_session("doctor2", "doctor-pass-2")

        me = self.client.get("/api/auth/me", headers=doctor).json()
        self.assertEqual((me["doctorId"], me["name"], me["hospital"]), ("d1", "김서연", "서울아산병원"))
        doctors = self.client.get("/api/doctors").json()
        self.assertEqual([(d["id"], d["name"], d["hospital"]) for d in doctors],
                         [("d1", "김서연", "서울아산병원"), ("d2", "박지훈", "삼성서울병원"), ("d3", "이다은", "세브란스병원")])
        self.assertEqual([c["id"] for c in self.client.get("/api/cases", headers=doctor).json()], [case_id])
        self.assertEqual(self.client.get(f"/api/cases/{case_id}", headers=other).status_code, 404)
        review = {"diagnosis": "여드름 의심", "opinion": "보습을 잘 해 주세요", "visitRequired": False,
                  "visitMessage": "", "reviewState": "임시 저장"}
        self.client.patch(f"/api/cases/{case_id}/review", headers=doctor, json=review)
        self.assertNotIn("opinion", self.client.get("/api/me/cases", headers=patient).json()[0])  # 임시 저장은 숨김
        review["reviewState"] = "결과 전달 완료"
        self.assertEqual(self.client.patch(f"/api/cases/{case_id}/review", headers=doctor, json=review).status_code, 200)
        published = self.client.get("/api/me/cases", headers=patient).json()[0]
        self.assertEqual((published["reviewState"], published["opinion"]), ("결과 전달 완료", "보습을 잘 해 주세요"))
        self.assertEqual(self.client.get("/api/me/cases", headers=doctor).status_code, 403)

    def test_doctor_wrong_password_and_patient_cannot_act_as_doctor(self):
        bad = self.client.post("/api/auth/login", json={"loginId": "doctor1", "password": "wrong-pass"})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login",
                                          json={"loginId": "nobody", "password": "x"}).status_code, 401)
        patient = self.patient_session()
        self.assertEqual(self.client.get("/api/cases", headers=patient).status_code, 403)
        case_id = self.submit(patient).json()["id"]
        review = {"diagnosis": "차단해야 할 수정", "opinion": "환자는 의사 소견을 쓸 수 없음",
                  "visitRequired": False, "visitMessage": "", "reviewState": "결과 전달 완료"}
        self.assertEqual(self.client.patch(f"/api/cases/{case_id}/review", headers=patient,
                                           json=review).status_code, 403)
        self.assertEqual(self.client.get(f"/api/cases/{case_id}", headers=self.doctor_session())
                         .json()["reviewState"], "검토 대기")

    def test_doctor_five_failures_lock_then_unlock_after_five_minutes(self):
        now = time.time()
        payload = {"loginId": "doctor1", "password": "wrong-password"}
        with patch("app.routers.auth.time.time", return_value=now):
            for attempt in range(1, 6):
                with self.subTest(failed_attempt=attempt):
                    self.assertEqual(self.client.post("/api/auth/login", json=payload).status_code, 401)
            self.assertEqual(self.client.post("/api/auth/login", json=payload).status_code, 429)
            payload["password"] = "doctor-pass-1"
            self.assertEqual(self.client.post("/api/auth/login", json=payload).status_code, 429)
        with patch("app.routers.auth.time.time", return_value=now + 299):
            self.assertEqual(self.client.post("/api/auth/login", json=payload).status_code, 429)
        with patch("app.routers.auth.time.time", return_value=now + 301):
            session = login_doctor(self.client, login_id="doctor1", password="doctor-pass-1")
            self.assertEqual(self.client.get("/api/cases", headers=session.headers()).status_code, 200)

    def test_successful_doctor_login_resets_previous_failures(self):
        wrong = {"loginId": "doctor1", "password": "wrong-password"}
        for _ in range(4):
            self.assertEqual(self.client.post("/api/auth/login", json=wrong).status_code, 401)
        login_doctor(self.client, login_id="doctor1", password="doctor-pass-1")
        for _ in range(4):
            self.assertEqual(self.client.post("/api/auth/login", json=wrong).status_code, 401)
        # If success did not clear the counter, this would already be locked.
        self.assertEqual(self.client.get("/api/cases", headers=self.doctor_session()).status_code, 200)

    def test_doctor_logout_blocks_old_session_reads_and_review_writes(self):
        case_id = self.submit(self.patient_session()).json()["id"]
        url = f"/api/cases/{case_id}"
        session = login_doctor(self.client, login_id="doctor1", password="doctor-pass-1")
        old_headers = session.headers()
        self.assertEqual(self.client.get(url, headers=old_headers).status_code, 200)
        logout_session(self.client, session)
        for path, expected in (("/api/auth/me", 401), ("/api/cases", 403),
                               (url, 404), (url + "/photos/0", 404)):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=old_headers).status_code, expected)
        review = {"diagnosis": "로그아웃 뒤 차단할 수정", "opinion": "저장되면 안 됨",
                  "visitRequired": False, "visitMessage": "", "reviewState": "결과 전달 완료"}
        self.assertEqual(self.client.patch(url + "/review", headers=old_headers,
                                           json=review).status_code, 403)
        fresh = login_doctor(self.client, login_id="doctor1", password="doctor-pass-1")
        self.assertEqual(self.client.get("/api/cases", headers=fresh.headers()).status_code, 200)
        detail = self.client.get(url, headers=fresh.headers()).json()
        self.assertEqual(detail["reviewState"], "검토 대기")
        self.assertNotIn("opinion", detail)
        self.assertEqual(self.client.get("/api/auth/me", headers=old_headers).status_code, 401)

    def test_patient_logout_revokes_session_but_not_legacy_case_credential(self):
        session = login_patient(self.client, phone="01012345678", name="홍길동", create=True)
        old_headers = session.headers()
        intake = self.submit(old_headers).json()
        case_headers = patient_headers(intake)
        url = f"/api/cases/{intake['id']}"
        logout_session(self.client, session)
        for path in ("/api/auth/me", "/api/me/cases"):
            self.assertEqual(self.client.get(path, headers=old_headers).status_code, 401)
        self.assertEqual(self.client.get(url, headers=old_headers).status_code, 404)
        self.assertEqual(self.submit(old_headers).status_code, 401)
        # Explicit compatibility contract; do not call this complete access revocation.
        self.assertEqual(self.client.get(url, headers=case_headers).status_code, 200)
        fresh = login_patient(self.client, phone="01012345678", name="홍길동", create=False)
        self.assertEqual([case["id"] for case in self.client.get("/api/me/cases", headers=fresh.headers()).json()],
                         [intake["id"]])

    def test_bad_or_expired_session(self):
        self.assertEqual(self.submit({"Authorization": "Bearer not-a-real-token"}).status_code, 401)
        self.assertEqual(self.submit().status_code, 201)  # 로그인 없는 기존 접수(자동 검사용)는 그대로
        headers = self.patient_session()
        with patch("app.accounts.time.time", return_value=time.time() + 13 * 60 * 60):
            self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)
