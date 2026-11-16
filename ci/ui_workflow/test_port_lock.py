"""Real subprocess contention checks; no Jenkins, Docker, or network access."""
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from port_lock import PortLockError, PortLockTimeout, configured_lock_path, port_lock, run_locked

MODULE_DIR = str(Path(__file__).resolve().parent)
CHILD = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from port_lock import port_lock, PortLockTimeout
try:
    with port_lock(Path(sys.argv[2]), timeout=float(sys.argv[4]), poll_interval=0.02):
        print('CHILD_ACQUIRED', flush=True)
        if sys.argv[3] == 'hold':
            sys.stdin.readline()
except PortLockTimeout:
    print('CHILD_TIMED_OUT', flush=True)
    sys.exit(7)
'''


class PortLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='skinai-port-lock-test-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'shared.lock'

    def command(self, mode='probe', timeout=1):
        return [sys.executable, '-B', '-c', CHILD, MODULE_DIR, str(self.path), mode, str(timeout)]

    def probe(self, timeout=1):
        return subprocess.run(self.command(timeout=timeout), capture_output=True,
                              text=True, encoding='utf-8', timeout=5)

    def holder(self):
        process = subprocess.Popen(self.command('hold', 2), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        self.addCleanup(self.stop, process)
        while True:
            line = process.stdout.readline()
            if line.strip() == 'CHILD_ACQUIRED':
                break
            if not line:
                self.fail('Holder did not acquire the lock: ' + process.stderr.read())
        return process

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def test_competing_process_times_out_without_entering_protected_region(self):
        with port_lock(self.path, timeout=0):
            result = self.probe(timeout=0.15)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn('CHILD_TIMED_OUT', result.stdout)
        self.assertNotIn('CHILD_ACQUIRED', result.stdout)

    def test_waiter_acquires_after_owner_releases(self):
        holder = self.holder()
        waiter = subprocess.Popen(self.command(timeout=2), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.addCleanup(self.stop, waiter)
        time.sleep(0.15)
        self.assertIsNone(waiter.poll(), 'Waiter must remain excluded while holder is alive')
        holder.communicate(input='release\n', timeout=5)
        out, err = waiter.communicate(timeout=5)
        self.assertEqual(waiter.returncode, 0, err)
        self.assertIn('CHILD_ACQUIRED', out)

    def test_killing_owner_releases_os_lock_without_deleting_file(self):
        holder = self.holder()
        inode = self.path.stat().st_ino
        holder.kill()
        holder.communicate(timeout=5)
        result = self.probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CHILD_ACQUIRED', result.stdout)
        self.assertEqual(self.path.stat().st_ino, inode)

    def test_exception_in_protected_work_releases_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic work failure'):
            with port_lock(self.path, timeout=0):
                raise RuntimeError('synthetic work failure')
        result = self.probe()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_lock_file_is_preserved_across_runs(self):
        with port_lock(self.path, timeout=0):
            first = self.path.stat().st_ino
        with port_lock(self.path, timeout=0):
            self.assertEqual(first, self.path.stat().st_ino)
        self.assertTrue(self.path.is_file())

    def test_environment_override_is_shared_and_independent_of_temp_folder(self):
        with patch.dict(os.environ, {'CI_WORKFLOW_LOCK': str(self.path), 'TEMP': 'ignored-per-run-temp'}):
            self.assertEqual(configured_lock_path(), self.path)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run_locked(lambda: 23), 23)
        self.assertTrue(self.path.is_file())

    def test_both_cli_entrypoints_share_the_lock_before_their_arguments_run(self):
        module = Path(MODULE_DIR)
        entrypoints = [module / 'run_workflow.py', module.parent / 'release/prepare_preview.py']
        env = dict(os.environ, CI_WORKFLOW_LOCK=str(self.path))
        for entrypoint in entrypoints:
            with self.subTest(entrypoint=entrypoint.name):
                with port_lock(self.path, timeout=0):
                    with self.assertRaises(subprocess.TimeoutExpired):
                        subprocess.run([sys.executable, '-B', str(entrypoint), '--help'],
                                       env=env, capture_output=True, timeout=0.35)
                result = subprocess.run([sys.executable, '-B', str(entrypoint), '--help'],
                                        env=env, capture_output=True, text=True,
                                        encoding='utf-8', timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('WORKFLOW_PORT_LOCK_ACQUIRED', result.stdout)
                self.assertIn('WORKFLOW_PORT_LOCK_RELEASED', result.stdout)

    def test_invalid_path_or_wait_is_rejected_before_work(self):
        for path in [Path('relative.lock'), self.path.with_suffix('.txt')]:
            with self.subTest(path=path), self.assertRaises(PortLockError):
                with port_lock(path, timeout=0):
                    self.fail('Unsafe lock path was used')
        for timeout in [-1, 901, True, float('nan')]:
            with self.subTest(timeout=timeout), self.assertRaises(PortLockError):
                with port_lock(self.path, timeout=timeout):
                    self.fail('Invalid lock wait was used')


if __name__ == '__main__':
    unittest.main()