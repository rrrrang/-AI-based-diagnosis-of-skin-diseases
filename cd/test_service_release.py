import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from deploy_service_release import deploy
from prepare_service_release import compose_for


class ComposeTests(unittest.TestCase):
    def test_services_use_release_digests_and_shared_storage(self):
        names = ("api", "worker", "patient-ui", "doctor-ui")
        images = {name: f"example/{name}@sha256:" + "a" * 64 for name in names}
        config = compose_for(images)
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
            candidate.write_text("new")
            run = Mock()
            deploy(candidate, ["smoke"], run=run)
            self.assertEqual(candidate.with_name("last-good.json").read_text(), "new")
            self.assertEqual(run.call_args.args[0], ["smoke"])

    def test_smoke_failure_restores_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            previous = candidate.with_name("last-good.json")
            candidate.write_text("new")
            previous.write_text("old")
            run = Mock(side_effect=[None, None, None, None, subprocess.CalledProcessError(1, "smoke"), None])
            with self.assertRaises(subprocess.CalledProcessError):
                deploy(candidate, ["smoke"], run=run)
            self.assertEqual(previous.read_text(), "old")
            self.assertEqual(run.call_args.args[0][3:5], [str(previous), "up"])

    def test_initial_failure_stops_services_without_removing_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "candidate.json"
            candidate.write_text("new")
            run = Mock(side_effect=[None, None, subprocess.CalledProcessError(1, "up"), None])
            with self.assertRaises(subprocess.CalledProcessError):
                deploy(candidate, ["smoke"], run=run)
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
                deploy(candidate, ["smoke"], run=run)
            self.assertEqual(previous.read_text(), "old")
            self.assertEqual([call.args[0][4] for call in run.call_args_list],
                             ["config", "config", "pull"])
            self.assertFalse(candidate.with_name("last-good.pending").exists())
