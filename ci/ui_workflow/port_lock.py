"""Serialize the real workflow and packaged-image checks on one host.

The operating system owns the lock until the file handle closes, including when
its process dies. Never delete this file: existing waiters must use one inode.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import sys
import time

DEFAULT_WINDOWS_LOCK = 'D:/SkinAI_DevOps/runlocks/real-workflow.lock'
DEFAULT_POSIX_LOCK = '/tmp/skinai-real-workflow.lock'
DEFAULT_TIMEOUT = 15 * 60


class PortLockError(RuntimeError):
    """No shared test ports were reserved by this process."""


class PortLockTimeout(PortLockError, TimeoutError):
    pass


def configured_lock_path():
    value = os.environ.get('CI_WORKFLOW_LOCK')
    return Path(value or (DEFAULT_WINDOWS_LOCK if os.name == 'nt' else DEFAULT_POSIX_LOCK))


def _physical_path(path):
    if not path.is_absolute() or path.suffix.lower() != '.lock':
        raise PortLockError('CI_WORKFLOW_LOCK must be an absolute .lock file path')
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise PortLockError('Refusing a redirected workflow lock path')
    if path.exists() and not path.is_file():
        raise PortLockError('Workflow lock must be a regular file')


def _try_lock(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def port_lock(path=None, *, timeout=DEFAULT_TIMEOUT, poll_interval=0.25):
    """Reserve the shared UI/API ports before preflight, through final cleanup."""
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or not 0 <= timeout <= DEFAULT_TIMEOUT
            or not isinstance(poll_interval, (int, float)) or isinstance(poll_interval, bool)
            or not 0 < poll_interval <= 5):
        raise PortLockError('Invalid bounded workflow lock wait')
    path = configured_lock_path() if path is None else Path(path)
    fd = None
    acquired = False
    try:
        _physical_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _physical_path(path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_BINARY', 0)
        flags |= getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags, 0o600)
        _physical_path(path)
        actual, opened = path.stat(), os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != (opened.st_dev, opened.st_ino):
            raise PortLockError('Workflow lock path changed during open')
        # Both OS lock APIs can reserve an empty file; never rewrite its bytes.
        deadline = time.monotonic() + timeout
        announced_wait = False
        while True:
            try:
                _try_lock(fd)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PortLockTimeout('Timed out waiting for the shared workflow test ports') from None
                if not announced_wait:
                    print('WORKFLOW_PORT_LOCK_WAITING', flush=True)
                    announced_wait = True
                time.sleep(min(poll_interval, remaining))
    except OSError as exc:
        if fd is not None:
            os.close(fd)
            fd = None
        if isinstance(exc, PortLockError):
            raise
        raise PortLockError('Unable to open or acquire the workflow port lock') from exc
    except BaseException:
        if fd is not None:
            os.close(fd)
            fd = None
        raise
    try:
        if not acquired:
            raise PortLockError('Workflow port lock was not acquired')
        print('WORKFLOW_PORT_LOCK_ACQUIRED', flush=True)
        yield path
    finally:
        if fd is not None:
            # close releases byte locks on Windows and flock locks on POSIX.
            os.close(fd)
        print('WORKFLOW_PORT_LOCK_RELEASED', flush=True)


def run_locked(callback):
    """CLI boundary only; imports and isolated helper tests have no lock side effects."""
    try:
        with port_lock():
            return callback()
    except PortLockError as exc:
        print('WORKFLOW_PORT_LOCK_FAILED:', str(exc), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('WORKFLOW_PORT_LOCK_INTERRUPTED', file=sys.stderr, flush=True)
        return 130