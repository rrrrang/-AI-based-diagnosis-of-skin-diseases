"""Unit tests use synthetic Jenkins metadata; no controller or credentials are read."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_ci_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_ci_evidence_under_test", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


def metadata(number, commit=COMMIT, result="SUCCESS", completed="true", branch=module.BRANCH):
    return f'''<flow-build>
<actions><hudson.plugins.git.util.BuildData>
<buildsByBranchName>
<entry><string>refs/remotes/origin/old-branch</string><hudson.plugins.git.util.Build>
<marked><sha1>{OTHER_COMMIT}</sha1></marked><revision reference="../marked"/>
<hudsonBuildNumber>1</hudsonBuildNumber></hudson.plugins.git.util.Build></entry>
<entry><string>{branch}</string><hudson.plugins.git.util.Build>
<marked><sha1>{commit}</sha1></marked><revision reference="../marked"/>
<hudsonBuildNumber>{number}</hudsonBuildNumber></hudson.plugins.git.util.Build></entry>
</buildsByBranchName><lastBuild reference="../buildsByBranchName/entry[2]/hudson.plugins.git.util.Build"/>
<remoteUrls><string>{module.REPOSITORY}.git</string></remoteUrls>
</hudson.plugins.git.util.BuildData></actions>
<result>{result}</result><duration>1234</duration><completed>{completed}</completed>
</flow-build>'''


def log(commit=COMMIT, branch=module.BRANCH):
    return f"Started by an SCM change\nChecking out Revision {commit} ({branch})\nTests passed\nFinished: SUCCESS\n"


class CollectEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skinai-ci-evidence-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.builds = {"ui": 9, "backend": 27, "workflow": 3}
        for key, number in self.builds.items():
            self.write_build(key, metadata(number), log())

    def folder(self, key):
        return self.home / "jobs" / module.JOBS[key] / "builds" / str(self.builds[key])

    def write_build(self, key, xml=None, console=None):
        folder = self.folder(key)
        folder.mkdir(parents=True, exist_ok=True)
        if xml is not None:
            (folder / "build.xml").write_text(xml, encoding="utf-8")
        if console is not None:
            (folder / "log").write_text(console, encoding="utf-8")

    def collect(self, commit=COMMIT, builds=None):
        return module.collect_evidence(self.home, commit, builds or self.builds)

    def test_three_explicit_completed_builds_and_audit_hashes(self):
        self.assertEqual(module.BRANCH, "refs/remotes/origin/main")
        evidence, audit = self.collect()
        self.assertEqual(set(evidence), {"ui", "backend", "workflow"})
        for key, entry in evidence.items():
            self.assertEqual(entry, {"job": module.JOBS[key], "build": self.builds[key],
                                     "result": "SUCCESS", "commit": COMMIT})
            self.assertRegex(audit["files_sha256"][key]["build_xml_sha256"], r"^[a-f0-9]{64}$")
        self.assertNotIn("Tests passed", json.dumps(audit))

    def test_failed_result_is_rejected_even_if_console_claims_success(self):
        self.write_build("backend", metadata(27, result="FAILURE"))
        with self.assertRaisesRegex(ValueError, "did not finish SUCCESS"):
            self.collect()

    def test_unfinished_build_is_rejected_even_with_success_field(self):
        self.write_build("workflow", metadata(3, completed="false"))
        with self.assertRaisesRegex(ValueError, "has not finished"):
            self.collect()

    def test_different_commit_is_rejected(self):
        self.write_build("ui", metadata(9, commit=OTHER_COMMIT), log(OTHER_COMMIT))
        with self.assertRaisesRegex(ValueError, "commit does not match"):
            self.collect()

    def test_old_branch_matching_sha_cannot_substitute_current_revision(self):
        # OTHER_COMMIT exists in all historical entries, but is not the checked source.
        with self.assertRaisesRegex(ValueError, "commit does not match"):
            self.collect(commit=OTHER_COMMIT)

    def test_multiple_checkouts_are_rejected_even_at_same_commit(self):
        for second in [COMMIT, OTHER_COMMIT]:
            with self.subTest(second=second):
                duplicate = log().replace("Tests passed", f"Checking out Revision {second} ({module.BRANCH})")
                self.write_build("ui", console=duplicate)
                with self.assertRaisesRegex(ValueError, "exactly one checkout"):
                    self.collect()

    def test_log_and_metadata_must_agree(self):
        self.write_build("ui", console=log(OTHER_COMMIT))
        with self.assertRaisesRegex(ValueError, "Console checkout"):
            self.collect()

    def test_wrong_branch_is_rejected_even_with_matching_commit(self):
        for branch in ["refs/remotes/origin/ci/photo-intake-contract",
                       "refs/remotes/origin/wrong-branch"]:
            with self.subTest(branch=branch):
                self.write_build("backend", metadata(27, branch=branch), log(branch=branch))
                with self.assertRaisesRegex(ValueError, "selected CI branch"):
                    self.collect()

    def test_last_scm_revision_and_build_number_cannot_be_stale(self):
        with self.subTest("old lastBuild"):
            self.write_build("ui", metadata(9).replace("entry[2]/", "entry[1]/"))
            with self.assertRaisesRegex(ValueError, "last SCM revision"):
                self.collect()
        with self.subTest("previous build number"):
            self.write_build("ui", metadata(8))
            with self.assertRaisesRegex(ValueError, "different build number"):
                self.collect()

    def test_wrong_repository_is_rejected(self):
        self.write_build("ui", metadata(9).replace(module.REPOSITORY, "https://example.invalid/other"))
        with self.assertRaisesRegex(ValueError, "unexpected repository"):
            self.collect()

    def test_console_must_have_final_success_marker(self):
        for console in [log().replace("Finished: SUCCESS", ""),
                        log().replace("Finished: SUCCESS", "Finished: FAILURE"),
                        log() + "unexpected trailing output\n"]:
            with self.subTest(console=console[-40:]):
                self.write_build("ui", console=console)
                with self.assertRaisesRegex(ValueError, "does not end"):
                    self.collect()

    def test_build_number_and_full_commit_validation(self):
        for value in [0, -1, True, "../9", "01", "lastSuccessfulBuild", 2_147_483_648]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.collect(builds={**self.builds, "ui": value})
        for commit in ["a" * 7, "A" * 40, None]:
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                self.collect(commit=commit)

    def test_cli_writes_only_after_all_three_pass_and_never_overwrites(self):
        output = self.home / "output/evidence.json"
        args = ["--jenkins-home", str(self.home), "--ui-build", "9", "--backend-build", "27",
                "--workflow-build", "3", "--commit", COMMIT, "--output", str(output)]
        self.write_build("workflow", metadata(3, result="FAILURE"))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(args), 1)
        self.assertFalse(output.exists())
        self.write_build("workflow", metadata(3))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 0)
        self.assertEqual(json.loads(output.read_text())["workflow"]["build"], 3)
        self.assertTrue(output.with_name("evidence.audit.json").exists())
        original = output.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(args), 1)
        self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)