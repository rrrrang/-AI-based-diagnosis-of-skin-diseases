"""Ownership, abort recovery and subprocess lifetime checks; no Docker daemon needed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from run_workflow import cleanup_run, run_process, sanitize_text, write_state, test_addresses


PROJECT = "skinai-ui-workflow-a1b2c3d4"
CONTAINER_ID = "a" * 64
NETWORK_ID = "b" * 64
TOKEN = "unit-test-ephemeral-token"


class TestAddressTests(unittest.TestCase):
    def test_isolated_ports_keep_all_addresses_on_loopback(self):
        self.assertEqual(test_addresses(18365, 18366, 18367), {
            "SKINAI_E2E_API_URL": "http://127.0.0.1:18365",
            "SKINAI_E2E_PATIENT_URL": "http://127.0.0.1:18366",
            "SKINAI_E2E_DOCTOR_URL": "http://127.0.0.1:18367",
        })

    def test_conflicting_or_invalid_ports_are_rejected(self):
        for ports in ((18365, 18365, 18367), (0, 18366, 18367),
                      (65536, 18366, 18367), (True, 18366, 18367)):
            with self.subTest(ports=ports), self.assertRaises(ValueError):
                test_addresses(*ports)


class FakeDocker:
    def __init__(self, output):
        self.calls = []
        self.fail_down = False
        self.keep_resources = False
        self.containers = [{"Id": CONTAINER_ID, "Name": f"/{PROJECT}-api-1", "Config": {"Labels": {
            "com.docker.compose.project": PROJECT,
            "com.docker.compose.service": "api",
            "com.docker.compose.oneoff": "False",
            "com.docker.compose.project.config_files": str(output / "compose.json"),
        }}}]
        self.networks = [{"Id": NETWORK_ID, "Name": f"{PROJECT}_default", "Labels": {
            "com.docker.compose.project": PROJECT, "com.docker.compose.network": "default",
        }}]

    def __call__(self, command, **kwargs):
        command = list(map(str, command))
        self.calls.append(command)
        if command[1] == "ps":
            if command[-2:] != ["--filter", f"label=com.docker.compose.project={PROJECT}"]:
                raise AssertionError("Container discovery must use the exact project label")
            return "\n".join(item["Id"] for item in self.containers)
        if command[1:3] == ["network", "ls"]:
            if command[-2:] != ["--filter", f"label=com.docker.compose.project={PROJECT}"]:
                raise AssertionError("Network discovery must use the exact project label")
            return "\n".join(item["Id"] for item in self.networks)
        if command[1:3] == ["container", "inspect"]:
            return json.dumps(self.containers)
        if command[1:3] == ["network", "inspect"]:
            return json.dumps(self.networks)
        if command[1] == "compose" and "down" in command:
            if self.fail_down:
                raise RuntimeError("Synthetic Docker failure")
            if not self.keep_resources:
                self.containers.clear()
                self.networks.clear()
            return "Removed owned resources"
        raise AssertionError(f"Unexpected command: {command}")


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workflow-cleanup-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name).resolve()
        (self.output / "results").mkdir()
        (self.output / "compose.json").write_text(json.dumps({
            "name": PROJECT, "services": {
                "api": {"env_file": [{"path": ".env.test", "required": False}]}, "worker": {},
            },
        }), encoding="utf-8")
        (self.output / ".env.test").write_text(
            "SKINAI_DEMO_DOCTOR_TOKENS=" + json.dumps({"d1": TOKEN}) + "\n", encoding="utf-8")
        write_state(self.output, PROJECT)
        self.docker = FakeDocker(self.output)

    def assert_no_down(self):
        self.assertFalse(any("down" in command for command in self.docker.calls))

    def change_state(self, **changes):
        path = self.output / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state.update(changes)
        path.write_text(json.dumps(state), encoding="utf-8")

    def test_cleanup_is_exactly_scoped_and_repeatable_without_private_env(self):
        report = self.output / "results" / "workflow.log"
        report.write_text("Assertion included " + TOKEN, encoding="utf-8")
        unrelated = self.output / "unrelated.txt"
        unrelated.write_text("leave alone", encoding="utf-8")
        for _ in range(2):
            self.assertTrue(cleanup_run(self.output, "docker.exe", self.docker)["test_containers_cleaned"])
        self.assertFalse((self.output / ".env.test").exists())
        self.assertEqual(report.read_text(encoding="utf-8"), "Assertion included [REDACTED]")
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "leave alone")
        for command in self.docker.calls:
            if "down" in command:
                self.assertEqual(command, ["docker.exe", "compose", "--project-name", PROJECT,
                    "--project-directory", str(self.output), "-f", str(self.output / "compose.json"),
                    "down", "--timeout", "20"])

    def test_absent_run_never_creates_a_directory_or_calls_docker(self):
        missing = self.output / "not-created"
        self.assertTrue(cleanup_run(missing, "docker.exe", self.docker)["test_containers_cleaned"])
        self.assertFalse(missing.exists())
        self.assertEqual(self.docker.calls, [])

    def test_missing_ownership_state_refuses_any_cleanup(self):
        (self.output / "state.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "without state.json"):
            cleanup_run(self.output, "docker.exe", self.docker)
        self.assertEqual(self.docker.calls, [])
        self.assertTrue((self.output / ".env.test").exists())

    def test_wrong_output_or_project_prefix_refuses_any_cleanup(self):
        for changes in [{"output": str(self.output.parent)}, {"compose_project": "production"}]:
            with self.subTest(changes=changes):
                write_state(self.output, PROJECT)
                self.change_state(**changes)
                with self.assertRaisesRegex(RuntimeError, "ownership"):
                    cleanup_run(self.output, "docker.exe", self.docker)
                self.assertEqual(self.docker.calls, [])

    def test_changed_compose_file_is_rejected(self):
        with (self.output / "compose.json").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(RuntimeError, "compose file differs"):
            cleanup_run(self.output, "docker.exe", self.docker)
        self.assertEqual(self.docker.calls, [])

    def test_unexpected_container_name_service_project_or_source_is_rejected(self):
        changes = [("Name", f"/{PROJECT}-api-2"), ("com.docker.compose.project", PROJECT + "-other"),
                   ("com.docker.compose.service", "production"), ("com.docker.compose.oneoff", "True"),
                   ("com.docker.compose.project.config_files", str(self.output.parent / "compose.json"))]
        for field, value in changes:
            with self.subTest(field=field):
                self.docker = FakeDocker(self.output)
                item = self.docker.containers[0]
                if field == "Name":
                    item[field] = value
                else:
                    item["Config"]["Labels"][field] = value
                with self.assertRaises(RuntimeError):
                    cleanup_run(self.output, "docker.exe", self.docker)
                self.assert_no_down()
                self.assertTrue((self.output / ".env.test").exists())

    def test_unexpected_network_is_rejected(self):
        self.docker.networks[0]["Name"] = "production_default"
        with self.assertRaisesRegex(RuntimeError, "unexpected network"):
            cleanup_run(self.output, "docker.exe", self.docker)
        self.assert_no_down()

    def test_down_failure_preserves_retry_credentials_but_redacts_reports(self):
        report = self.output / "results" / "playwright-result.json"
        report.write_text(json.dumps({"error": TOKEN}), encoding="utf-8")
        self.docker.fail_down = True
        with self.assertRaisesRegex(RuntimeError, "Synthetic Docker failure"):
            cleanup_run(self.output, "docker.exe", self.docker)
        self.assertTrue((self.output / ".env.test").exists())
        self.assertNotIn(TOKEN, report.read_text(encoding="utf-8"))
        self.docker.fail_down = False
        self.assertTrue(cleanup_run(self.output, "docker.exe", self.docker)["test_containers_cleaned"])

    def test_recovery_without_env_still_redacts_patient_credentials(self):
        (self.output / ".env.test").unlink()
        patient_token = "x" * 43
        report = self.output / "results" / "playwright-result.json"
        report.write_text(json.dumps({"error": f"Authorization: Bearer {patient_token}"}), encoding="utf-8")
        cleanup_run(self.output, "docker.exe", self.docker)
        self.assertNotIn(patient_token, report.read_text(encoding="utf-8"))
        self.assertIn("[REDACTED]", json.loads(report.read_text(encoding="utf-8"))["error"])

    def test_remaining_owned_resources_fail_cleanup_and_keep_credentials(self):
        self.docker.keep_resources = True
        with self.assertRaisesRegex(RuntimeError, "remain after cleanup"):
            cleanup_run(self.output, "docker.exe", self.docker)
        self.assertTrue((self.output / ".env.test").exists())

    def test_redirected_report_is_never_overwritten(self):
        target = self.output / "outside-report.log"
        target.write_text(TOKEN, encoding="utf-8")
        link = self.output / "results" / "linked.log"
        link.write_text(TOKEN, encoding="utf-8")
        original_resolve = Path.resolve

        def redirect(path, *args, **kwargs):
            return target if path == link else original_resolve(path, *args, **kwargs)

        # Exercise the same resolution check without requiring Windows symlink privilege.
        with patch.object(Path, "resolve", redirect):
            with self.assertRaisesRegex(RuntimeError, "redirected report"):
                cleanup_run(self.output, "docker.exe", self.docker)
        self.assertEqual(target.read_text(encoding="utf-8"), TOKEN)
        self.assert_no_down()


class ProcessLifetimeTests(unittest.TestCase):
    def test_timeout_keeps_output_and_stops_command(self):
        with tempfile.TemporaryDirectory(prefix="workflow-timeout-unit-") as directory:
            with self.assertRaises(subprocess.TimeoutExpired) as failure:
                run_process([sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
                            cwd=directory, timeout=0.5)
            self.assertIn("started", failure.exception.output)

    @unittest.skipUnless(os.name == "nt", "Windows agent process ownership")
    def test_completed_command_cannot_leave_a_background_child(self):
        with tempfile.TemporaryDirectory(prefix="workflow-child-unit-") as directory:
            marker = Path(directory) / "should-not-exist.txt"
            child_code = f"import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).write_text('orphan')"
            parent_code = ("import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(child_code)
                           + "],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); print('done')")
            result = run_process([sys.executable, "-c", parent_code], cwd=directory, timeout=5)
            self.assertEqual(result.returncode, 0)
            time.sleep(1.3)
            self.assertFalse(marker.exists(), "Owned background process outlived its command")

    @unittest.skipUnless(os.name == "nt", "Windows agent process ownership")
    def test_abrupt_runner_exit_stops_its_owned_command(self):
        with tempfile.TemporaryDirectory(prefix="workflow-abort-unit-") as directory:
            ready = Path(directory) / "ready.txt"
            orphan = Path(directory) / "should-not-exist.txt"
            command_code = (f"import time; from pathlib import Path; Path({str(ready)!r}).write_text('ready'); "
                            f"time.sleep(1); Path({str(orphan)!r}).write_text('orphan'); time.sleep(30)")
            helper_code = ("import sys; from run_workflow import run_process; "
                           f"run_process([sys.executable,'-c',{command_code!r}],cwd={directory!r},timeout=40)")
            helper = subprocess.Popen([sys.executable, "-B", "-c", helper_code], cwd=Path(__file__).parent,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline and helper.poll() is None:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), "Owned command did not start")
                helper.kill()
                helper.wait(timeout=5)
                time.sleep(1.3)
                self.assertFalse(orphan.exists(), "Owned command outlived the aborted runner")
            finally:
                if helper.poll() is None:
                    helper.kill()
                helper.wait(timeout=5)


class RedactionTests(unittest.TestCase):
    def test_request_headers_json_fields_and_bare_assertion_values_are_redacted(self):
        patient_token = "abc_-DEF012" * 3 + "xyz_-01234"
        self.assertEqual(len(patient_token), 43)
        messages = [f"Authorization: Bearer {patient_token}",
                    json.dumps({"error": f'headers: {{"Authorization": "Bearer {patient_token}"}}'}),
                    json.dumps({"accessToken": patient_token}),
                    json.dumps({"error": f'body: {{"accessToken": "{patient_token}"}}'}),
                    f"Received: {patient_token}", 'access_token="short-token"']
        for message in messages:
            with self.subTest(message=message):
                result = sanitize_text(message)
                self.assertNotIn(patient_token, result)
                self.assertNotIn("short-token", result)
                self.assertIn("[REDACTED]", result)
        self.assertEqual(sanitize_text("a" * 64), "a" * 64, "Keep evidence SHA-256 hashes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
