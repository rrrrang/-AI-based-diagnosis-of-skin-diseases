"""Fail-closed behavior of the CI runner, without changing service code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from run_checks import MIN_TESTS, REQUIRED_SOURCE, check_result


class ResultGateTests(unittest.TestCase):
    def test_complete_suite_passes(self):
        self.assertEqual(check_result("backend", 0, "Ran 7 tests in 0.1s\n\nOK\n"), (7, []))

    def test_zero_tests_cannot_pass(self):
        self.assertTrue(check_result("backend", 0, "Ran 0 tests in 0.1s\n\nOK\n")[1])

    def test_skips_cannot_pass(self):
        self.assertTrue(check_result("backend", 0, "Ran 7 tests in 0.1s\n\nOK (skipped=1)\n")[1])

    def test_expected_failure_cannot_pass(self):
        self.assertTrue(check_result("policy", 0, "Ran 1 test in 0.1s\n\nOK (expected failures=1)\n")[1])

    def test_nonzero_exit_cannot_pass(self):
        self.assertTrue(check_result("backend", 1, "Ran 7 tests in 0.1s\n\nOK\n")[1])

    def test_missing_http_report_cannot_pass(self):
        self.assertTrue(check_result("http", 0, "Ran 17 tests in 1s\n\nOK\n")[1])

    def test_missing_http_case_cannot_pass(self):
        expected = [f"test_{i}" for i in range(MIN_TESTS["http"])]
        report = dict(status="PASS", tests_run=17, expected_tests=expected, executed_tests=expected[:-1],
                      failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0)
        self.assertTrue(check_result("http", 0, "Ran 17 tests in 1s\n\nOK\n", report)[1])

    def test_complete_http_report_passes(self):
        expected = [f"test_{i}" for i in range(MIN_TESTS["http"])]
        report = dict(status="PASS", tests_run=17, expected_tests=expected, executed_tests=expected,
                      failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0)
        self.assertFalse(check_result("http", 0, "Ran 17 tests in 1s\n\nOK\n", report)[1])

    def test_real_failure_stops_later_steps_and_keeps_report(self):
        with tempfile.TemporaryDirectory(prefix="backend-ci-gate-") as directory:
            base = Path(directory)
            source, output = base / "source", base / "results"
            for name in REQUIRED_SOURCE:
                file = source / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("", encoding="utf-8")
            (source / "tests/test_backend.py").write_text(
                "import unittest\nclass Failure(unittest.TestCase):\n"
                "    def test_fail(self):\n        self.assertEqual(422, 200)\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("run_checks.py")),
                                     "--source-root", str(source), "--output-root", str(output)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result.returncode, 1, result.stdout)
            reports = list(output.glob("*/summary.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual([step["name"] for step in report["steps"]], ["backend"])
            self.assertTrue(reports[0].with_name("backend.log").is_file())
            self.assertFalse(reports[0].with_name("policy.log").exists())
            self.assertFalse(reports[0].with_name("http.log").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
