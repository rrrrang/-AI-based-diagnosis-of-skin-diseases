"""Release orchestration uses fake processes/registry/CI only."""
from argparse import Namespace
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

BASE = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

module = load('auto_release_under_test', BASE / 'auto_release.py')
release_fixture = load('release_fixture_for_auto', BASE / 'handoff/test_release.py')
preview_fixture = load('preview_fixture_for_auto', BASE / 'tests/test_publish.py')
SHA = 'a' * 40


class AutomaticReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skinai-auto-release-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = module._output(self.root / 'artifacts')
        self.gate = {'schema': 'skinai.ci-selection/v1', 'status': 'READY', 'commit': SHA,
                     'branch': module.BRANCH, 'builds': {'ui': 3, 'backend': 3, 'workflow': 3},
                     'jobs': {}, 'ci': release_fixture.valid_release()['ci']}
        self.gate_path = self.output / 'gate.json'
        module._json(self.gate_path, self.gate)
        self.args = Namespace(gate=self.gate_path, state_root=self.root / 'state', output=self.output,
                              jenkins_home=self.root / 'jenkins', docker='docker-fake',
                              models=self.root / 'models', sample=self.root / 'sample.png',
                              node_dir=self.root / 'node', browsers=self.root / 'browsers',
                              auth_scratch=self.root / 'scratch')
        self.selected = mock.patch.object(module, 'select_builds', side_effect=lambda *_: copy.deepcopy(self.gate)).start()
        self.source = mock.patch.object(module, '_source').start()
        self.hashes = mock.patch.object(module, 'assert_inputs_unchanged').start()
        self.addCleanup(mock.patch.stopall)
        self.commands = []
        self.auth_open = False
        self.auth_calls = 0
        self.registry_calls = []
        self.process = mock.patch.object(module, '_run', side_effect=self.fake_run).start()
        mock.patch.object(module, '_auth_session', side_effect=self.fake_auth).start()
        mock.patch.object(module, 'verify_public_image', side_effect=self.fake_verify).start()

    @contextmanager
    def fake_auth(self, *_):
        self.auth_calls += 1
        self.auth_open = True
        try:
            yield {'SAFE_CHILD_ENV': 'true'}
        finally:
            self.auth_open = False

    def fake_verify(self, repository, tag, local_id, commit, expected_digest=None):
        self.assertFalse(self.auth_open, 'Success verification/artifact must follow auth cleanup')
        self.registry_calls.append(repository)
        item = next(item for item in release_fixture.valid_release()['services'].values()
                    if item['repository'] == repository)
        self.assertEqual(commit, SHA)
        self.assertEqual(expected_digest, item['digest'])
        return {key: item[key] for key in ('digest', 'platform_digest', 'config_digest', 'visibility')}

    def write_preview(self, path):
        path.mkdir(parents=True)
        (path / 'results').mkdir()
        candidate, summary, _, _ = preview_fixture.fixture()
        module._json(path / 'candidate.json', candidate)
        module._json(path / 'results/preview-summary.json', summary)
        module._json(path / 'preview-state.json', {'test_only': True})

    def fake_run(self, command, timeout=60, env=None):
        command = list(map(str, command))
        self.commands.append(command)
        name = Path(command[2]).name
        if name == 'prepare_preview.py':
            output = Path(command[command.index('--output') + 1])
            if '--cleanup' not in command:
                self.assertFalse(output.exists())
                state_path = output.parent / 'state.json'
                self.assertEqual(module.read_json(state_path)['preview'], output.name)
                self.write_preview(output)
            return ''
        if name == 'publish.py':
            self.assertTrue(self.auth_open)
            self.assertEqual(env, {'SAFE_CHILD_ENV': 'true'})
            output = Path(command[command.index('--output') + 1])
            output.mkdir()
            module._json(output / 'release.json', release_fixture.valid_release())
            module._json(output / 'publication_report.json', {'status': 'images-verified'})
            module._json(output / 'ci-evidence.json', self.gate['ci'])
            (output / 'logs').mkdir()
            (output / 'logs/private.log').write_text('must never be archived')
            return ''
        raise AssertionError('Unexpected fake command: ' + repr(command))

    def state(self):
        return module._state(self.args.state_root, self.gate, False)

    def prepare(self):
        with redirect_stdout(io.StringIO()):
            module.prepare_command(self.args)

    def publish(self):
        with redirect_stdout(io.StringIO()):
            module.publish_command(self.args)

    def test_failed_or_waiting_gate_never_builds_or_authenticates(self):
        for status in ('WAITING', 'FAILED'):
            self.gate['status'] = status
            module._json(self.gate_path, self.gate)
            with self.assertRaises(module.ReleaseError):
                self.prepare()
            with self.assertRaises(module.ReleaseError):
                self.publish()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.auth_calls, 0)
        self.assertFalse((self.output / 'release.json').exists())

    def test_new_failed_attempt_after_gate_blocks_all_external_mutation(self):
        self.selected.side_effect = lambda *_: {**self.gate, 'status': 'FAILED'}
        with self.assertRaises(module.ReleaseError):
            self.prepare()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.auth_calls, 0)

    def test_prepare_persists_pointer_before_build_and_reuses_passed_candidate(self):
        self.prepare()
        path, state = self.state()
        preview = state['preview']
        self.assertEqual(len(self.commands), 1)
        self.prepare()
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.state()[1]['preview'], preview)
        self.assertEqual(module.read_json(self.output / 'preparation.json')['mode'], 'publish')
        self.assertEqual(self.auth_calls, 0)
        self.assertFalse((self.output / 'release.json').exists())

    def test_failed_preview_is_cleaned_and_preserved_before_fresh_attempt(self):
        path, state = module._state(self.args.state_root, self.gate, True)
        state['preview'] = 'preview-' + '1' * 32
        module._json(path / 'state.json', state)
        previous = path / state['preview']
        previous.mkdir()
        module._json(previous / 'preview-state.json', {'test_only': True})
        self.prepare()
        self.assertIn('--cleanup', self.commands[0])
        self.assertNotIn('--cleanup', self.commands[1])
        self.assertTrue(previous.exists())
        self.assertNotEqual(self.state()[1]['preview'], previous.name)

    def test_failed_preparation_keeps_safe_summary_and_state_pointer(self):
        def failed_preview(command, **kwargs):
            preview = Path(command[command.index('--output') + 1])
            self.write_preview(preview)
            module._json(preview / 'results/preview-summary.json', {'status': 'failed', 'cleanup': 'passed'})
            (preview / 'results/private.log').write_text('must not be archived')
            raise module.ReleaseError('Fake preview failure')
        self.process.side_effect = failed_preview
        with self.assertRaises(module.ReleaseError):
            self.prepare()
        state = module.read_json(self.output / 'preparation-state.json')
        self.assertEqual(Path(state['state_path']), self.state()[0])
        self.assertEqual(Path(state['preview_path']).name, self.state()[1]['preview'])
        self.assertEqual(module.read_json(self.output / 'preview-summary.json')['status'], 'failed')
        self.assertFalse((self.output / 'private.log').exists())
        self.assertFalse((self.output / 'release.json').exists())
        self.assertEqual(self.auth_calls, 0)

    def test_partial_publication_cannot_rebuild_missing_candidate(self):
        self.prepare()
        path, state = self.state()
        state['publish_attempts'] = ['publish-' + '2' * 32]
        module._json(path / 'state.json', state)
        (path / state['preview'] / 'candidate.json').unlink()
        count = len(self.commands)
        with self.assertRaisesRegex(module.ReleaseError, 'publication was attempted'):
            self.prepare()
        self.assertEqual(len(self.commands), count)
        self.assertEqual(self.auth_calls, 0)

    def test_partial_failure_keeps_same_candidate_and_never_exports_release(self):
        self.prepare()
        path, before = self.state()
        original = self.process.side_effect
        def failed(command, **kwargs):
            if Path(str(command[2])).name == 'publish.py':
                out = Path(command[command.index('--output') + 1])
                out.mkdir()
                module._json(out / 'publication_report.json', {'status': 'failed', 'services': {'api': 'pushed'}})
                raise module.ReleaseError('Fake partial push failure')
            return original(command, **kwargs)
        self.process.side_effect = failed
        with self.assertRaises(module.ReleaseError):
            self.publish()
        self.assertFalse(self.auth_open)
        self.assertFalse((self.output / 'release.json').exists())
        self.assertFalse((path / 'release.json').exists())
        after = self.state()[1]
        self.assertEqual(after['preview'], before['preview'])
        self.assertEqual(len(after['publish_attempts']), 1)
        self.prepare()  # Passed candidate is still reused; no retag/rebuild.
        self.assertEqual(self.state()[1]['preview'], before['preview'])

    def test_success_exports_byte_identical_release_without_private_logs(self):
        self.prepare()
        self.publish()
        path, state = self.state()
        self.assertEqual((path / 'release.json').read_bytes(), (self.output / 'release.json').read_bytes())
        self.assertEqual(self.auth_calls, 1)
        self.assertEqual(len(self.registry_calls), 4)
        self.assertFalse((self.output / 'logs').exists())
        self.assertFalse((self.output / 'doctor-test.env').exists())
        self.assertFalse((self.output / 'config.json').exists())
        self.assertEqual(module.load_release(self.output / 'release.json')['source']['commit'], SHA)

    def test_completed_release_reuse_requires_no_auth_or_rebuild(self):
        self.prepare()
        self.publish()
        before_commands = len(self.commands)
        before_auth = self.auth_calls
        self.args.output = self.root / 'retry-artifacts'
        self.prepare()
        self.assertEqual(module.read_json(self.args.output / 'preparation.json')['mode'], 'reuse')
        self.publish()
        self.assertEqual(len(self.commands), before_commands)
        self.assertEqual(self.auth_calls, before_auth)
        self.assertTrue((self.args.output / 'release.json').is_file())
        self.assertEqual(len(self.registry_calls), 12)

    def test_auth_cleanup_failure_blocks_success_artifact(self):
        self.prepare()
        @contextmanager
        def failed_cleanup(*_):
            self.auth_open = True
            try:
                yield {'SAFE_CHILD_ENV': 'true'}
            finally:
                self.auth_open = False
                raise RuntimeError('Fake secret cleanup failure')
        with mock.patch.object(module, '_auth_session', side_effect=failed_cleanup):
            with self.assertRaises(RuntimeError):
                self.publish()
        self.assertFalse((self.output / 'release.json').exists())
        self.assertFalse((self.state()[0] / 'release.json').exists())

    def test_ci_changed_during_upload_blocks_final_handoff(self):
        self.prepare()
        original = self.process.side_effect
        def changed(command, **kwargs):
            value = original(command, **kwargs)
            if Path(str(command[2])).name == 'publish.py':
                self.selected.side_effect = lambda *_: {**self.gate, 'status': 'WAITING'}
            return value
        self.process.side_effect = changed
        with self.assertRaises(module.ReleaseError):
            self.publish()
        self.assertFalse((self.output / 'release.json').exists())
        self.assertFalse((self.state()[0] / 'release.json').exists())

    def test_cleanup_always_removes_owned_auth_sessions_even_without_gate(self):
        self.args.gate = self.root / 'missing-gate.json'
        self.args.output = None
        with mock.patch.object(module, '_auth_cleanup', return_value=1) as cleaned, redirect_stdout(io.StringIO()):
            module.cleanup_command(self.args)
        cleaned.assert_called_once_with(self.args.auth_scratch)
        self.assertEqual(self.commands, [])

    def test_cleanup_error_still_invokes_auth_cleanup(self):
        self.prepare()
        self.args.output = None
        with mock.patch.object(module, '_clean_preview', side_effect=module.ReleaseError('failed')):
            with mock.patch.object(module, '_auth_cleanup', return_value=0) as cleaned, redirect_stdout(io.StringIO()):
                with self.assertRaises(module.ReleaseError):
                    module.cleanup_command(self.args)
        cleaned.assert_called_once_with(self.args.auth_scratch)

    def test_auth_is_removed_before_potentially_blocking_preview_cleanup(self):
        self.prepare()
        self.args.output = None
        events = []
        def auth_cleanup(_):
            events.append('auth-removed')
            return 1
        def preview_cleanup(*_):
            self.assertEqual(events, ['auth-removed'])
            events.append('preview-started')
            raise TimeoutError('Fake Docker cleanup timeout')
        with mock.patch.object(module, '_auth_cleanup', side_effect=auth_cleanup):
            with mock.patch.object(module, '_clean_preview', side_effect=preview_cleanup), redirect_stdout(io.StringIO()):
                with self.assertRaises(TimeoutError):
                    module.cleanup_command(self.args)
        self.assertEqual(events, ['auth-removed', 'preview-started'])

    def test_unowned_state_root_and_output_inside_git_are_refused(self):
        self.args.state_root.mkdir()
        sentinel = self.args.state_root / 'other.txt'
        sentinel.write_text('keep me')
        with self.assertRaises(module.ReleaseError):
            self.prepare()
        self.assertEqual(sentinel.read_text(), 'keep me')
        with self.assertRaises(module.ReleaseError):
            module._output(module.REPO / 'forbidden-artifacts')
        self.assertEqual(self.commands, [])

    def test_manual_empty_causes_are_supported_and_nonready_gate_has_no_mutations(self):
        output = self.root / 'manual-gate'
        causes = self.root / 'causes.json'
        causes.write_text('[]')
        self.selected.side_effect = lambda *_: {**self.gate, 'status': 'WAITING', 'builds': {}}
        with redirect_stdout(io.StringIO()):
            code = module.main(['gate', '--jenkins-home', str(self.args.jenkins_home), '--commit', SHA,
                                '--output', str(output), '--causes', str(causes)])
        self.assertEqual(code, 0)
        self.assertIn('status=WAITING', (output / 'gate.properties').read_text())
        self.assertEqual(self.commands, [])
        self.assertEqual(self.auth_calls, 0)

    def test_malformed_causes_fail_without_success_release(self):
        output = self.root / 'bad-gate'
        causes = self.root / 'causes.json'
        causes.write_text('{}')
        with redirect_stderr(io.StringIO()):
            code = module.main(['gate', '--jenkins-home', str(self.args.jenkins_home), '--commit', SHA,
                                '--output', str(output), '--causes', str(causes)])
        self.assertEqual(code, 1)
        self.assertFalse((output / 'release.json').exists())
        self.assertEqual(self.commands, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)