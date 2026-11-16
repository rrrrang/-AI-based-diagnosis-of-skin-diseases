"""Synthetic CI histories only: no live Jenkins, Docker, network or credentials."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / 'select_ci_builds.py'
SPEC = importlib.util.spec_from_file_location('select_ci_under_test', SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
SHA = 'a' * 40
OTHER = 'b' * 40


def metadata(number, commit=SHA, result='SUCCESS', completed=True, branch=module.BRANCH):
    return f'''<flow-build><actions><hudson.plugins.git.util.BuildData>
<buildsByBranchName>
<entry><string>refs/remotes/origin/old</string><hudson.plugins.git.util.Build>
<marked><sha1>{SHA}</sha1></marked><revision reference="../marked"/><hudsonBuildNumber>1</hudsonBuildNumber>
</hudson.plugins.git.util.Build></entry>
<entry><string>{branch}</string><hudson.plugins.git.util.Build>
<marked><sha1>{commit}</sha1></marked><revision reference="../marked"/><hudsonBuildNumber>{number}</hudsonBuildNumber>
</hudson.plugins.git.util.Build></entry></buildsByBranchName>
<lastBuild reference="../buildsByBranchName/entry[2]/hudson.plugins.git.util.Build"/>
<remoteUrls><string>{module.REPOSITORY}.git</string></remoteUrls>
</hudson.plugins.git.util.BuildData></actions><completed>{str(completed).lower()}</completed>
<result>{result}</result><duration>1234</duration></flow-build>'''


def console(commit=SHA, result='SUCCESS', branch=module.BRANCH):
    return f'Checking out Revision {commit} ({branch})\nTests complete\nFinished: {result}\n'


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skinai-selection-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for role, number in [('ui', 11), ('backend', 29), ('workflow', 5)]:
            self.write(role, number)

    def folder(self, role, number):
        return self.home / 'jobs' / module.JOBS[role] / 'builds' / str(number)

    def write(self, role, number, commit=SHA, result='SUCCESS', completed=True, branch=module.BRANCH):
        folder = self.folder(role, number)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'build.xml').write_text(metadata(number, commit, result, completed, branch), encoding='utf-8')
        (folder / 'log').write_text(console(commit, result, branch), encoding='utf-8')
        return folder

    def select(self):
        return module.select_builds(self.home, SHA)

    def test_exact_three_successes_include_existing_collector_proof(self):
        self.assertEqual(module.BRANCH, 'refs/remotes/origin/main')
        result = self.select()
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['builds'], {'ui': 11, 'backend': 29, 'workflow': 5})
        self.assertEqual(result['ci']['workflow']['commit'], SHA)
        self.assertIn('files_sha256', result['audit'])

    def test_newer_failed_same_commit_cannot_reuse_old_success(self):
        self.write('backend', 30, result='FAILURE')
        result = self.select()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['jobs']['backend']['build'], 30)
        self.assertNotIn('backend', result['builds'])
        self.assertNotIn('ci', result)

    def test_newer_running_same_commit_blocks_old_success_even_with_success_result(self):
        self.write('ui', 12, completed=False)
        result = self.select()
        self.assertEqual(result['status'], 'WAITING')
        self.assertEqual(result['jobs']['ui']['reason'], 'BUILD_RUNNING')
        self.assertNotIn('ci', result)

    def test_latest_retry_success_replaces_failure(self):
        self.write('backend', 30, result='FAILURE')
        self.write('backend', 31)
        result = self.select()
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['builds']['backend'], 31)

    def test_other_commit_results_never_substitute_and_known_other_commit_can_be_skipped(self):
        self.write('ui', 12, commit=OTHER, result='FAILURE')
        self.assertEqual(self.select()['builds']['ui'], 11)
        self.write('workflow', 5, commit=OTHER)
        result = self.select()
        self.assertEqual(result['status'], 'WAITING')
        self.assertEqual(result['jobs']['workflow']['reason'], 'NO_MATCHING_BUILD')

    def test_historical_matching_sha_is_not_current_source(self):
        self.write('workflow', 5, commit=OTHER)
        result = self.select()
        self.assertEqual(result['status'], 'WAITING')
        self.assertNotIn('workflow', result['builds'])

    def test_wrong_branch_cannot_satisfy_same_sha(self):
        for branch in ['refs/remotes/origin/ci/photo-intake-contract',
                       'refs/remotes/origin/wrong-branch']:
            with self.subTest(branch=branch):
                self.write('workflow', 5, branch=branch)
                self.assertEqual(self.select()['status'], 'WAITING')

    def test_new_unknown_attempt_blocks_until_a_new_verified_attempt(self):
        folder = self.folder('backend', 30)
        folder.mkdir(parents=True)
        result = self.select()
        self.assertEqual(result['status'], 'WAITING')
        self.assertEqual(result['jobs']['backend']['reason'], 'METADATA_NOT_WRITTEN')
        (folder / 'build.xml').write_text('<flow-build><completed>true</completed><result>FAILURE</result></flow-build>')
        self.assertEqual(self.select()['status'], 'FAILED')
        self.write('backend', 31)
        self.assertEqual(self.select()['status'], 'READY')

    def test_old_unknown_failure_does_not_block_newer_matching_success(self):
        folder = self.folder('ui', 10)
        folder.mkdir(parents=True)
        (folder / 'build.xml').write_text('<flow-build><completed>true</completed><result>FAILURE</result></flow-build>')
        self.assertEqual(self.select()['status'], 'READY')

    def test_inconsistent_console_blocks_metadata_success(self):
        (self.folder('ui', 11) / 'log').write_text(console(OTHER), encoding='utf-8')
        result = self.select()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['jobs']['ui']['reason'], 'SUCCESS_EVIDENCE_INVALID')

    def test_attempt_started_during_collection_cannot_produce_ready(self):
        original = module.collect_evidence
        def changed(*args):
            value = original(*args)
            self.write('workflow', 6, completed=False)
            return value
        with mock.patch.object(module, 'collect_evidence', side_effect=changed):
            result = self.select()
        self.assertEqual(result['status'], 'WAITING')
        self.assertEqual(result['reason'], 'BUILD_ATTEMPTS_CHANGED')
        self.assertNotIn('ci', result)

    def test_only_fixed_jobs_and_numeric_build_evidence_are_opened(self):
        extra = self.home / 'jobs' / 'Unrelated' / 'builds' / '1'
        extra.mkdir(parents=True)
        (extra / 'build.xml').write_text('do not read')
        (self.home / 'credentials.xml').write_text('do not read')
        original = module._read_evidence_file
        observed = []
        def guarded(home, path, maximum):
            relative = path.relative_to(self.home)
            self.assertEqual(relative.parts[0], 'jobs')
            self.assertIn(relative.parts[1], module.JOBS.values())
            self.assertTrue(relative.parts[3].isdecimal())
            self.assertIn(relative.name, ('build.xml', 'log'))
            observed.append(relative)
            return original(home, path, maximum)
        with mock.patch.object(module, '_read_evidence_file', side_effect=guarded):
            self.assertEqual(self.select()['status'], 'READY')
        self.assertTrue(observed)

    def test_upstream_causes_require_allowed_job_exact_build_and_success(self):
        causes = [{'upstreamProject': module.JOBS['ui'], 'upstreamBuild': 11, 'shortDescription': 'ignored'}]
        self.assertEqual(module.resolve_upstream_causes(self.home, causes), [
            {'role': 'ui', 'job': module.JOBS['ui'], 'build': 11, 'commit': SHA}])
        self.assertEqual(len(module.resolve_upstream_causes(self.home, causes * 2)), 1)
        for bad in [[], [{'upstreamProject': '../credentials', 'upstreamBuild': 1}],
                    [{'upstreamProject': module.JOBS['ui'], 'upstreamBuild': '../11'}],
                    [{'upstreamProject': module.JOBS['ui'], 'upstreamBuild': True}],
                    [{**causes[0], '_class': 'unknown'}]]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                module.resolve_upstream_causes(self.home, bad)
        self.write('ui', 11, result='FAILURE')
        with self.assertRaises(ValueError):
            module.resolve_upstream_causes(self.home, causes)

    def test_cli_writes_safe_status_and_never_replaces_existing_file(self):
        output = self.home / 'selected.json'
        args = ['--jenkins-home', str(self.home), '--commit', SHA, '--output', str(output)]
        self.write('workflow', 5, result='FAILURE')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 0)
        self.assertEqual(json.loads(output.read_text())['status'], 'FAILED')
        before = output.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(args), 1)
        self.assertEqual(output.read_bytes(), before)

    def test_outdated_verified_trigger_never_publishes_new_checkout(self):
        self.write('ui', 12, commit=OTHER)
        cause_file = self.home / 'causes.json'
        cause_file.write_text(json.dumps([{'upstreamProject': module.JOBS['ui'], 'upstreamBuild': 12}]))
        output = self.home / 'selected.json'
        with redirect_stdout(io.StringIO()):
            code = module.main(['--jenkins-home', str(self.home), '--commit', SHA,
                                '--causes', str(cause_file), '--output', str(output)])
        self.assertEqual(code, 0)
        result = json.loads(output.read_text())
        self.assertEqual(result['status'], 'WAITING')
        self.assertEqual(result['reason'], 'UPSTREAM_COMMIT_MISMATCH')
        self.assertNotIn('ci', result)

    def test_invalid_commit_is_rejected(self):
        for value in ['main', 'a' * 7, 'A' * 40, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.select_builds(self.home, value)


if __name__ == '__main__':
    unittest.main(verbosity=2)