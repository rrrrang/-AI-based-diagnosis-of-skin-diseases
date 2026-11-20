"""Synthetic lock/report checks; no Docker, model weights, or private settings."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from model_evidence import (GUARD_PATH, LOCK_PATH, GRADCAM_CHECKS, DOCTOR_MODEL_UI_CHECKS, load_model_identity,
                            verify_workflow_model_evidence, verify_gradcam_evidence)


class ModelEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.results = self.root / "results"
        self.results.mkdir()
        self.versions = {"mobilenet": "a" * 64, "resnet50": "b" * 64, "yolo": "c" * 64}
        self.identity = {"expected_model_versions": self.versions}
        for count in (2, 3):
            self.write_evidence(count)

    def write_evidence(self, count, focused=False, **changes):
        document = {"status": "passed", "photo_count": count,
                    "verification_scope": "gradcam-only" if focused else "full-workflow",
                    "model_keys": list(self.versions), "model_versions": self.versions.copy(),
                    "checked": {"three_real_model_results": True, "yolo_six_class_response_checked": True,
                                **dict.fromkeys(GRADCAM_CHECKS, True)},
                    "gradcam": {"http_status": 200, "content_type": "image/png", "byte_length": 4096,
                                "width": 224, "height": 224, "ui_natural_width": 224,
                                "ui_natural_height": 224, "anonymous_status": 401, "patient_status": 403}}
        if focused:
            document["checked"]["gradcam_unassigned_doctor_blocked"] = True
            document["gradcam"]["unassigned_doctor_status"] = 404
        else:
            document["checked"].update(dict.fromkeys(DOCTOR_MODEL_UI_CHECKS, True))
        document.update(changes)
        prefix = "gradcam" if focused else "workflow"
        (self.results / f"{prefix}-{count}-photos.json").write_text(json.dumps(document), encoding="utf-8")
        return document

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
        self.assertTrue(report["gradcam_storage_access_ui_verified"])
        self.assertTrue(report["ensemble_decision_visible_in_doctor_ui"])
        self.assertTrue(report["three_model_rows_match_api"])
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

    def test_gradcam_flags_cannot_be_missing_false_or_truthy_strings(self):
        for key in GRADCAM_CHECKS:
            for value in (None, False, "true"):
                with self.subTest(key=key, value=value):
                    document = self.write_evidence(2)
                    if value is None:
                        del document["checked"][key]
                    else:
                        document["checked"][key] = value
                    self.write_evidence(2, checked=document["checked"])
                    with self.assertRaisesRegex(ValueError, "Grad-CAM"):
                        verify_workflow_model_evidence(self.results, self.identity)

    def test_png_measurements_and_authorization_must_be_proven(self):
        for key, value in (("http_status", 404), ("content_type", "image/jpeg"),
                           ("byte_length", 8), ("byte_length", True), ("width", 0),
                           ("height", -1), ("ui_natural_width", 0), ("ui_natural_height", 223),
                           ("anonymous_status", 200), ("patient_status", 200)):
            with self.subTest(key=key, value=value):
                document = self.write_evidence(3)
                document["gradcam"][key] = value
                self.write_evidence(3, gradcam=document["gradcam"])
                with self.assertRaisesRegex(ValueError, "Grad-CAM"):
                    verify_workflow_model_evidence(self.results, self.identity)
        self.write_evidence(3, gradcam=None)
        with self.assertRaisesRegex(ValueError, "PNG evidence"):
            verify_workflow_model_evidence(self.results, self.identity)

    def test_doctor_model_ui_flags_must_be_proven_for_both_photo_counts(self):
        for count in (2, 3):
            for key in DOCTOR_MODEL_UI_CHECKS:
                for value in (None, False, "true", 1):
                    with self.subTest(count=count, key=key, value=value):
                        for other_count in (2, 3):
                            self.write_evidence(other_count)
                        document = self.write_evidence(count)
                        if value is None:
                            del document["checked"][key]
                        else:
                            document["checked"][key] = value
                        self.write_evidence(count, checked=document["checked"])
                        with self.assertRaisesRegex(ValueError, "Doctor ensemble/model UI"):
                            verify_workflow_model_evidence(self.results, self.identity)

    def test_focused_evidence_is_separate_and_checks_other_doctor(self):
        for count in (2, 3):
            document = self.write_evidence(count, focused=True)
            self.assertTrue(all(key not in document["checked"] for key in DOCTOR_MODEL_UI_CHECKS))
        report = verify_gradcam_evidence(self.results, self.identity)
        self.assertEqual(report["verification_scope"], "gradcam-only")
        self.assertTrue(report["gradcam_unassigned_doctor_blocked"])
        document = self.write_evidence(2, focused=True)
        del document["checked"]["gradcam_unassigned_doctor_blocked"]
        self.write_evidence(2, focused=True, checked=document["checked"])
        with self.assertRaisesRegex(ValueError, "Grad-CAM"):
            verify_gradcam_evidence(self.results, self.identity)
        document = self.write_evidence(2, focused=True)
        document["gradcam"]["unassigned_doctor_status"] = 200
        self.write_evidence(2, focused=True, gradcam=document["gradcam"])
        with self.assertRaisesRegex(ValueError, "authorization"):
            verify_gradcam_evidence(self.results, self.identity)

    def test_focused_results_cannot_satisfy_full_gate_even_if_renamed(self):
        for count in (2, 3):
            document = self.write_evidence(count, focused=True)
            self.write_evidence(count, **document)
        with self.assertRaisesRegex(ValueError, "scope must be full-workflow"):
            verify_workflow_model_evidence(self.results, self.identity)

    def test_full_results_cannot_satisfy_focused_scope(self):
        for count in (2, 3):
            document = self.write_evidence(count)
            self.write_evidence(count, focused=True, **document)
        with self.assertRaisesRegex(ValueError, "scope must be gradcam-only"):
            verify_gradcam_evidence(self.results, self.identity)

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
