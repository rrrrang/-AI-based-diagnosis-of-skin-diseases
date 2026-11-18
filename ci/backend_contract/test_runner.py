"""Fail-closed behavior of the CI runner, without changing service code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from run_checks import (MIN_TESTS, REQUIRED_SOURCE, REQUIRED_AUTH_TESTS,
                        POLICY_MODULES, REQUIRED_POLICY_TESTS, check_result)


def backend_output():
    lines = [f"{name} (test_auth.AuthTests.{name}) ... ok" for name in REQUIRED_AUTH_TESTS]
    return "\n".join(lines) + f"\nRan {MIN_TESTS['backend']} tests in 0.1s\n\nOK\n"


def policy_output(omitted=None):
    lines = [f"{test_id.rsplit('.', 1)[-1]} ({test_id}) ... ok"
             for test_id in REQUIRED_POLICY_TESTS if test_id != omitted]
    return "\n".join(lines) + f"\nRan {MIN_TESTS['policy']} tests in 0.1s\n\nOK\n"


class ResultGateTests(unittest.TestCase):
    def test_complete_suite_passes(self):
        count = MIN_TESTS["backend"]
        self.assertEqual(check_result("backend", 0, backend_output()), (count, []))

    def test_total_count_cannot_replace_missing_authentication_checks(self):
        count = MIN_TESTS["backend"]
        self.assertTrue(check_result("backend", 0, f"Ran {count} tests in 0.1s\n\nOK\n")[1])

    def test_zero_tests_cannot_pass(self):
        self.assertTrue(check_result("backend", 0, "Ran 0 tests in 0.1s\n\nOK\n")[1])

    def test_skips_cannot_pass(self):
        output = backend_output().replace("\nOK\n", "\nOK (skipped=1)\n")
        self.assertTrue(check_result("backend", 0, output)[1])

    def test_expected_failure_cannot_pass(self):
        output = policy_output().replace("\nOK\n", "\nOK (expected failures=1)\n")
        self.assertTrue(check_result("policy", 0, output)[1])

    def test_nonzero_exit_cannot_pass(self):
        self.assertTrue(check_result("backend", 1, backend_output())[1])

    def test_complete_six_class_policy_report_passes(self):
        self.assertEqual(check_result("policy", 0, policy_output()), (MIN_TESTS["policy"], []))

    def test_policy_count_cannot_replace_each_missing_critical_case(self):
        for test_id in REQUIRED_POLICY_TESTS:
            with self.subTest(test=test_id):
                count, errors = check_result("policy", 0, policy_output(omitted=test_id))
                self.assertEqual(count, MIN_TESTS["policy"])
                self.assertTrue(any(test_id in error for error in errors))

    def test_legacy_single_policy_test_is_insufficient(self):
        output = "test_rules (ensemble.test_policy.VotingTests.test_rules) ... ok\nRan 1 test in 0.1s\n\nOK\n"
        self.assertTrue(check_result("policy", 0, output)[1])

    def test_actual_policy_and_adapter_output_passes_gate(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", *POLICY_MODULES, "-v"],
                                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", timeout=30,
                                env={**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        count, errors = check_result("policy", result.returncode, result.stdout)
        self.assertGreaterEqual(count, 17)
        self.assertFalse(errors, "\n".join(errors))

    def test_missing_http_report_cannot_pass(self):
        self.assertTrue(check_result("http", 0, "Ran 20 tests in 1s\n\nOK\n")[1])

    def test_missing_http_case_cannot_pass(self):
        count = MIN_TESTS["http"]
        expected = [f"test_{i}" for i in range(MIN_TESTS["http"])]
        report = dict(status="PASS", tests_run=count, expected_tests=expected, executed_tests=expected[:-1],
                      failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0)
        self.assertTrue(check_result("http", 0, f"Ran {count} tests in 1s\n\nOK\n", report)[1])

    def test_complete_http_report_passes(self):
        count = MIN_TESTS["http"]
        expected = [f"test_{i}" for i in range(MIN_TESTS["http"])]
        report = dict(status="PASS", tests_run=count, expected_tests=expected, executed_tests=expected,
                      failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0)
        self.assertFalse(check_result("http", 0, f"Ran {count} tests in 1s\n\nOK\n", report)[1])

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
