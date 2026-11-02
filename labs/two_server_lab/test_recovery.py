import json
import os
import subprocess
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.getenv(
    "TEST_BASE_URL",
    "http://127.0.0.1:18120",
)

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


def call_api(path, method="GET"):
    request = Request(BASE_URL + path, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


class RecoveryTest(unittest.TestCase):
    def check_ai_connection(self):
        code, data = call_api("/analyze", "POST")
        self.assertEqual(code, 200)
        self.assertEqual(data["service"], "central")
        self.assertEqual(data["ai_response"]["status"], "ok")
        self.assertEqual(data["ai_response"]["service"], "ai-mock")

    def test_failure_and_recovery(self):
        print("\n[1/3] 정상 연결 검사", flush=True)
        self.check_ai_connection()

        try:
            print("[2/3] 테스트 AI 중지 후 오류 처리 검사", flush=True)
            run_compose("stop", "-t", "5", "ai-mock")

            code, data = call_api("/health")
            self.assertEqual(code, 200)
            self.assertEqual(data["status"], "ok")

            code, data = call_api("/analyze", "POST")
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