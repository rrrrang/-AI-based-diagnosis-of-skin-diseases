"""Run the package check on small temporary fixtures. No trained model is required."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CHECK = Path(__file__).with_name("check_model_package.py")
LABELS = {"건선": 0, "아토피": 1, "여드름": 2, "정상": 3, "주사": 4, "지루": 5}


class ModelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.files = {
            "model_config.json": b'{"fixture":true}',
            "preprocess.json": b'{"fixture":true}',
            "classes.json": json.dumps({"class_to_id": LABELS}, ensure_ascii=False).encode("utf-8"),
            "manifest.json": b'{"fixture":true}',
            "model.pt": b"synthetic bytes for verifying the digest only",
        }
        for name, content in self.files.items():
            (self.directory / name).write_bytes(content)
        self.digest = hashlib.sha256(self.files["model.pt"]).hexdigest()

    def run_check(self, digest, *extra_args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(CHECK), str(self.directory), "--weights-sha256", digest, *extra_args],
            capture_output=True, encoding="utf-8", timeout=15,
        )

    def test_valid_files_and_independent_digest(self):
        for document in ({"class_to_id": LABELS}, dict(reversed(LABELS.items())), list(LABELS)):
            with self.subTest(document=document):
                (self.directory / "classes.json").write_text(json.dumps(document), encoding="utf-8")
                result = self.run_check(self.digest)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("PASS", result.stdout)

    def test_alternative_weights_filename(self):
        (self.directory / "model.pt").rename(self.directory / "model.onnx")
        result = self.run_check(self.digest, "--weights-file", "model.onnx")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("model.onnx", result.stdout)

    def test_rejects_paths_and_config_as_weights(self):
        for name in ("../elsewhere", r"..\other", "C:outside", "classes.json"):
            with self.subTest(name=name):
                result = self.run_check(self.digest, "--weights-file", name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("--weights-file", result.stderr)

    def test_each_file_is_required(self):
        for name, content in self.files.items():
            with self.subTest(name=name):
                path = self.directory / name
                path.unlink()
                result = self.run_check(self.digest)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                path.write_bytes(content)

    def test_invalid_json(self):
        (self.directory / "preprocess.json").write_bytes(b"{")
        result = self.run_check(self.digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preprocess.json", result.stderr)

    def test_rejects_invalid_config_documents_and_class_mappings(self):
        invalid_mappings = [
            {"class_to_id": {**LABELS, "여드름": 3, "정상": 2}},
            {"class_to_id": {**LABELS, "정상": 2}},
            {"class_to_id": {key: value for key, value in LABELS.items() if key != "정상"}},
            {"class_to_id": {**LABELS, "기타": 6}},
            {"class_to_id": {**LABELS, "정상": "3"}},
            {"class_to_id": {**LABELS, "정상": 3.0}},
            {"class_to_id": {**LABELS, "건선": False}},
            ["건선", "아토피", "정상", "여드름", "주사", "지루"],
        ]
        bad_files = [("classes.json", json.dumps(document)) for document in invalid_mappings]
        duplicate_key = json.dumps(LABELS, ensure_ascii=False).replace('"정상": 3', '"정상": 2, "정상": 3')
        bad_files.extend([("classes.json", duplicate_key), ("classes.json", "[]"), ("classes.json", "{}"),
                          ("manifest.json", "[]"), ("model_config.json", "null")])
        for name, content in bad_files:
            with self.subTest(name=name, content=content):
                path = self.directory / name
                path.write_text(content, encoding="utf-8")
                result = self.run_check(self.digest)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                path.write_bytes(self.files[name])

    def test_rejects_empty_weights_even_with_matching_digest(self):
        (self.directory / "model.pt").write_bytes(b"")
        result = self.run_check(hashlib.sha256(b"").hexdigest())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty", result.stderr)

    def test_rejects_mismatched_or_malformed_digest(self):
        for digest in ["0" * 64, "invalid"]:
            with self.subTest(digest=digest):
                result = self.run_check(digest)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("SHA-256", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
