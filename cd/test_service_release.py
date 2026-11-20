import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import ExitStack
from zipfile import ZipFile
from unittest.mock import Mock, patch

from deploy_service_release import deploy, prepare_smoke, smoke_environment
from prepare_service_release import compose_for

IMAGES = {name: f"example/{name}@sha256:" + "a" * 64
          for name in ("api", "worker", "patient-ui", "doctor-ui")}
NEW = json.dumps(compose_for(IMAGES, "a" * 40))
old_config = compose_for(IMAGES, "b" * 40)
for service, port, target in (("api", 18275, 8000), ("patient-ui", 18276, 8080), ("doctor-ui", 18277, 8080)):
    old_config["services"][service]["ports"] = [f"127.0.0.1:{port}:{target}"]
OLD = json.dumps(old_config)


def archived_source(*, legacy=False):
    """Simulate git archive; no Git, npm, browser or Docker process is executed."""
    def run(command, **kwargs):
        if command[:2] == ["git", "archive"]:
            root = "frontend/patient-frontend/"
            files = {
                "playwright.release.config.ts": "process.env.SKINAI_E2E_PATIENT_URL",
                "tests/workflow/patient-doctor.workflow.spec.ts": "process.env.SKINAI_E2E_API_URL",
                "tests/workflow/workflow.pages.ts": "process.env.SKINAI_E2E_DOCTOR_URL",
            }
            with ZipFile(command[4], "w") as archive:
                for filename, content in files.items():
                    archive.writestr(root + filename, "http://127.0.0.1:18165" if legacy else content)
        return subprocess.CompletedProcess(command, 0)
    return run


