"""Publisher gates and partial failures; subprocess/registry/Jenkins are all fake."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "skinai_publish_under_test", Path(__file__).resolve().parents[1] / "publish.py"
)
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)

COMMIT = "a" * 40
JOBS = {"ui": "SkinAI-UI-CI", "backend": "SkinAI-Backend-CI", "workflow": "SkinAI-Workflow-CI"}


def fixture():
    images = {name: "sha256:" + str(index + 1) * 64
              for index, name in enumerate(publisher.REPOSITORIES)}
    candidate = {
        "schema": "skinai.local-candidate/v2", "candidate_id": "local-test-run",
        "draft_only": True, "deployable": False, "target": "local-preview",
        "platform": "linux/amd64",
        "source": {"commit": COMMIT, "working_tree_dirty": False},
        "packaging": {"status": "committed-draft", "files_sha256": {"main.py": "f" * 64}},
        "services": {name: {"local_image_id": image} for name, image in images.items()},
        "model_bundle_manifest_sha256": publisher.file_hash(publisher.HERE / "backend/model-lock.json"),
        "verification": {"status": "passed"},
    }
    summary = {
        "status": "passed", "services": 4, "workflow_cases": 2,
        "no_host_source_or_model_mounts": True, "ui_proxy_checks": "passed",
        "cleanup": "passed", "source_inputs_unchanged": True,
        "existing_containers_unchanged": True, "source_commit": COMMIT,
        "packaged_image_ids": dict(images),
    }
    ci = {role: {"job": job, "build": 3, "result": "SUCCESS", "commit": COMMIT}
          for role, job in JOBS.items()}
    return candidate, summary, images, ci


class FakeExternal:
    """No method in this object launches a command or makes a network request."""
    def __init__(self, images):
        self.images = dict(images)
        self.repository_to_service = {repo: service for service, repo in publisher.REPOSITORIES.items()}
        self.commands = []
        self.tags = {}
        self.remote = {}
        self.repositories = {repo: True for repo in publisher.REPOSITORIES.values()}
        self.verified = []
        self.repository_reads = []
        self.fail_verify = None
        self.created_private = False
        self.retagged_wrong_image = False
        self.inspect_revision = COMMIT
        self.inspect_architecture = "amd64"
        self.dirty_initial = False
        self.dirty_final = False
        self.status_reads = 0
        self.after_push = None

    def process(self, command, **kwargs):
        command = list(map(str, command))
        self.commands.append(command)
        if command == ["git", "status", "--porcelain"]:
            self.status_reads += 1
            dirty = self.dirty_initial or (self.dirty_final and self.status_reads > 1)
            result = " M main.py\n" if dirty else ""
        elif command == ["git", "rev-parse", "HEAD"]:
            result = COMMIT + "\n"
        elif command == ["git", "remote", "get-url", "origin"]:
            result = publisher.SOURCE_REPOSITORY + ".git\n"
        elif command[:3] == ["docker-fake", "image", "inspect"] and len(command) == 4:
            image = self.tags.get(command[3], command[3])
            if image not in self.images.values() and image != "sha256:" + "9" * 64:
                raise AssertionError("Attempt to inspect unknown fake image")
            result = json.dumps([{
                "Id": image, "Os": "linux", "Architecture": self.inspect_architecture,
                "Config": {"Labels": {"org.opencontainers.image.revision": self.inspect_revision}},
            }])
        elif command[:2] == ["docker-fake", "tag"] and len(command) == 4:
            self.tags[command[3]] = "sha256:" + "9" * 64 if self.retagged_wrong_image else command[2]
            result = ""
        elif command[:2] == ["docker-fake", "push"] and len(command) == 3:
            target = command[2]
            if target not in self.tags:
                raise AssertionError("Push without assigning a tested fake image")
            repo, tag = target.rsplit(":", 1)
            self.remote[repo] = self.tags[target]
            self.repositories[repo] = not self.created_private
            result = f"{tag}: digest: {self.remote[repo]} size: 856\n"
            if self.after_push is not None:
                self.after_push()
        else:
            raise AssertionError("Unmodeled command; no real command was run: " + repr(command))
        return subprocess.CompletedProcess(command, 0, result)

    def repository_reader(self, repository):
        self.repository_reads.append(repository)
        if not self.repositories.get(repository):
            return None
        return {"is_private": False}

    def digest_reader(self, repository, tag):
        return self.remote.get(repository)

    def verify(self, repository, tag, local_id, commit, expected_digest=None):
        service = self.repository_to_service[repository]
        if not self.repositories.get(repository):
            raise ValueError("Repository is not publicly observable after upload")
        if self.fail_verify == service:
            raise ValueError("Injected remote content verification failure")
        if self.remote.get(repository) != local_id or expected_digest != local_id:
            raise ValueError("Remote tag is different from the tested image")
        if commit != COMMIT or local_id != self.images[service]:
            raise ValueError("Source or local image identity is different")
        self.verified.append(service)
        return {"digest": local_id, "platform_digest": local_id,
                "config_digest": "sha256:" + "b" * 64, "visibility": "public"}

    def mutations(self):
        return [item for item in self.commands
                if item[0] == "docker-fake" and item[1] in ("tag", "push")]

    def pushes(self):
        return [item for item in self.commands if item[:2] == ["docker-fake", "push"]]


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skinai-publish-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "packaged-run"
        (self.run / "results").mkdir(parents=True)
        self.output = self.root / "publication"
        self.candidate, self.summary, self.images, self.ci = fixture()
        self.fake = FakeExternal(self.images)

    def invoke(self, publish=True, allow_create=False):
        publisher.save(self.run / "candidate.json", self.candidate)
        publisher.save(self.run / "results/preview-summary.json", self.summary)
        arguments = ["--run", str(self.run), "--output", str(self.output),
                     "--docker", "docker-fake", "--jenkins-home", str(self.root / "fake-jenkins"),
                     "--ui-build", "3", "--backend-build", "3", "--workflow-build", "3"]
        if publish:
            arguments.append("--publish")
        if allow_create:
            arguments.append("--create-missing-repositories")
        actual_publish_services = publisher.publish_services

        def inject_dependencies(*args, **kwargs):
            return actual_publish_services(*args, **kwargs,
                repository_reader=self.fake.repository_reader,
                digest_reader=self.fake.digest_reader, verifier=self.fake.verify)

        with patch.object(publisher, "run_process", self.fake.process), \
             patch.object(publisher, "assert_inputs_unchanged"), \
             patch.object(publisher, "collect_evidence", return_value=(self.ci, {"test": "fake-only"})), \
             patch.object(publisher, "publish_services", side_effect=inject_dependencies), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return publisher.main(arguments)

    def assert_no_release(self):
        self.assertFalse((self.output / "release.json").exists())
        self.assertFalse((self.output / "release.json.tmp").exists())

    def test_dirty_or_mismatched_candidate_is_rejected(self):
        cases = [
            ("source", "working_tree_dirty", True),
            ("source", "commit", "9" * 40),
            ("packaging", "status", "uncommitted-draft"),
            ("verification", "status", "failed"),
        ]
        for group, field, value in cases:
            with self.subTest(group=group, field=field):
                data = copy.deepcopy(self.candidate)
                data[group][field] = value
                with self.assertRaises(ValueError):
                    publisher.validate_gate(data, self.summary, COMMIT)

    def test_only_exact_tested_image_ids_and_successful_cleanup_are_accepted(self):
        for key, value in (("cleanup", "failed"), ("source_inputs_unchanged", False),
                           ("existing_containers_unchanged", False), ("workflow_cases", 1),
                           ("no_host_source_or_model_mounts", 1)):
            with self.subTest(key=key):
                changed = dict(self.summary, **{key: value})
                with self.assertRaises(ValueError):
                    publisher.validate_gate(self.candidate, changed, COMMIT)
        self.summary["packaged_image_ids"]["api"] = "sha256:" + "9" * 64
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.fake.mutations(), [])
        self.assert_no_release()

    def test_dirty_checkout_stops_before_any_docker_or_registry_mutation(self):
        self.fake.dirty_initial = True
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual(self.fake.repository_reads, [])
        self.assert_no_release()

    def test_local_revision_mismatch_stops_before_upload(self):
        self.fake.inspect_revision = "9" * 40
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.fake.mutations(), [])
        self.assert_no_release()

    def test_local_tag_must_still_resolve_to_the_tested_image_before_push(self):
        self.fake.retagged_wrong_image = True
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.fake.pushes(), [])
        self.assert_no_release()

    def test_four_successful_publications_create_one_valid_handoff(self):
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(len(self.fake.pushes()), 4)
        self.assertEqual(set(self.fake.verified), set(self.images))
        data = publisher.read_json(self.output / "release.json")
        publisher.validate_release(data)
        for service, record in data["services"].items():
            self.assertEqual(record["local_image_id"], self.images[service])
            self.assertEqual(record["digest"], self.images[service])
        self.assertEqual(data["deployment"]["status"], "not-configured")

    def test_partial_upload_failure_leaves_no_success_release(self):
        self.fake.fail_verify = "worker"
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(len(self.fake.pushes()), 2)
        self.assertEqual(self.fake.verified, ["api"])
        report = publisher.read_json(self.output / "publication_report.json")
        self.assertEqual(report["status"], "failed")
        self.assert_no_release()

    def test_existing_mismatched_public_tag_is_never_overwritten(self):
        repository = publisher.REPOSITORIES["api"]
        self.fake.remote[repository] = "sha256:" + "9" * 64
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual(self.fake.remote[repository], "sha256:" + "9" * 64)
        self.assert_no_release()

    def test_matching_existing_tags_are_verified_without_pushes(self):
        self.fake.remote = {repository: self.images[service]
                            for service, repository in publisher.REPOSITORIES.items()}
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual(set(self.fake.verified), set(self.images))
        self.assertTrue((self.output / "release.json").is_file())

    def test_missing_repository_defaults_to_no_mutation_even_when_last_in_bundle(self):
        self.fake.repositories[publisher.REPOSITORIES["doctor-ui"]] = False
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.fake.mutations(), [])
        self.assert_no_release()

    def test_explicit_first_publication_can_create_approved_names(self):
        self.fake.repositories = {repository: False for repository in publisher.REPOSITORIES.values()}
        self.assertEqual(self.invoke(allow_create=True), 0)
        self.assertEqual(len(self.fake.pushes()), 4)
        self.assertEqual(set(self.fake.verified), set(self.images))
        self.assertTrue((self.output / "release.json").is_file())

    def test_explicit_creation_still_requires_public_verification(self):
        self.fake.repositories = {repository: False for repository in publisher.REPOSITORIES.values()}
        self.fake.created_private = True
        self.assertEqual(self.invoke(allow_create=True), 1)
        self.assertEqual(len(self.fake.pushes()), 1)
        self.assert_no_release()

    def test_final_checkout_change_prevents_release_even_after_verified_images(self):
        self.fake.dirty_final = True
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(len(self.fake.pushes()), 4)
        report = publisher.read_json(self.output / "publication_report.json")
        self.assertEqual(report["status"], "failed")
        self.assert_no_release()

    def test_candidate_or_summary_change_during_upload_prevents_release(self):
        for name, relative in (("candidate", "candidate.json"),
                               ("summary", "results/preview-summary.json")):
            with self.subTest(evidence=name):
                self.output = self.root / ("publication-drift-" + name)
                self.fake = FakeExternal(self.images)
                evidence = self.run / relative

                def change_evidence(path=evidence):
                    # Keep valid JSON and identical parsed fields; the recorded
                    # proof must still refer to the exact bytes verified earlier.
                    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

                self.fake.after_push = change_evidence
                self.assertEqual(self.invoke(), 1)
                self.assertEqual(len(self.fake.pushes()), 4)
                report = publisher.read_json(self.output / "publication_report.json")
                self.assertEqual(report["status"], "failed")
                self.assertIn("evidence changed during publication", report["error"])
                self.assert_no_release()

    def test_evidence_change_while_reading_is_rejected_before_upload(self):
        original_read = publisher.read_json
        candidate_path = self.run / "candidate.json"
        changed = False

        def change_after_read(path):
            nonlocal changed
            value = original_read(path)
            if Path(path) == candidate_path and not changed:
                changed = True
                candidate_path.write_text(candidate_path.read_text(encoding="utf-8") + "\n",
                                          encoding="utf-8")
            return value

        with patch.object(publisher, "read_json", side_effect=change_after_read):
            self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.fake.mutations(), [])
        error = original_read(self.output / "failure.json")
        self.assertIn("evidence changed while being read", error["error"])
        self.assert_no_release()

    def test_preflight_never_tags_pushes_or_claims_a_release(self):
        self.assertEqual(self.invoke(publish=False), 0)
        self.assertEqual(self.fake.mutations(), [])
        self.assertEqual(self.fake.repository_reads, [])
        self.assertTrue((self.output / "preflight.json").is_file())
        self.assert_no_release()


if __name__ == "__main__":
    unittest.main(verbosity=2)