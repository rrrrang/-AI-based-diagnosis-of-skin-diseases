import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SUPPORT = Path(__file__).resolve().parents[1] / "support"
spec = importlib.util.spec_from_file_location("release_model_guard", SUPPORT / "model_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ModelGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "models"
        self.root.mkdir()
        self.lock_path = self.root.parent / "model-lock.json"
        self.document = {
            "schema_version": 1,
            "repository": "https://example.invalid/test",
            "source_commits": {model: "a" * 40 for model in guard.MODELS},
            "files": [],
        }
        for model in sorted(guard.MODELS):
            relative = model + "/model.bin"
            data = ("test data for " + model).encode()
            target = self.root / relative
            target.parent.mkdir()
            target.write_bytes(data)
            self.document["files"].append({
                "model": model, "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "source_commit": "a" * 40, "source_url": "https://example.invalid/file",
            })
        self.save_fixture()
        self.pinned = patch.object(guard, "TRUSTED_LOCK_SHA256", hashlib.sha256(self.lock_path.read_bytes()).hexdigest())
        self.pinned.start()
        self.addCleanup(self.pinned.stop)

    def save_fixture(self):
        self.lock_path.write_text(json.dumps(self.document), encoding="utf-8")

    def test_valid_bundle(self):
        self.assertEqual(guard.verify_bundle(self.root, self.lock_path), self.document)

    def test_weight_or_code_tamper_is_rejected(self):
        target = self.root / self.document["files"][0]["path"]
        original = target.read_bytes()
        target.write_bytes(b"x" * len(original))
        with self.assertRaisesRegex(ValueError, "checksum or size"):
            guard.verify_bundle(self.root, self.lock_path)

    def test_size_change_is_rejected(self):
        target = self.root / self.document["files"][0]["path"]
        target.write_bytes(target.read_bytes() + b"x")
        with self.assertRaisesRegex(ValueError, "checksum or size"):
            guard.verify_bundle(self.root, self.lock_path)

    def test_lock_and_bundle_cannot_be_replaced_together(self):
        entry = self.document["files"][0]
        payload = b"modified checkpoint"
        (self.root / entry["path"]).write_bytes(payload)
        entry.update(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
        self.save_fixture()
        with self.assertRaisesRegex(ValueError, "pinned trusted checksum"):
            guard.verify_bundle(self.root, self.lock_path)

    def test_unlisted_python_code_is_rejected(self):
        (self.root / "mobilenet" / "unexpected.py").write_text("raise RuntimeError", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "file set mismatch"):
            guard.verify_bundle(self.root, self.lock_path)

    def test_missing_file_is_rejected(self):
        (self.root / self.document["files"][0]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "file set mismatch"):
            guard.verify_bundle(self.root, self.lock_path)

    def test_unsafe_paths_are_rejected(self):
        for value in (
            "/mobilenet/file", "../mobilenet/file", "mobilenet/../outside",
            "mobilenet//file", "mobilenet/./file", "mobilenet/",
            "mobilenet\\file", "C:/models/file", "other/file", "mobilenet/\x00",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                guard.safe_relative_path(value)

    def test_duplicate_paths_are_rejected(self):
        document = copy.deepcopy(self.document)
        document["files"].append(copy.deepcopy(document["files"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate path"):
            guard.validate_document(document)

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            json.loads('{"path":"one","path":"two"}', object_pairs_hook=guard._unique_object)

    def test_symlink_is_rejected_even_with_correct_file_bytes(self):
        target = self.root / self.document["files"][0]["path"]
        outside = self.root.parent / "outside.bin"
        target.replace(outside)
        try:
            target.symlink_to(outside)
        except OSError as error:
            self.skipTest("Host does not permit symlink creation: " + str(error))
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            guard.verify_bundle(self.root, self.lock_path)


class CommittedLockTests(unittest.TestCase):
    def test_committed_lock_checksum_and_expected_models(self):
        document = guard.load_lock()
        self.assertEqual(len(document["files"]), 9)
        self.assertEqual({item["model"] for item in document["files"]}, guard.MODELS)
        self.assertEqual(
            {item["path"]: item["sha256"] for item in document["files"] if item["path"].endswith((".pt", ".pth"))},
            {
                "mobilenet/model/best.pt": "493e76716efeada4bbb3effddc7f1e9ee9f78055cef4e8492cbddfa7fc45ea6f",
                "resnet50/models/resnet50_side_best.pth": "2fb9580777988c5bb9506be107d8e1d18d53a857d9cce7ead4f79ab62842e0d3",
                "yolo/models/yolo11_detect/side_six_class_augmented/weights/best.pt": "e792fb2374a6024f49249a40a9f2807282ef8d1bad9c3ec5c2f48055d03ed800",
            },
        )


if __name__ == "__main__":
    unittest.main()
