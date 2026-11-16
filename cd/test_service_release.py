import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from deploy_service_release import deploy
from prepare_service_release import compose_for

NEW = json.dumps({"x-skinai-source-commit": "a" * 40})
OLD = json.dumps({"x-skinai-source-commit": "b" * 40})


class ComposeTests(unittest.TestCase):
    def test_services_use_release_digests_and_shared_storage(self):
        names = ("api", "worker", "patient-ui", "doctor-ui")
        images = {name: f"example/{name}@sha256:" + "a" * 64 for name in names}
        config = compose_for(images, "a" * 40)
        self.assertEqual(config["x-skinai-source-commit"], "a" * 40)
        self.assertEqual(config["name"], "skinai-service")
        services = config["services"]
        self.assertEqual({name: service["image"] for name, service in services.items()}, images)
        self.assertEqual(services["api"]["volumes"], ["db:/data/db", "photos:/data/photos"])
        self.assertEqual(services["worker"]["volumes"], ["db:/data/db", "photos:/data/photos:ro"])
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
