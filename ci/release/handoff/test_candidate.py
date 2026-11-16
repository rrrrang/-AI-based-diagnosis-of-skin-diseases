"""Negative contract tests that stop local preview evidence becoming a release."""
import copy
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "skinai_local_candidate", Path(__file__).with_name("candidate.py")
)
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


def valid_candidate():
    return {
        "schema": "skinai.local-candidate/v2",
        "candidate_id": "local-test-only",
        "draft_only": True,
        "deployable": False,
        "target": "local-preview",
        "platform": "linux/amd64",
        "source": {"commit": "b" * 40, "working_tree_dirty": True},
        "packaging": {
            "status": "uncommitted-draft",
            "files_sha256": {"ci/release/Dockerfile": "a" * 64},
        },
        "services": {
            name: {"local_image_id": "sha256:" + "c" * 64,
                   "local_tag": "skinai-local-" + name + ":test"}
            for name in ("api", "worker", "patient-ui", "doctor-ui")
        },
        "model_bundle_manifest_sha256": "d" * 64,
        "ci": {
            "purpose": "historical-source-evidence",
            "source_commit": "b" * 40,
            "builds": {"ui": 8, "backend": 26, "workflow": 2},
        },
        "verification": {"status": "pending"},
        "limitations": ["Local preview only"],
    }


class CandidateContractTests(unittest.TestCase):
    def assert_invalid(self, data):
        with self.assertRaises(ValueError):
            candidate.validate_candidate(data)

    def test_local_verification_never_changes_release_authority(self):
        for status in ("pending", "passed", "failed"):
            data = valid_candidate()
            data["verification"]["status"] = status
            before = copy.deepcopy(data)
            self.assertIsNone(candidate.validate_candidate(data))
            self.assertEqual(data, before)
            self.assertFalse(data["deployable"])

    def test_remote_digest_cannot_replace_local_image_identity(self):
        for field in ("digest", "registry_digest", "repository", "release_id"):
            with self.subTest(field=field):
                data = valid_candidate()
                data["services"]["api"][field] = "sha256:" + "e" * 64
                self.assert_invalid(data)
        data = valid_candidate()
        data["services"]["api"]["local_image_id"] = (
            "example.invalid/skinai/api@sha256:" + "e" * 64
        )
        self.assert_invalid(data)

    def test_registry_reference_cannot_hide_inside_service_metadata(self):
        data = valid_candidate()
        data["services"]["worker"]["local_tag"] = (
            "example.invalid/skinai/worker@sha256:" + "e" * 64
        )
        self.assert_invalid(data)
        data = valid_candidate()
        data["services"]["worker"]["extra"] = {
            "nested": [{"registry_digest": "sha256:" + "e" * 64}]
        }
        self.assert_invalid(data)

    def test_draft_cannot_be_promoted_by_editing_a_flag_or_target(self):
        for key, value in (
            ("draft_only", False), ("deployable", True),
            ("target", "production"), ("target", "staging"),
            ("schema", "skinai.release/v2"), ("draft_only", 1),
            ("deployable", 0),
        ):
            with self.subTest(key=key, value=value):
                data = valid_candidate()
                data[key] = value
                self.assert_invalid(data)
        data = valid_candidate()
        data["release_id"] = "published-release"
        self.assert_invalid(data)

    def test_no_partial_four_service_bundle(self):
        for service in ("api", "worker", "patient-ui", "doctor-ui"):
            with self.subTest(service=service):
                data = valid_candidate()
                del data["services"][service]
                self.assert_invalid(data)
                data = valid_candidate()
                del data["services"][service]["local_image_id"]
                self.assert_invalid(data)

    def test_latest_or_empty_image_is_not_immutable_local_evidence(self):
        for image in ("", "skinai-api:latest", "sha256:1234", None):
            with self.subTest(image=image):
                data = valid_candidate()
                data["services"]["api"]["local_image_id"] = image
                self.assert_invalid(data)

    def test_ci_from_another_commit_cannot_describe_this_source(self):
        data = valid_candidate()
        data["ci"]["source_commit"] = "f" * 40
        self.assert_invalid(data)
        for number in (0, -1, "8", True):
            with self.subTest(number=number):
                data = valid_candidate()
                data["ci"]["builds"]["ui"] = number
                self.assert_invalid(data)

    def test_packaging_files_cannot_be_unhashed_or_escape_the_source_tree(self):
        for mapping in ({}, {"Dockerfile": ""},
                        {"../Dockerfile": "a" * 64},
                        {"D:/outside/Dockerfile": "a" * 64}):
            with self.subTest(mapping=mapping):
                data = valid_candidate()
                data["packaging"]["files_sha256"] = mapping
                self.assert_invalid(data)

    def test_optional_evidence_can_be_absent_but_model_lock_cannot(self):
        data = valid_candidate()
        for key in ("ci", "verification", "candidate_id", "limitations"):
            del data[key]
        self.assertIsNone(candidate.validate_candidate(data))
        del data["model_bundle_manifest_sha256"]
        self.assert_invalid(data)

    def test_cli_json_reader_rejects_duplicate_authority_fields(self):
        with self.assertRaises(ValueError):
            candidate._unique_object([("deployable", True), ("deployable", False)])


if __name__ == "__main__":
    unittest.main()