class ComposeTests(unittest.TestCase):
    def test_services_use_release_digests_and_shared_storage(self):
        names = ("api", "worker", "patient-ui", "doctor-ui")
        images = {name: f"example/{name}@sha256:" + "a" * 64 for name in names}
        config = compose_for(images, "a" * 40)
        self.assertEqual(config["x-skinai-source-commit"], "a" * 40)
        self.assertEqual(config["name"], "skinai-service-local")
        services = config["services"]
        self.assertEqual(services["api"]["ports"], ["127.0.0.1:18265:8000"])
        self.assertEqual(services["patient-ui"]["ports"], ["127.0.0.1:18266:8080"])
        self.assertEqual(services["doctor-ui"]["ports"], ["127.0.0.1:18267:8080"])
        self.assertEqual({name: service["image"] for name, service in services.items()}, images)
        self.assertEqual(services["api"]["volumes"],
                         ["db:/data/db", "photos:/data/photos", "analysis:/data/analysis:ro"])
        self.assertEqual(services["worker"]["volumes"],
                         ["db:/data/db", "photos:/data/photos:ro", "analysis:/data/analysis"])
        self.assertEqual(set(config["volumes"]), {"db", "photos", "analysis"})
        for name in ("api", "worker"):
            self.assertEqual(services[name]["environment"]["SKINAI_ANALYSIS_DIR"], "/data/analysis")
        self.assertEqual(services["worker"]["network_mode"], "none")
        self.assertEqual(services["api"]["env_file"], ["runtime.env"])
        self.assertNotIn("env_file", services["patient-ui"])

    def test_success_promotes_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            candidate.write_text(NEW)
            run = Mock()
            smoke = Mock()
            deploy(candidate, Mock(return_value=smoke), run=run)
            self.assertEqual(candidate.with_name("last-good.json").read_text(), NEW)
            smoke.assert_called_once_with("candidate")

    def test_smoke_failure_restores_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            previous = candidate.with_name("last-good.json")
            candidate.write_text(NEW)
            previous.write_text(OLD)
            run = Mock()
            smoke = Mock(side_effect=[subprocess.CalledProcessError(1, "smoke"), None])
            prepare = Mock(return_value=smoke)
            with self.assertRaises(subprocess.CalledProcessError):
                deploy(candidate, prepare, run=run)
            self.assertEqual(previous.read_text(), OLD)
            self.assertEqual(run.call_args.args[0][3:5], [str(previous), "up"])
            self.assertEqual([call.args[0] for call in prepare.call_args_list], ["a" * 40, "b" * 40])
            self.assertEqual([call.args[0] for call in smoke.call_args_list], ["candidate", "rollback"])
            self.assertEqual(prepare.call_args_list[0].args[2], {
                "SKINAI_E2E_API_URL": "http://127.0.0.1:18265",
                "SKINAI_E2E_PATIENT_URL": "http://127.0.0.1:18266",
                "SKINAI_E2E_DOCTOR_URL": "http://127.0.0.1:18267",
            })
            self.assertEqual(prepare.call_args_list[1].args[2], {
                "SKINAI_E2E_API_URL": "http://127.0.0.1:18275",
                "SKINAI_E2E_PATIENT_URL": "http://127.0.0.1:18276",
                "SKINAI_E2E_DOCTOR_URL": "http://127.0.0.1:18277",
            })

    def test_initial_failure_stops_services_without_removing_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            candidate.write_text(NEW)
            run = Mock(side_effect=[None, None, subprocess.CalledProcessError(1, "up"), None])
            with self.assertRaises(subprocess.CalledProcessError):
                deploy(candidate, Mock(), run=run)
            self.assertFalse(candidate.with_name("last-good.json").exists())
            self.assertEqual(run.call_args.args[0][-1], "down")

    def test_pull_failure_leaves_running_release_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            previous = candidate.with_name("last-good.json")
            candidate.write_text("new")
            previous.write_text("old")
            run = Mock(side_effect=[None, None, subprocess.CalledProcessError(1, "pull")])
            with self.assertRaises(subprocess.CalledProcessError):
                deploy(candidate, Mock(), run=run)
            self.assertEqual(previous.read_text(), "old")
            self.assertEqual([call.args[0][4] for call in run.call_args_list],
                             ["config", "config", "pull"])
            self.assertFalse(candidate.with_name("last-good.pending").exists())

    def test_previous_test_setup_failure_does_not_switch_services(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            candidate.write_text(NEW)
            candidate.with_name("last-good.json").write_text(OLD)
            prepare = Mock(side_effect=[Mock(), OSError("missing previous test source")])
            run = Mock()
            with self.assertRaisesRegex(OSError, "missing previous"):
                deploy(candidate, prepare, run=run)
            self.assertEqual([call.args[0][4] for call in run.call_args_list],
                             ["config", "config", "pull"])

    def test_pinned_source_runs_with_target_urls_and_phase_evidence(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            candidate = Path(folder) / "candidate.json"
            candidate.write_text(NEW)
            urls = smoke_environment(candidate)
            evidence = Path(folder) / "evidence"
            with patch("deploy_service_release.subprocess.run", side_effect=archived_source()) as run, \
                    patch("deploy_service_release.shutil.which", return_value="npm.cmd"):
                smoke = prepare_smoke("a" * 40, stack, evidence, urls)
                smoke("candidate")
                archive_call = run.call_args_list[1].args[0]
                self.assertEqual(archive_call[5], "a" * 40)
                self.assertEqual(run.call_args.kwargs["env"]["SKINAI_E2E_OUTPUT"], str(evidence / "candidate"))
                for key, value in urls.items():
                    self.assertEqual(run.call_args.kwargs["env"][key], value)
                self.assertEqual((evidence / "candidate/source-commit.txt").read_text().strip(), "a" * 40)

    def test_fixed_address_release_is_rejected_before_switching_services(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            previous = candidate.with_name("last-good.json")
            candidate.write_text(NEW)
            previous.write_text(OLD)
            docker = Mock()
            with patch("deploy_service_release.subprocess.run", side_effect=archived_source(legacy=True)), \
                    patch("deploy_service_release.shutil.which") as find_npm:
                with self.assertRaisesRegex(ValueError, "does not support separate CD test addresses"):
                    deploy(candidate, lambda commit, stack, urls: prepare_smoke(
                        commit, stack, Path(folder) / "evidence", urls), run=docker)
                find_npm.assert_not_called()
            self.assertEqual([call.args[0][4] for call in docker.call_args_list], ["config", "config", "pull"])
            self.assertEqual(previous.read_text(), OLD)
            self.assertFalse(candidate.with_name("last-good.pending").exists())

    def test_non_loopback_port_is_rejected_before_switching_services(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            config = json.loads(NEW)
            config["services"]["api"]["ports"] = ["0.0.0.0:18265:8000"]
            candidate.write_text(json.dumps(config))
            docker = Mock()
            with self.assertRaisesRegex(ValueError, "loopback port"):
                deploy(candidate, Mock(), run=docker)
            self.assertEqual([call.args[0][4] for call in docker.call_args_list], ["config", "pull"])

    def test_duplicate_ports_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            config = json.loads(NEW)
            config["services"]["patient-ui"]["ports"] = ["127.0.0.1:18265:8080"]
            candidate.write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, "must be distinct"):
                smoke_environment(candidate)
