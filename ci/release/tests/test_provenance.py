"""Provenance checks for the inputs actually copied into packaged services."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "preview_provenance", Path(__file__).resolve().parents[1] / "provenance.py"
)
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)


class InputSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        for name in provenance.REQUIRED_FILES:
            self.write(name, "initial fixture")
        for name in (*provenance.INPUT_TREES, provenance.HELPER_TREE):
            (self.repo / name).mkdir(parents=True, exist_ok=True)
        self.write("app/worker.py", "worker-v1")
        self.write("ensemble/policy.py", "policy-v1")
        self.write("frontend/patient-frontend/src/App.tsx", "patient-v1")
        self.write("frontend/doctor-frontend/src/App.tsx", "doctor-v1")
        self.write("frontend/patient-frontend/public/logo.svg", "<svg/>")
        self.write("ci/release/backend/Dockerfile", "FROM example")
        self.write("ci/release/handoff/candidate.py", "validator-v1")
        self.write("ci/ui_workflow/run_workflow.py", "process-helper-v1")
        self.write("frontend/patient-frontend/tests/workflow/workflow.pages.ts", "pages-v1")
        self.write("frontend/patient-frontend/tests/support/auth.ts", "auth-v1")

    def write(self, relative, value):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def test_hashes_app_ui_assets_recipes_and_verification_dependencies(self):
        snapshot = provenance.snapshot_inputs(self.repo)
        self.assertEqual(snapshot["app/worker.py"],
                         hashlib.sha256(b"worker-v1").hexdigest())
        for name in (
            "ensemble/policy.py", "frontend/doctor-frontend/src/App.tsx",
            "frontend/patient-frontend/package-lock.json",
            "frontend/patient-frontend/public/logo.svg",
            "ci/release/backend/Dockerfile", "ci/release/handoff/candidate.py",
            "ci/ui_workflow/run_workflow.py",
            "frontend/patient-frontend/tests/workflow/workflow.pages.ts",
            "frontend/patient-frontend/tests/support/auth.ts",
        ):
            self.assertIn(name, snapshot)
        self.assertIsNone(provenance.assert_inputs_unchanged(self.repo, snapshot))

    def test_changed_app_lock_recipe_or_test_invalidates_frozen_evidence(self):
        for name in (
            "app/worker.py", "frontend/patient-frontend/package-lock.json",
            "ci/release/backend/Dockerfile", "ci/ui_workflow/run_workflow.py",
            "frontend/patient-frontend/tests/workflow/workflow.pages.ts",
            "frontend/patient-frontend/tests/support/auth.ts",
        ):
            with self.subTest(name=name):
                frozen = provenance.snapshot_inputs(self.repo)
                self.write(name, "changed after build started")
                with self.assertRaisesRegex(ValueError, "changed after freezing"):
                    provenance.assert_inputs_unchanged(self.repo, frozen)

    def test_new_source_file_is_detected_even_if_old_files_unchanged(self):
        frozen = provenance.snapshot_inputs(self.repo)
        self.write("app/new_endpoint.py", "new code")
        with self.assertRaisesRegex(ValueError, "added: app/new_endpoint.py"):
            provenance.assert_inputs_unchanged(self.repo, frozen)

    def test_deleted_source_file_is_detected(self):
        frozen = provenance.snapshot_inputs(self.repo)
        (self.repo / "app/worker.py").unlink()
        with self.assertRaisesRegex(ValueError, "removed: app/worker.py"):
            provenance.assert_inputs_unchanged(self.repo, frozen)

    def test_generated_files_and_credentials_are_not_opened_or_hashed(self):
        frozen = provenance.snapshot_inputs(self.repo)
        excluded = (
            "app/__pycache__/worker.pyc", "app/.env.production",
            "ensemble/client.key", "ci/release/results/token.log",
            "ci/release/.aws/credentials",
            "frontend/patient-frontend/src/.npmrc",
            "frontend/patient-frontend/src/node_modules/dependency/index.js",
            "frontend/doctor-frontend/public/private.p12",
        )
        for name in excluded:
            self.write(name, "do not read")
        original = provenance._file_hash

        def refuse_sensitive_read(path):
            if path.relative_to(self.repo).as_posix() in excluded:
                raise AssertionError("An excluded local file was opened")
            return original(path)

        with mock.patch.object(provenance, "_file_hash", side_effect=refuse_sensitive_read):
            self.assertEqual(provenance.snapshot_inputs(self.repo), frozen)
            provenance.assert_inputs_unchanged(self.repo, frozen)

    def test_redirected_source_is_rejected_before_hashing(self):
        redirected = self.repo / "app/worker.py"
        original = provenance._is_link
        with mock.patch.object(
            provenance, "_is_link",
            side_effect=lambda path: path == redirected or original(path),
        ):
            with self.assertRaisesRegex(ValueError, "symbolic link or junction"):
                provenance.snapshot_inputs(self.repo)

    def test_missing_required_ui_input_cannot_produce_partial_snapshot(self):
        (self.repo / "frontend/doctor-frontend/package-lock.json").unlink()
        with self.assertRaises((OSError, ValueError)):
            provenance.snapshot_inputs(self.repo)

    def test_changed_file_during_read_cannot_be_accepted(self):
        target = self.repo / "app/worker.py"
        original = hashlib.file_digest

        def mutate_while_reading(stream, algorithm):
            result = original(stream, algorithm)
            if Path(stream.name) == target:
                target.write_bytes(b"replacement with different length")
            return result

        with mock.patch.object(provenance.hashlib, "file_digest", side_effect=mutate_while_reading):
            with self.assertRaisesRegex(ValueError, "changed while being read"):
                provenance.snapshot_inputs(self.repo)


if __name__ == "__main__":
    unittest.main()
