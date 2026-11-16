"""Safety regression checks; all Docker calls are replaced by an in-memory fake."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PREVIEW_PATH = Path(__file__).resolve().parents[1] / "prepare_preview.py"
SPEC = importlib.util.spec_from_file_location("release_preview_under_test", PREVIEW_PATH)
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


class FakeDocker:
    """Model label-filtered discovery and exact-name Compose volume removal.

    A name collision without Compose labels is invisible to label discovery,
    but `compose down --volumes` can still remove that configured named volume.
    No command escapes this fake, including commands not modeled here.
    """

    def __init__(self, project):
        self.project = project
        self.resources = {kind: {} for kind in ("container", "network", "volume")}
        self.calls = []
        self.down_calls = []
        labels = {"com.docker.compose.project": project,
                  "com.skinai.preview.owner": preview.OWNER}
        for index, service in enumerate(preview.SERVICES):
            name = f"{project}-{service}-1"
            self.resources["container"][name] = {
                "Id": f"container-{index}", "Name": "/" + name,
                "Config": {"Labels": {**labels, "com.docker.compose.service": service}},
            }
        self.resources["network"][project + "_private"] = {
            "Id": "network-1", "Name": project + "_private", "Labels": dict(labels),
        }
        for volume in ("db", "photos"):
            name = project + "_" + volume
            self.resources["volume"][name] = {"Name": name, "Labels": dict(labels)}

    @staticmethod
    def labels(kind, item):
        return (item.get("Config", {}).get("Labels") if kind == "container"
                else item.get("Labels")) or {}

    def identifier(self, kind, item):
        return item.get("Id", item["Name"])

    def select(self, kind, args):
        items = list(self.resources[kind].values())
        filters = [args[index + 1] for index, value in enumerate(args[:-1])
                   if value in ("--filter", "-f")]
        filters += [arg.split("=", 1)[1] for arg in args if arg.startswith("--filter=")]
        for selector in filters:
            if selector.startswith("label="):
                key, _, value = selector[6:].partition("=")
                items = [item for item in items
                         if key in self.labels(kind, item)
                         and (not value or self.labels(kind, item)[key] == value)]
            elif selector.startswith("name="):
                pattern = selector[5:]
                items = [item for item in items if re.search(pattern, item["Name"].lstrip("/"))]
            else:
                raise AssertionError(f"Unexpected fake Docker filter: {selector}")
        return items

    def __call__(self, command, **kwargs):
        command = list(map(str, command))
        if command[0] != "docker-fake":
            raise AssertionError("A test attempted a non-fake executable")
        args = command[1:]
        self.calls.append(args)

        def result(code=0, stdout=""):
            return subprocess.CompletedProcess(command, code, stdout)

        if args and args[0] == "compose":
            if "down" not in args or "--volumes" not in args:
                raise AssertionError(f"Unexpected Compose mutation: {args}")
            self.down_calls.append(args)
            # Compose selects containers by project but can address configured
            # volumes and networks by their names, even without project labels.
            for name, item in list(self.resources["container"].items()):
                if self.labels("container", item).get("com.docker.compose.project") == self.project:
                    del self.resources["container"][name]
            for name in (self.project + "_db", self.project + "_photos"):
                self.resources["volume"].pop(name, None)
            self.resources["network"].pop(self.project + "_private", None)
            return result(stdout="Removed isolated preview resources\n")
        if args and args[0] == "ps":
            return result(stdout="\n".join(self.identifier("container", item)
                                           for item in self.select("container", args)))
        if len(args) >= 2 and args[0] in self.resources and args[1] == "ls":
            kind = args[0]
            if "--format" in args:
                if args[args.index("--format") + 1] != "{{.Name}}":
                    raise AssertionError("Unexpected fake Docker name format")
                return result(stdout="\n".join(item["Name"] for item in self.select(kind, args)))
            return result(stdout="\n".join(self.identifier(kind, item)
                                           for item in self.select(kind, args)))
        if len(args) >= 3 and args[0] in self.resources and args[1] == "inspect":
            kind, names = args[0], args[2:]
            found = []
            for name in names:
                item = next((item for item in self.resources[kind].values()
                             if name in (item["Name"], item["Name"].lstrip("/"),
                                         self.identifier(kind, item))), None)
                if item is None:
                    return result(1, f"Error response from daemon: No such {kind}: {name}\n")
                found.append(item)
            return result(stdout=json.dumps(found))
        raise AssertionError(f"Unmodeled Docker command; no real command ran: {args}")


class CleanupOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skinai-cleanup-test-")
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name).resolve()
        (self.output / "results").mkdir()
        self.project = "skinai-release-preview-1234abcd"
        self.images = {name: "sha256:" + str(index + 1) * 64
                       for index, name in enumerate(preview.SERVICES)}
        self.compose_path = self.output / "compose.preview.json"
        preview.write_json(self.compose_path, preview.compose_for(self.images, self.project))
        preview.write_json(self.output / "preview-state.json", {
            "owner": preview.OWNER, "output": str(self.output), "project": self.project,
            "images": self.images, "compose_sha256": preview.digest(self.compose_path),
        })
        self.fake = FakeDocker(self.project)

    def cleanup(self):
        # Patching at the invocation boundary guarantees tests cannot run Docker.
        with patch.object(preview, "run_process", self.fake):
            return preview.cleanup(self.output, "docker-fake")

    def assert_refuses_before_down(self):
        refused = False
        try:
            self.cleanup()
        except RuntimeError:
            refused = True
        self.assertEqual(self.fake.down_calls, [],
                         "Cleanup reached Compose down before proving resource ownership")
        self.assertTrue(refused, "Cleanup must refuse unowned resources")

    def test_owned_resources_cleaned_and_unrelated_volume_preserved(self):
        self.fake.resources["volume"]["another-project-data"] = {
            "Name": "another-project-data", "Labels": {},
        }
        report = self.cleanup()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(self.fake.down_calls), 1)
        self.assertIn("another-project-data", self.fake.resources["volume"])

    def test_empty_project_cleanup_is_idempotent(self):
        for resources in self.fake.resources.values():
            resources.clear()
        self.assertEqual(self.cleanup()["status"], "passed")

    def test_unlabelled_database_volume_name_collision_is_refused(self):
        self.fake.resources["volume"][self.project + "_db"]["Labels"] = {}
        self.assert_refuses_before_down()

    def test_foreign_photo_volume_without_project_label_is_refused(self):
        self.fake.resources["volume"][self.project + "_photos"]["Labels"] = {
            "com.skinai.preview.owner": "someone-else",
        }
        self.assert_refuses_before_down()

    def test_unlabelled_network_name_collision_is_refused(self):
        self.fake.resources["network"][self.project + "_private"]["Labels"] = {}
        self.assert_refuses_before_down()

    def test_labelled_resource_with_wrong_owner_is_refused(self):
        self.fake.resources["volume"][self.project + "_db"]["Labels"][
            "com.skinai.preview.owner"] = "someone-else"
        self.assert_refuses_before_down()

    def test_changed_compose_is_refused_before_any_docker_command(self):
        self.compose_path.write_text(self.compose_path.read_text(encoding="utf-8") + "\n",
                                     encoding="utf-8")
        self.assert_refuses_before_down()
        self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
