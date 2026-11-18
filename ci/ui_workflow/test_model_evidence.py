"""Synthetic lock/report checks; no Docker, model weights, or private settings."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from model_evidence import GUARD_PATH, LOCK_PATH, load_model_identity, verify_workflow_model_evidence


class ModelEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.results = self.root / "results"
        self.results.mkdir()
        self.versions = {"mobilenet": "a" * 64, "resnet50": "b" * 64, "yolo": "c" * 64}
        self.identity = {"expected_model_versions": self.versions}
        for count in (2, 3):
            self.write_evidence(count)

    def write_evidence(self, count, **changes):
        document = {"status": "passed", "photo_count": count,
                    "model_keys": list(self.versions), "model_versions": self.versions.copy(),
                    "checked": {"three_real_model_results": True, "yolo_six_class_response_checked": True}}
        document.update(changes)
        (self.results / f"workflow-{count}-photos.json").write_text(json.dumps(document), encoding="utf-8")

    def write_lock(self, extra_checkpoint=False):
        entries = [{"model": model, "path": model + "/weights.pt", "sha256": value,
                    "bytes": 1, "source_commit": "d" * 40, "source_url": "https://example.invalid/weights.pt"}
                   for model, value in self.versions.items()]
        if extra_checkpoint:
            entries.append({**entries[-1], "path": "yolo/another.pt"})
        document = {"schema_version": 1, "repository": "https://example.invalid/repository",
                    "source_commits": dict.fromkeys(self.versions, "d" * 40), "files": entries}
        lock = self.root / LOCK_PATH
        lock.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(document).encode("utf-8")
        lock.write_bytes(raw)
        real_guard = Path(__file__).resolve().parents[2] / GUARD_PATH
        code = real_guard.read_text(encoding="utf-8")
        code, count = re.subn(r'TRUSTED_LOCK_SHA256 = "[0-9a-f]{64}"',
                             'TRUSTED_LOCK_SHA256 = "' + hashlib.sha256(raw).hexdigest() + '"', code)
        self.assertEqual(count, 1)
        guard = self.root / GUARD_PATH
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_text(code, encoding="utf-8")
        return lock, guard

    def test_both_flows_require_exact_models_and_six_class_evidence(self):
        report = verify_workflow_model_evidence(self.results, self.identity)
        self.assertTrue(report["checkpoint_hashes_matched"])
        self.assertTrue(report["yolo_six_class_evidence_verified"])
        self.assertEqual(report["workflow_photo_counts"], [2, 3])

    def test_old_or_other_checkpoint_fails_even_with_passed_status(self):
        versions = {**self.versions, "yolo": "e" * 64}
        self.write_evidence(3, model_versions=versions)
        with self.assertRaisesRegex(ValueError, "checkpoint hashes"):
            verify_workflow_model_evidence(self.results, self.identity)

    def test_missing_model_hash_fails(self):
        versions = {key: value for key, value in self.versions.items() if key != "resnet50"}
        self.write_evidence(2, model_versions=versions)
        with self.assertRaisesRegex(ValueError, "checkpoint hashes"):
            verify_workflow_model_evidence(self.results, self.identity)

    def test_missing_second_flow_is_not_a_pass(self):
        (self.results / "workflow-3-photos.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            verify_workflow_model_evidence(self.results, self.identity)

    def test_missing_or_non_boolean_six_class_flag_fails(self):
        for checked in ({"three_real_model_results": True},
                        {"three_real_model_results": True, "yolo_six_class_response_checked": "true"},
                        {"three_real_model_results": False, "yolo_six_class_response_checked": True}):
            with self.subTest(checked=checked):
                self.write_evidence(2, checked=checked)
                with self.assertRaisesRegex(ValueError, "Six-class"):
                    verify_workflow_model_evidence(self.results, self.identity)

    def test_wrong_photo_count_or_duplicate_model_key_fails(self):
        for changes in ({"photo_count": 3}, {"status": "failed"},
                        {"model_keys": ["mobilenet", "yolo", "yolo"]}):
            with self.subTest(changes=changes):
                self.write_evidence(2, **changes)
                with self.assertRaises(ValueError):
                    verify_workflow_model_evidence(self.results, self.identity)

    def test_guard_validates_lock_and_both_input_hashes_are_recorded(self):
        lock, guard = self.write_lock()
        result = load_model_identity(self.root)
        self.assertEqual(result["expected_model_versions"], self.versions)
        self.assertEqual(result["model_lock_sha256"], hashlib.sha256(lock.read_bytes()).hexdigest())
        self.assertEqual(result["model_guard_sha256"], hashlib.sha256(guard.read_bytes()).hexdigest())

    def test_lock_edit_without_updated_trusted_guard_is_rejected(self):
        lock, _ = self.write_lock()
        lock.write_bytes(lock.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "trusted checksum"):
            load_model_identity(self.root)

    def test_ambiguous_multiple_weights_for_one_model_is_rejected(self):
        self.write_lock(extra_checkpoint=True)
        with self.assertRaisesRegex(ValueError, "one checkpoint"):
            load_model_identity(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
