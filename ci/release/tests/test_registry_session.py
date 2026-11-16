"""No real credentials, Docker commands, or network calls are used."""
import importlib.util
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    'release_registry_session', Path(__file__).resolve().parents[1] / 'registry_session.py')
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)
TOKEN = 'fake-ci-token-never-log'
HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'


class RegistrySessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='registry-session-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.scratch = self.root / 'scratch'
        self.env = {'DOCKERHUB_USERNAME': 'rlarns982', 'DOCKERHUB_TOKEN': TOKEN,
                    'DOCKER_CONFIG': str(self.root / 'existing-config'),
                    'DOCKER_AUTH_CONFIG': 'sensitive-existing-auth',
                    'PATH': 'test-path', 'DOCKER_CONTEXT': 'desktop-linux'}
        self.calls = []
        self.configs = []

    def fake_login(self, command, **kwargs):
        self.calls.append((command, kwargs))
        config = Path(command[2])
        self.configs.append(config)
        (config / 'config.json').write_text('sensitive-fake-auth', encoding='utf-8')
        return subprocess.CompletedProcess(command, 0, 'Login Succeeded', '')

    def test_success_uses_stdin_isolated_config_and_credential_free_environment(self):
        old = Path(self.env['DOCKER_CONFIG'])
        old.mkdir()
        marker = old / 'config.json'
        marker.write_text('preserve-this-existing-config', encoding='utf-8')
        with session.authenticated_registry('docker', self.scratch, runner=self.fake_login,
                                            environ=self.env, docker_host=HOST) as child:
            command, kwargs = self.calls[0]
            self.assertEqual(command[3:], ['login', '--username', 'rlarns982',
                                          '--password-stdin', 'docker.io'])
            self.assertNotIn(TOKEN, str(command))
            self.assertEqual(kwargs['input'], TOKEN + '\n')
            self.assertEqual(kwargs['timeout'], 60)
            self.assertFalse(kwargs['check'])
            self.assertEqual(child['DOCKER_CONFIG'], command[2])
            self.assertEqual(child['DOCKER_HOST'], HOST)
            self.assertNotIn('DOCKER_CONTEXT', child)
            for key in ('DOCKERHUB_TOKEN', 'DOCKERHUB_USERNAME', 'DOCKER_AUTH_CONFIG'):
                self.assertNotIn(key, child)
                self.assertNotIn(key, kwargs['env'])
            self.assertTrue(self.configs[0].is_dir())
            self.assertNotEqual(child['DOCKER_CONFIG'], self.env['DOCKER_CONFIG'])
        self.assertFalse(self.configs[0].exists())
        self.assertTrue(self.scratch.is_dir())
        self.assertEqual(marker.read_text(), 'preserve-this-existing-config')
        self.assertEqual(self.env['DOCKERHUB_TOKEN'], TOKEN)

    def test_existing_explicit_host_avoids_saved_context_dependency(self):
        self.env['DOCKER_HOST'] = HOST
        with session.authenticated_registry('docker', self.scratch, runner=self.fake_login,
                                            environ=self.env) as child:
            self.assertEqual(child['DOCKER_HOST'], HOST)
            self.assertNotIn('DOCKER_CONTEXT', child)

    def test_no_explicit_host_preserves_requested_engine_selection(self):
        with session.authenticated_registry('docker', self.scratch, runner=self.fake_login,
                                            environ=self.env) as child:
            self.assertEqual(child['DOCKER_CONTEXT'], 'desktop-linux')

    def test_login_failure_output_is_not_exposed_and_temp_auth_is_removed(self):
        def failing(command, **kwargs):
            self.fake_login(command, **kwargs)
            return subprocess.CompletedProcess(command, 1, TOKEN, TOKEN)
        with self.assertRaises(session.RegistrySessionError) as raised:
            with session.authenticated_registry('docker', self.scratch, runner=failing,
                                                environ=self.env):
                self.fail('Failed login must not yield')
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertFalse(self.configs[0].exists())

    def test_runner_exception_cannot_disclose_token(self):
        def failing(command, **kwargs):
            self.fake_login(command, **kwargs)
            raise RuntimeError(TOKEN)
        with self.assertRaises(session.RegistrySessionError) as raised:
            with session.authenticated_registry('docker', self.scratch, runner=failing,
                                                environ=self.env):
                self.fail('Failed runner must not yield')
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertFalse(self.configs[0].exists())

    def test_runner_error_of_helper_type_is_still_sanitized(self):
        def failing(command, **kwargs):
            self.fake_login(command, **kwargs)
            raise session.RegistrySessionError(TOKEN)
        with self.assertRaises(session.RegistrySessionError) as raised:
            with session.authenticated_registry('docker', self.scratch, runner=failing,
                                                environ=self.env):
                self.fail('Failed runner must not yield')
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertFalse(self.configs[0].exists())

    def test_timeout_removes_auth_and_hides_command_output(self):
        def timeout(command, **kwargs):
            self.fake_login(command, **kwargs)
            raise subprocess.TimeoutExpired(command, 60, output=TOKEN, stderr=TOKEN)
        with self.assertRaises(session.RegistrySessionError) as raised:
            with session.authenticated_registry('docker', self.scratch, runner=timeout,
                                                environ=self.env):
                self.fail('Timed out login must not yield')
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertFalse(self.configs[0].exists())

    def test_consumer_failure_still_removes_only_its_own_config(self):
        with self.assertRaisesRegex(ValueError, 'publication failed'):
            with session.authenticated_registry('docker', self.scratch, runner=self.fake_login,
                                                environ=self.env):
                raise ValueError('publication failed')
        self.assertFalse(self.configs[0].exists())
        self.assertTrue(self.scratch.exists())

    def test_wrong_account_or_missing_token_fails_before_creating_config(self):
        for changes in ({'DOCKERHUB_USERNAME': 'other'}, {'DOCKERHUB_TOKEN': ''},
                        {'DOCKERHUB_TOKEN': ' '}, {'DOCKERHUB_TOKEN': 'fake\nsecond-line'}):
            with self.subTest(changes=list(changes)):
                with self.assertRaises(session.RegistrySessionError):
                    with session.authenticated_registry('docker', self.scratch,
                            runner=self.fake_login, environ={**self.env, **changes}):
                        self.fail('Invalid credential accepted')
        self.assertEqual(self.calls, [])
        self.assertFalse(self.scratch.exists())

    def test_relative_scratch_is_refused_before_login(self):
        with self.assertRaises(session.RegistrySessionError):
            with session.authenticated_registry('docker', 'relative-scratch',
                    runner=self.fake_login, environ=self.env):
                self.fail('Relative scratch accepted')
        self.assertEqual(self.calls, [])

    def test_scratch_inside_git_checkout_is_refused(self):
        (self.root / '.git').write_text('gitdir: fake', encoding='utf-8')
        with self.assertRaises(session.RegistrySessionError):
            with session.authenticated_registry('docker', self.scratch,
                    runner=self.fake_login, environ=self.env):
                self.fail('Git checkout used for secrets')
        self.assertEqual(self.calls, [])

    def test_cleanup_refuses_a_directory_outside_owned_scratch(self):
        self.scratch.mkdir()
        outside = self.root / 'docker-auth-unrelated'
        outside.mkdir()
        marker = outside / 'preserve.txt'
        marker.write_text('keep', encoding='utf-8')
        with self.assertRaises(session.RegistrySessionError):
            session._safe_cleanup(outside, self.scratch)
        self.assertEqual(marker.read_text(), 'keep')

    def make_leftover(self, name='docker-auth-leftover'):
        self.scratch.mkdir(exist_ok=True)
        directory = self.scratch / name
        directory.mkdir()
        (directory / session.MARKER).write_bytes(session._owner_bytes(directory, self.scratch))
        (directory / 'config.json').write_text('fake-sensitive-auth', encoding='utf-8')
        return directory

    def test_recovery_of_missing_scratch_is_a_noop(self):
        self.assertEqual(session.cleanup_registry_sessions(self.scratch), 0)
        self.assertFalse(self.scratch.exists())

    def test_recovery_reads_only_markers_and_preserves_unrelated_names(self):
        directory = self.make_leftover()
        unrelated = self.scratch / 'other-output'
        unrelated.mkdir()
        marker = unrelated / 'keep.txt'
        marker.write_text('preserve', encoding='utf-8')
        original_read = Path.read_bytes
        def guarded_read(path):
            self.assertEqual(path.name, session.MARKER, 'Recovery read credential contents')
            return original_read(path)
        with patch.object(Path, 'read_bytes', guarded_read):
            self.assertEqual(session.cleanup_registry_sessions(self.scratch), 1)
        self.assertFalse(directory.exists())
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertTrue(self.scratch.is_dir())

    def test_foreign_matching_directory_blocks_recovery_before_any_deletion(self):
        owned = self.make_leftover()
        foreign = self.scratch / 'docker-auth-foreign'
        foreign.mkdir()
        (foreign / 'config.json').write_text('leave-alone', encoding='utf-8')
        with self.assertRaises(session.RegistrySessionError):
            session.cleanup_registry_sessions(self.scratch)
        self.assertTrue(owned.exists())
        self.assertEqual((foreign / 'config.json').read_text(), 'leave-alone')

    def test_tampered_owner_marker_blocks_recovery(self):
        owned = self.make_leftover()
        (owned / session.MARKER).write_text('wrong-owner', encoding='utf-8')
        with self.assertRaises(session.RegistrySessionError):
            session.cleanup_registry_sessions(self.scratch)
        self.assertTrue(owned.exists())

    def test_redirected_auth_directory_is_never_deleted(self):
        owned = self.make_leftover()
        original = session._linked
        with patch.object(session, '_linked', side_effect=lambda p: Path(p) == owned or original(p)):
            with self.assertRaises(session.RegistrySessionError):
                session.cleanup_registry_sessions(self.scratch)
        self.assertTrue(owned.exists())

    def test_post_cleanup_recovers_config_after_process_exits_without_finally(self):
        code = """
import importlib.util, os, pathlib, subprocess, sys
spec=importlib.util.spec_from_file_location('session',sys.argv[1])
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
def fake(command,**kwargs):
    (pathlib.Path(command[2])/'config.json').write_text('fake-auth',encoding='utf-8')
    return subprocess.CompletedProcess(command,0,'','')
with s.authenticated_registry('docker',sys.argv[2],runner=fake,
    environ={'DOCKERHUB_USERNAME':'rlarns982','DOCKERHUB_TOKEN':'fake-token'}):
    os._exit(0)
"""
        result = subprocess.run([sys.executable, '-B', '-c', code, SPEC.origin, str(self.scratch)],
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        leftovers = list(self.scratch.glob('docker-auth-*'))
        self.assertEqual(len(leftovers), 1)
        self.assertTrue((leftovers[0] / 'config.json').exists())
        self.assertEqual(session.cleanup_registry_sessions(self.scratch), 1)
        self.assertFalse(leftovers[0].exists())

    def test_separate_sessions_use_distinct_configs(self):
        for _ in range(2):
            with session.authenticated_registry('docker', self.scratch,
                    runner=self.fake_login, environ=self.env):
                pass
        self.assertNotEqual(*self.configs)
        self.assertTrue(all(not path.exists() for path in self.configs))


if __name__ == '__main__':
    unittest.main()