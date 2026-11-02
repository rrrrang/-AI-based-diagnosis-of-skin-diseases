import json
import unittest
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:18100"


class ConnectionTest(unittest.TestCase):
    def test_central_health(self):
        with urlopen(f"{BASE_URL}/health", timeout=5) as response:
            self.assertEqual(response.status, 200)
            data = json.load(response)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "central")

    def test_central_to_ai(self):
        request = Request(f"{BASE_URL}/analyze", method="POST")

        with urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            data = json.load(response)

        self.assertEqual(data["service"], "central")
        ai = data["ai_response"]
        self.assertEqual(ai["status"], "ok")
        self.assertEqual(ai["service"], "ai-mock")
        self.assertEqual(ai["message"], "연결 실습용 응답입니다.")
        self.assertIs(ai["model_loaded"], False)
        self.assertIs(ai["practice_only"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)