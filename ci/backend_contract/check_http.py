"""Isolated real-HTTP verification; model outcomes are synthetic, not ML inference."""
import argparse
import copy
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import unittest
from contextlib import closing
from datetime import datetime, timezone

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OBS = {}
REVIEW_FIELDS = ("diagnosis", "opinion", "visitRequired", "visitMessage", "reviewState")
EXPECTED_TESTS = (
    "test_01_health_and_openapi",
    "test_02_intake_korean_and_repeated_fields",
    "test_03_required_fields_and_invalid_values",
    "test_04_corrupt_photo",
    "test_05_webp_rejected",
    "test_06_valid_png_between_8_and_10_mib_rejected",
    "test_07_over_16_megapixels_rejected",
    "test_08_authorization_isolation",
    "test_09_no_worker_503_keeps_case",
    "test_10_deferred_doctor_confirmation",
    "test_11_normal_doctor_confirmation",
    "test_12_model_failure_explicit_retry",
    "test_13_front_only_optional_fields_behavior",
    "test_14_patient_own_photo_behavior",
    "test_15_error_request_id",
    "test_16_api_restart_persistence",
    "test_17_valid_jpeg_accepted",
)


def image_bytes(fmt="PNG", size=(32, 32)):
    out = io.BytesIO()
    Image.new("RGB", size, (125, 140, 160)).save(out, format=fmt)
    return out.getvalue()


PNG = image_bytes()


class Server:
    process = None
    log = None

    def start(self):
        global PORT, BASE
        with socket.socket() as probe:
            # Reopening a just-closed fixed port can hit Windows TIME_WAIT.
            # Persistence is verified through the same DB, on a fresh test port.
            probe.bind(("127.0.0.1", PORT if self.process is None else 0))
            PORT = probe.getsockname()[1]
        BASE = f"http://127.0.0.1:{PORT}"
        self.ports = getattr(self, "ports", []) + [PORT]
        self.log = (RUN / "server.log").open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT), "--no-access-log"],
            cwd=ROOT, env=os.environ.copy(), stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for _ in range(150):
            if self.process.poll() is not None:
                raise RuntimeError("Isolated API exited; see server.log")
            try:
                response = httpx.get(BASE + "/api/cases", headers=DOCTOR, timeout=1, trust_env=False)
                # Random per-run doctor credentials prevent a different local
                # server from being mistaken for this verification process.
                if response.status_code == 200 and self.process.poll() is None:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        raise RuntimeError("API startup timeout")

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()


SERVER = Server()


class LiveApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = httpx.Client(base_url=BASE, timeout=15, trust_env=False)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def intake(self, fields=None, lesion=True, photo=PNG, filename="synthetic.png", mime="image/png", omit=()):
        data = {"doctorId": "d1", "date": "2026-11-13", "time": "10:00", "patientName": "가상 검사자", "age": "25", "gender": "none",
                "symptoms": ["가려움", "붉어짐"], "duration": "3일", "description": "합성 이미지 API 검증"}
        data.update(fields or {})
        for key in omit:
            data.pop(key, None)
        files = {"photo0": (filename, photo, mime)}
        if lesion:
            files["photo1"] = ("synthetic-lesion.png", PNG, "image/png")
        if "photo0" in omit:
            files.pop("photo0")
        return self.client.post("/api/cases", data=data, files=files)

    def new_case(self, **kwargs):
        response = self.intake(**kwargs)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["id"].startswith("CASE-"))
        self.assertTrue(data["accessToken"])
        return "/api/cases/" + data["id"], {"Authorization": "Bearer " + data["accessToken"]}

    def complete_with_fake_model(self, url, headers, decision):
        from app.jobs import claim, heartbeat
        from app.worker import run_job
        from ensemble.policy import Prediction, decide
        thresholds = {"mobilenet": .82, "resnet50": .85, "yolo": .70}
        if decision == "normal_consensus":
            predictions = {"mobilenet": Prediction("normal", .95), "resnet50": Prediction("normal", .96), "yolo": None}
        else:
            predictions = {"mobilenet": Prediction("acne", .95), "resnet50": Prediction("rosacea", .96), "yolo": None}
        result = decide(predictions, thresholds)
        self.assertEqual(result["decision"], decision)
        class FakeModel:
            def predict(self, image, image_id, role):
                return copy.deepcopy(result)
        heartbeat("isolated-http-test-worker")
        queued = self.client.post(url + "/analyze", headers=headers)
        self.assertEqual(queued.status_code, 202)
        duplicate = self.client.post(url + "/analyze", headers=headers)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["jobId"], queued.json()["jobId"])
        job = claim()
        self.assertEqual(job["id"], queued.json()["jobId"])
        self.assertTrue(run_job(job, FakeModel(), {"test": "synthetic-not-real-weights"}))
        return result

    def review_flow(self, decision):
        url, patient = self.new_case()
        self.complete_with_fake_model(url, patient, decision)
        def detail(headers):
            response = self.client.get(url, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def assert_unpublished(data):
            self.assertEqual(data["aiState"], "완료")
            self.assertEqual(data["reviewState"], "검토 대기")
            self.assertNotIn("analysis", data)
            for field in REVIEW_FIELDS[:-1]:
                self.assertNotIn(field, data, f"Unpublished {field} exposed to patient")

        def assert_review(data, expected, *, doctor):
            self.assertEqual({key: data[key] for key in REVIEW_FIELDS}, expected)
            if doctor:
                self.assertEqual(data["analysis"]["decision"], decision)
            else:
                self.assertNotIn("analysis", data)

        assert_unpublished(detail(patient))
        doctor_view = detail(DOCTOR)
        self.assertEqual(doctor_view["analysis"]["decision"], decision)
        self.assertEqual(doctor_view["reviewState"], "검토 대기")
        review = {"diagnosis": "검증용 의사 판단", "opinion": "검증용 확정 안내",
                  "visitRequired": True, "visitMessage": "공개할 대면 진료 안내", "reviewState": "임시 저장"}
        self.assertEqual(self.client.patch(url + "/review", headers=patient, json=review).status_code, 403)
        self.assertEqual(self.client.patch(url + "/review", headers=OTHER, json=review).status_code, 404)
        assert_unpublished(detail(patient))
        self.assertEqual(self.client.patch(url + "/review", headers=DOCTOR, json=review).status_code, 200)
        assert_unpublished(detail(patient))
        assert_review(detail(DOCTOR), review, doctor=True)
        review["reviewState"] = "결과 전달 완료"
        self.assertEqual(self.client.patch(url + "/review", headers=DOCTOR, json=review).status_code, 200)
        published_review = review.copy()
        assert_review(detail(patient), published_review, doctor=False)
        assert_review(detail(DOCTOR), published_review, doctor=True)
        review.update(diagnosis="미공개 변경 진단", opinion="아직 공개하지 않은 변경",
                      visitRequired=False, visitMessage="미공개 변경 안내", reviewState="임시 저장")
        self.assertEqual(self.client.patch(url + "/review", headers=DOCTOR, json=review).status_code, 200)
        assert_review(detail(patient), published_review, doctor=False)
        assert_review(detail(DOCTOR), review, doctor=True)
        OBS[decision] = "All five review fields require doctor publication; AI stays doctor-only; later drafts preserve the published review"

    def test_01_health_and_openapi(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertTrue(response.headers.get("x-request-id"))
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertIn("/api/cases", self.client.get("/openapi.json").json()["paths"])
        doctors = self.client.get("/api/doctors")
        self.assertEqual(doctors.status_code, 200)
        self.assertEqual(len(doctors.json()), 3)

    def test_02_intake_korean_and_repeated_fields(self):
        url, headers = self.new_case()
        data = self.client.get(url, headers=headers).json()
        self.assertEqual(data["patientName"], "가상 검사자")
        self.assertEqual(data["symptoms"], ["가려움", "붉어짐"])
        self.assertEqual(data["photoCount"], 2)
        self.assertEqual(data["reviewState"], "검토 대기")

    def test_03_required_fields_and_invalid_values(self):
        for field in ("patientName", "photo0"):
            with self.subTest(field=field):
                self.assertEqual(self.intake(omit=(field,)).status_code, 422)
        for fields in ({"doctorId": "unknown"}, {"age": "-1"}, {"gender": "invalid"}, {"date": "invalid"}):
            with self.subTest(fields=fields):
                self.assertEqual(self.intake(fields=fields).status_code, 422)

    def test_04_corrupt_photo(self):
        self.assertEqual(self.intake(photo=b"not an image").status_code, 422)

    def test_05_webp_rejected(self):
        response = self.intake(photo=image_bytes("WEBP"), filename="photo.webp", mime="image/webp")
        self.assertEqual(response.status_code, 422)
        OBS["webp"] = {"http": response.status_code, "detail": response.json()["detail"]}

    def test_06_valid_png_between_8_and_10_mib_rejected(self):
        output = io.BytesIO()
        Image.frombytes("RGB", (1800, 1800), os.urandom(1800 * 1800 * 3)).save(output, format="PNG")
        blob = output.getvalue()
        self.assertTrue(8 * 1024**2 < len(blob) < 10 * 1024**2)
        response = self.intake(photo=blob)
        self.assertEqual(response.status_code, 413)
        OBS["8_to_10_mib_png"] = {"bytes": len(blob), "http": response.status_code, "detail": response.json()["detail"]}

    def test_07_over_16_megapixels_rejected(self):
        response = self.intake(photo=image_bytes(size=(4001, 4000)))
        self.assertEqual(response.status_code, 422)
        OBS["over_16mp"] = {"http": response.status_code, "detail": response.json()["detail"]}

    def test_08_authorization_isolation(self):
        from app.db import connect

        url, patient = self.new_case()
        other_url, other_patient = self.new_case(fields={"doctorId": "d2"})
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, headers=other_patient).status_code, 404)
        self.assertEqual(self.client.get(url, headers=OTHER).status_code, 404)
        self.assertEqual(self.client.get(other_url, headers=patient).status_code, 404)
        self.assertEqual(self.client.get(other_url, headers=DOCTOR).status_code, 404)
        self.assertEqual(self.client.get("/api/cases", headers=patient).status_code, 403)
        self.assertEqual(self.client.get("/api/cases?doctorId=d1", headers=OTHER).status_code, 403)
        # Include earlier test cases in the expected sets while ensuring both
        # doctors own at least one case; a missing SQL filter must fail here.
        with closing(connect()) as connection:
            expected = {doctor: {row[0] for row in connection.execute(
                "SELECT id FROM cases WHERE doctor_id = ?", (doctor,)
            )} for doctor in ("d1", "d2")}
        self.assertIn(url.rsplit("/", 1)[-1], expected["d1"])
        self.assertIn(other_url.rsplit("/", 1)[-1], expected["d2"])
        for doctor, headers in (("d1", DOCTOR), ("d2", OTHER)):
            for path in ("/api/cases", f"/api/cases?doctorId={doctor}"):
                with self.subTest(doctor=doctor, path=path):
                    response = self.client.get(path, headers=headers)
                    self.assertEqual(response.status_code, 200, response.text)
                    rows = response.json()
                    self.assertEqual({row["id"] for row in rows}, expected[doctor])
                    self.assertEqual(len(rows), len(expected[doctor]))
                    self.assertTrue(all(row["doctorId"] == doctor for row in rows))
        self.assertEqual(self.client.get(url + "/photos/0").status_code, 401)
        self.assertEqual(self.client.get(url + "/photos/0", headers=OTHER).status_code, 404)
        self.assertEqual(self.client.get(url + "/photos/0", headers=other_patient).status_code, 404)
        self.assertEqual(self.client.get(other_url + "/photos/0", headers=patient).status_code, 404)
        self.assertEqual(self.client.post(url + "/analyze").status_code, 401)
        self.assertEqual(self.client.post(url + "/analyze", headers=other_patient).status_code, 404)
        self.assertEqual(self.client.post(other_url + "/analyze", headers=patient).status_code, 404)
        with closing(connect()) as connection:
            for case_url in (url, other_url):
                count = connection.execute("SELECT COUNT(*) FROM analysis_jobs WHERE case_id = ?",
                                           (case_url.rsplit("/", 1)[-1],)).fetchone()[0]
                self.assertEqual(count, 0, "Unauthorized analysis request created a job")

    def test_09_no_worker_503_keeps_case(self):
        from app.db import connect
        with closing(connect()) as connection, connection:
            connection.execute("DELETE FROM analysis_workers")
        url, patient = self.new_case()
        response = self.client.post(url + "/analyze", headers=patient)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.get(url, headers=patient).status_code, 200)
        OBS["no_worker"] = {"analyze_http": 503, "case_remains_http": 200}

    def test_10_deferred_doctor_confirmation(self):
        self.review_flow("deferred")

    def test_11_normal_doctor_confirmation(self):
        self.review_flow("normal_consensus")

    def test_12_model_failure_explicit_retry(self):
        from app.jobs import heartbeat, claim
        from app.worker import run_job
        class BrokenModel:
            def predict(self, *args):
                raise ValueError("Intentional synthetic model failure")
        url, patient = self.new_case()
        heartbeat("isolated-http-test-worker")
        first = self.client.post(url + "/analyze", headers=patient)
        self.assertEqual(first.status_code, 202)
        self.assertTrue(run_job(claim(), BrokenModel(), {}))
        self.assertEqual(self.client.get(url, headers=patient).json()["aiState"], "실패")
        repeated = self.client.post(url + "/analyze", headers=patient)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["jobId"], first.json()["jobId"])
        retried = self.client.post(url + "/analyze?retry=true", headers=patient)
        self.assertEqual(retried.status_code, 202)
        self.assertNotEqual(retried.json()["jobId"], first.json()["jobId"])
        self.assertTrue(run_job(claim(), BrokenModel(), {}))

    def test_13_front_only_optional_fields_behavior(self):
        url, headers = self.new_case(lesion=False, omit=("symptoms", "duration", "description"))
        self.assertEqual(self.client.post(url + "/analyze", headers=headers).status_code, 422)
        self.assertEqual(self.client.get(url, headers=headers).json()["symptoms"], [])
        OBS["optional_intake"] = "Front-only and empty questionnaire accepted (201); analysis without close-up rejected (422)"

    def test_14_patient_own_photo_behavior(self):
        url, patient = self.new_case()
        response = self.client.get(url + "/photos/0", headers=patient)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PNG)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        OBS["patient_own_photo"] = "Own case token can download original photo (200), as agreed for the backend contract"

    def test_15_error_request_id(self):
        response = self.client.get("/api/missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["request_id"], response.headers["x-request-id"])

    def test_16_api_restart_persistence(self):
        url, patient = self.new_case()
        self.client.close()
        SERVER.stop()
        SERVER.start()
        self.__class__.client = httpx.Client(base_url=BASE, timeout=15, trust_env=False)
        self.assertEqual(self.client.get(url, headers=patient).status_code, 200)
        self.assertEqual(self.client.get(url + "/photos/0", headers=DOCTOR).content, PNG)
        OBS["restart"] = "Case, token access and photo persist after API process restart"

    def test_17_valid_jpeg_accepted(self):
        jpeg = image_bytes("JPEG")
        url, patient = self.new_case(photo=jpeg, filename="synthetic.jpg", mime="image/jpeg")
        response = self.client.get(url + "/photos/0", headers=patient)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.content, jpeg)


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.executed_tests = []
        self._records_by_id = {}
        self._started = {}

    def _record(self, test):
        test_id = test.id()
        if test_id not in self._records_by_id:
            record = {"test": test_id, "result": "RUNNING", "subtests": []}
            self._records_by_id[test_id] = record
            self.records.append(record)
        return self._records_by_id[test_id]

    def startTest(self, test):
        super().startTest(test)
        self._started[test.id()] = time.monotonic()
        self.executed_tests.append(test.id().rsplit(".", 1)[-1])
        self._record(test)

    def stopTest(self, test):
        record = self._record(test)
        record["seconds"] = round(time.monotonic() - self._started[test.id()], 3)
        if record["result"] == "RUNNING":
            record.update(result="ERROR", details="Test ended without an outcome")
        super().stopTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test)["result"] = "PASS"

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test).update(result="FAIL", details=self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test).update(result="ERROR", details=self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        parent = getattr(test, "test_case", test)
        record = self._record(parent)
        if parent is not test:
            record["subtests"].append({"test": test.id(), "result": "SKIP", "reason": reason})
        if record["result"] not in ("FAIL", "ERROR"):
            record.update(result="SKIP", reason=reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        item = {"test": subtest.id(), "result": "PASS"}
        if err is not None:
            item.update(result="FAIL" if issubclass(err[0], test.failureException) else "ERROR",
                        details=self._exc_info_to_string(err, test))
            self._record(test)["result"] = item["result"]
        self._record(test)["subtests"].append(item)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test).update(result="EXPECTED_FAILURE", details=self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test)["result"] = "UNEXPECTED_SUCCESS"


def main():
    global ROOT, RUN, PORT, BASE, DOCTOR, OTHER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2],
                        help="Repository containing main.py, app/ and ensemble/")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.port != 0 and not 1024 <= args.port <= 65535:
        parser.error("Use 0 for an automatic port, or a port between 1024 and 65535")
    ROOT = args.source_root.resolve()
    if not all((ROOT / path).exists() for path in ("main.py", "app", "ensemble")):
        parser.error("--source-root must contain main.py, app/ and ensemble/")
    sys.path.insert(0, str(ROOT))
    OBS.clear()
    RUN = args.output.resolve()
    RUN.mkdir(parents=True, exist_ok=False)
    PORT = args.port
    BASE = f"http://127.0.0.1:{PORT}"
    tokens = {"d1": secrets.token_urlsafe(32), "d2": secrets.token_urlsafe(32)}
    settings = {"SKINAI_DB_PATH": str(RUN / "backend.sqlite3"),
                "SKINAI_PHOTO_DIR": str(RUN / "photos"),
                "SKINAI_DEMO_DOCTOR_TOKENS": json.dumps(tokens), "PYTHONUTF8": "1"}
    previous = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    DOCTOR = {"Authorization": "Bearer " + tokens["d1"]}
    OTHER = {"Authorization": "Bearer " + tokens["d2"]}
    report = {"scope": "actual local HTTP; synthetic images and model outputs",
              "status": "FAIL", "python": sys.version, "port": PORT, "source_root": str(ROOT),
              "expected_tests": list(EXPECTED_TESTS), "executed_tests": [], "tests_run": 0,
              "skipped": 0, "checks": [],
              "limitations": ["No real model weights or worker process", "No remote LAN client",
                              "No browser UI test", "No CI/CD settings modified"]}
    exit_code = 1
    try:
        SERVER.start()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(LiveApiTests)
        result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
        missing = sorted(set(EXPECTED_TESTS) - set(result.executed_tests))
        unexpected = sorted(set(result.executed_tests) - set(EXPECTED_TESTS))
        complete = (not missing and not unexpected and result.testsRun == len(EXPECTED_TESTS)
                    and len(result.executed_tests) == len(set(result.executed_tests)))
        passed = (complete and result.wasSuccessful() and not result.skipped
                  and not result.expectedFailures and not result.unexpectedSuccesses
                  and all(row["result"] == "PASS" for row in result.records))
        report.update(status="PASS" if passed else "FAIL", tests_run=result.testsRun,
                      executed_tests=result.executed_tests, missing_tests=missing, unexpected_tests=unexpected,
                      skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
                      unexpected_successes=len(result.unexpectedSuccesses), failures=len(result.failures),
                      errors=len(result.errors), checks=result.records, observations=OBS)
        exit_code = 0 if passed else 1
    except Exception as error:
        report["setup_error"] = f"{type(error).__name__}: {error}"
        print(report["setup_error"], file=sys.stderr)
    finally:
        SERVER.stop()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if sys.path and sys.path[0] == str(ROOT):
            sys.path.pop(0)
        report["ports"] = getattr(SERVER, "ports", [])
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (RUN / "http-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("HTTP_REPORT=" + str(RUN / "http-results.json"))
        print("Isolated API stopped; existing CI/CD services were not modified.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
