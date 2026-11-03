import json
import os
import subprocess
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:18120")
CONFIG = Path(
    os.getenv(
        "TEST_COMPOSE_FILE",
        str(Path(__file__).resolve().with_name("compose.ci.yaml")),
    )
)

# CI가 지정한 이번 검사 환경만 조작합니다.
PROJECT_NAME = os.getenv("TEST_PROJECT_NAME", "").strip()
if not PROJECT_NAME:
    raise RuntimeError(
        "TEST_PROJECT_NAME이 필요합니다. Jenkins CI 작업에서 실행하세요."
    )

DOCKER_EXE = os.getenv("DOCKER_EXE", "docker")
SAMPLE_DATA = {
    "sample_id": "ci-case-001",
    "sample_text": "한글 연결 검사용 가짜 데이터입니다.",
}


def run_compose(*args):
    subprocess.run(
        [
            DOCKER_EXE,
            "compose",
            "-p",
            PROJECT_NAME,
            "-f",
            str(CONFIG),
            *args,
        ],
        check=True,
        timeout=60,
    )


def call_api(path, method="GET", payload=None):
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(BASE_URL + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


class RecoveryTest(unittest.TestCase):
    def check_ai_connection(self, payload=None):
        if payload is None:
            payload = SAMPLE_DATA
        code, data = call_api("/analyze", "POST", payload)
        self.assertEqual(code, 200)
        self.assertEqual(data["service"], "central")
        ai = data["ai_response"]
        self.assertEqual(ai["status"], "ok")
        self.assertEqual(ai["service"], "ai-mock")
        self.assertEqual(ai["received"], payload)
        self.assertIs(ai["model_loaded"], False)
        self.assertIs(ai["practice_only"], True)

    def test_data_round_trip(self):
        # 서로 다른 값 2개로 검사해 고정 응답만 돌려주는 오류도 찾습니다.
        for payload in [
            SAMPLE_DATA,
            {"sample_id": "ci-case-002", "sample_text": '두 번째 문장: "JSON" & 한글!'},
        ]:
            with self.subTest(sample_id=payload["sample_id"]):
                self.check_ai_connection(payload)

    def test_missing_body_rejected(self):
        code, data = call_api("/analyze", "POST")
        self.assertEqual(code, 422)
        self.assertIn("detail", data)

    def test_missing_field_rejected(self):
        code, data = call_api("/analyze", "POST", {"sample_id": "ci-missing"})
        self.assertEqual(code, 422)
        self.assertTrue(any("sample_text" in item["loc"] for item in data["detail"]))

    def test_invalid_field_value_rejected(self):
        cases = [
            ("sample_id", 123),
            ("sample_id", ""),
            ("sample_id", "x" * 65),
            ("sample_text", ""),
            ("sample_text", "x" * 201),
        ]
        for field, invalid_value in cases:
            with self.subTest(field=field, invalid_value=invalid_value):
                code, data = call_api(
                    "/analyze", "POST", {**SAMPLE_DATA, field: invalid_value}
                )
                self.assertEqual(code, 422)
                self.assertTrue(
                    any(field in item["loc"] for item in data["detail"])
                )

    def test_extra_field_rejected(self):
        code, data = call_api(
            "/analyze", "POST", {**SAMPLE_DATA, "unexpected": "extra"}
        )
        self.assertEqual(code, 422)
        self.assertTrue(any("unexpected" in item["loc"] for item in data["detail"]))

    def test_wrong_method_rejected(self):
        code, _ = call_api("/analyze", "GET")
        self.assertEqual(code, 405)

    def test_failure_and_recovery(self):
        print("\n[1/3] 정상 데이터 전달 검사", flush=True)
        self.check_ai_connection()
        try:
            print("[2/3] 테스트 AI 중지 후 오류 처리 검사", flush=True)
            run_compose("stop", "-t", "5", "ai-mock")
            code, data = call_api("/health")
            self.assertEqual(code, 200)
            self.assertEqual(data["status"], "ok")
            code, data = call_api("/analyze", "POST", SAMPLE_DATA)
            self.assertEqual(code, 503)
            self.assertEqual(
                data["detail"],
                "임시 AI 서버와의 통신에 실패했습니다.",
            )
        finally:
            print("[3/3] 테스트 AI 재시작 및 복구 검사", flush=True)
            run_compose("start", "--wait", "--wait-timeout", "30", "ai-mock")
            self.check_ai_connection()


if __name__ == "__main__":
    unittest.main(verbosity=2)
