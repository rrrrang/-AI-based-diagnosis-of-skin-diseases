"""Publication must never accept partial images or unrelated/failed CI builds."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "skinai_published_release", Path(__file__).with_name("release.py")
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def valid_release():
    commit = "a" * 40
    release_id = "sha-" + commit[:12] + "-workflow-3"
    return {
        "schema": release.SCHEMA,
        "release_id": release_id,
        "platform": "linux/amd64",
        "source": {
            "repository": release.SOURCE_REPOSITORY,
            "branch": release.SOURCE_BRANCH,
            "commit": commit,
            "working_tree_dirty": False,
        },
        "ci": {
            role: {"job": job, "build": 3, "result": "SUCCESS", "commit": commit}
            for role, job in release.CI_JOBS.items()
        },
        "services": {
            name: {
                "repository": repository,
                "tag": release_id,
                "digest": "sha256:" + "b" * 64,
                "image": repository + "@sha256:" + "b" * 64,
                "platform_digest": "sha256:" + "c" * 64,
                "config_digest": "sha256:" + "d" * 64,
                "local_image_id": "sha256:" + "e" * 64,
                "visibility": "public",
            }
            for name, repository in release.REPOSITORIES.items()
        },
        "verification": dict(release.VERIFICATION),
        "evidence_sha256": {
            "candidate": "f" * 64, "preview_summary": "1" * 64,
            "model_manifest": "2" * 64,
        },
        "deployment": dict(release.DEPLOYMENT),
    }


class PublicationContractTests(unittest.TestCase):
    def assert_invalid(self, data):
        with self.assertRaises(ValueError):
            release.validate_release(data)

    def test_complete_same_revision_handoff_does_not_claim_cd_ready(self):
        data = valid_release()
        before = copy.deepcopy(data)
        self.assertIsNone(release.validate_release(data))
        self.assertEqual(data, before)
        self.assertEqual(data["deployment"]["status"], "not-configured")
        # Docker can have a single manifest rather than an OCI index.
        for item in data["services"].values():
            item["platform_digest"] = item["digest"]
            item["local_image_id"] = item["digest"]
        self.assertIsNone(release.validate_release(data))

    def test_missing_or_extra_service_is_not_a_complete_release(self):
        for name in release.REPOSITORIES:
            with self.subTest(name=name):
                data = valid_release()
                del data["services"][name]
                self.assert_invalid(data)
        data = valid_release()
        data["services"]["ai-mock"] = copy.deepcopy(data["services"]["worker"])
        self.assert_invalid(data)

    def test_all_three_ci_jobs_must_succeed_for_exact_source_commit(self):
        for role in release.CI_JOBS:
            for field, value in (
                ("result", "FAILURE"), ("result", "UNSTABLE"),
                ("result", "ABORTED"), ("result", None),
                ("commit", "9" * 40), ("job", "SkinAI-Two-Server-CI"),
                ("build", 0), ("build", True), ("build", "3"),
            ):
                with self.subTest(role=role, field=field, value=value):
                    data = valid_release()
                    data["ci"][role][field] = value
                    self.assert_invalid(data)
            data = valid_release()
            del data["ci"][role]
            self.assert_invalid(data)

    def test_tag_is_bound_to_commit_and_exact_workflow_build(self):
        for value in ("latest", "sha-aaaaaaaaaaaa-workflow-2",
                      "sha-bbbbbbbbbbbb-workflow-3"):
            data = valid_release()
            data["release_id"] = value
            for item in data["services"].values():
                item["tag"] = value
            self.assert_invalid(data)
        data = valid_release()
        data["services"]["doctor-ui"]["tag"] = "another-tag"
        self.assert_invalid(data)

    def test_repository_allowlist_and_public_scope_cannot_drift(self):
        for service in release.REPOSITORIES:
            for field, value in (
                ("repository", "docker.io/another-user/skinai-api"),
                ("repository", "docker.io/rlarns982/skinai-central-lab"),
                ("visibility", "private"),
            ):
                with self.subTest(service=service, field=field):
                    data = valid_release()
                    data["services"][service][field] = value
                    self.assert_invalid(data)

    def test_image_reference_must_match_its_repository_and_registry_digest(self):
        for field in ("digest", "platform_digest", "config_digest", "local_image_id"):
            for value in ("", "latest", "sha256:short", "sha256:" + "G" * 64):
                with self.subTest(field=field, value=value):
                    data = valid_release()
                    data["services"]["api"][field] = value
                    self.assert_invalid(data)
        for value in ("docker.io/rlarns982/skinai-api:latest",
                      "docker.io/rlarns982/skinai-api@sha256:" + "9" * 64,
                      "docker.io/rlarns982/skinai-worker@sha256:" + "b" * 64):
            data = valid_release()
            data["services"]["api"]["image"] = value
            self.assert_invalid(data)

    def test_uncommitted_or_wrong_repository_source_is_rejected(self):
        for field, value in (
            ("working_tree_dirty", True), ("working_tree_dirty", 0),
            ("commit", "short"), ("repository", "https://example.invalid/repo"),
            ("branch", "main"),
        ):
            with self.subTest(field=field, value=value):
                data = valid_release()
                data["source"][field] = value
                self.assert_invalid(data)

    def test_unverified_publication_or_failed_cleanup_cannot_be_released(self):
        for field, value in (
            ("status", "failed"), ("packaged_workflow", "pending"),
            ("cleanup", "failed"), ("source_inputs_unchanged", False),
            ("source_inputs_unchanged", 1), ("registry", "not-checked"),
        ):
            with self.subTest(field=field, value=value):
                data = valid_release()
                data["verification"][field] = value
                self.assert_invalid(data)
        data = valid_release()
        del data["evidence_sha256"]["candidate"]
        self.assert_invalid(data)
        data = valid_release()
        data["evidence_sha256"]["preview_summary"] = "unknown"
        self.assert_invalid(data)

    def test_publication_cannot_silently_claim_production_auth_or_clinical_validation(self):
        for field, value in (("status", "ready"), ("auth", "production"),
                             ("medical_accuracy_evaluated", True)):
            data = valid_release()
            data["deployment"][field] = value
            self.assert_invalid(data)
        data = valid_release()
        data["deployable"] = True
        self.assert_invalid(data)

    def test_local_candidate_and_old_mock_contract_are_not_this_contract(self):
        for field, value in (("schema", "skinai.local-candidate/v2"),
                             ("platform", "linux/arm64")):
            data = valid_release()
            data[field] = value
            self.assert_invalid(data)
        data = valid_release()
        data["practice_only"] = True
        data["model_loaded"] = False
        self.assert_invalid(data)

    def test_duplicate_json_authority_fields_are_rejected(self):
        body = json.dumps(valid_release())
        body = body[:-1] + ', "schema": "skinai.release/v2"}'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "release.json"
            path.write_text(body, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON field"):
                release.load_release(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)