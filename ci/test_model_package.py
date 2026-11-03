"""Run the package check on small temporary fixtures. No trained model is required."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CHECK = Path(__file__).with_name("check_model_package.py")


class ModelPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.files = {
            "model_config.json": b'{"fixture":true}',
            "preprocess.json": b'{"fixture":true}',
            "classes.json": b'["test_class"]',
            "manifest.json": b'{"fixture":true}',
            "model.pt": b"synthetic bytes for verifying the digest only",
        }
        for name, content in self.files.items():
            (self.directory / name).write_bytes(content)
        self.digest = hashlib.sha256(self.files["model.pt"]).hexdigest()

    def run_check(self, digest, *extra_args):
        return subprocess.run(
            [sys.executable, str(CHECK), str(self.directory), "--weights-sha256", digest, *extra_args],
            capture_output=True, text=True, timeout=15,
        )

    def test_valid_files_and_independent_digest(self):
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

    def test_rejects_empty_documents_or_incorrect_container_type(self):
        for name, content in [("classes.json", "[]"), ("classes.json", "{}"),
                              ("manifest.json", "[]"), ("model_config.json", "null")]:
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
