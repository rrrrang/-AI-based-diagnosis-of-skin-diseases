"""Isolated Docker Hub login for an already-approved Jenkins publication.

Only credentials bound into this process are used. Existing Docker or Jenkins
credential stores are never opened, copied, or changed.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

USERNAME = 'rlarns982'
OWNER = 'skinai-registry-session/v1'
MARKER = '.skinai-docker-auth-owner.json'
SECRET_ENV_NAMES = frozenset({
    'DOCKERHUB_USERNAME', 'DOCKERHUB_TOKEN', 'DOCKER_AUTH_CONFIG',
    'DOCKER_PASSWORD', 'DOCKERHUB_PASSWORD',
})


class RegistrySessionError(RuntimeError):
    """Safe diagnostics that do not contain login output or credential values."""


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _validate_scratch(value, *, create=True):
    root = Path(value)
    if not root.is_absolute() or root == Path(root.anchor):
        raise RegistrySessionError('Docker login scratch must be an absolute task folder')
    for item in (root, *root.parents):
        if _linked(item):
            raise RegistrySessionError('Docker login scratch must not use redirected paths')
        if (item / '.git').exists():
            raise RegistrySessionError('Docker login scratch must be outside Git checkouts')
    if root.exists() and not root.is_dir():
        raise RegistrySessionError('Docker login scratch must be a directory')
    if create:
        root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve(strict=create or root.exists())
    if resolved != root or _linked(root):
        raise RegistrySessionError('Docker login scratch changed while being prepared')
    return resolved


def _owner_bytes(directory, root):
    return (json.dumps({'owner': OWNER, 'directory': directory.name,
                        'scratch_root': str(root)}, sort_keys=True) + '\n').encode('utf-8')


def _validate_owned_directory(directory, root):
    directory, root = Path(directory), Path(root)
    if (not directory.is_absolute() or not root.is_absolute()
            or directory.parent != root or not directory.name.startswith('docker-auth-')
            or not directory.is_dir() or _linked(directory) or _linked(root)
            or directory.resolve(strict=True) != directory
            or root.resolve(strict=True) != root
            or directory.resolve(strict=True).parent != root):
        raise RegistrySessionError('Temporary Docker login path changed; cleanup refused')
    for ancestor in root.parents:
        if _linked(ancestor):
            raise RegistrySessionError('Temporary Docker login parent changed; cleanup refused')
    marker = directory / MARKER
    expected = _owner_bytes(directory, root)
    if (_linked(marker) or not marker.is_file()
            or marker.stat().st_size != len(expected)
            or marker.read_bytes() != expected):
        raise RegistrySessionError('Temporary Docker login owner is missing or different; cleanup refused')


def _safe_cleanup(directory, root):
    """Delete only an exact marked direct child created by this session."""
    directory, root = Path(directory), Path(root)
    try:
        if not directory.exists() and not _linked(directory):
            return
        _validate_owned_directory(directory, root)
        shutil.rmtree(directory)
    except RegistrySessionError:
        raise
    except OSError:
        raise RegistrySessionError('Temporary Docker credentials could not be removed') from None


def cleanup_registry_sessions(scratch_root):
    """Recover marked sessions after Jenkins kills a process; return removed count.

    No config.json is read. A missing scratch folder is a no-op. All matching
    children must prove ownership before any child is removed; unrelated names
    are preserved. Call only for this build's private scratch, after its process
    has stopped, never for another running build's scratch.
    """
    try:
        root = _validate_scratch(scratch_root, create=False)
        if not root.exists():
            return 0
        sessions = sorted(path for path in root.iterdir()
                          if path.name.startswith('docker-auth-'))
        for directory in sessions:
            _validate_owned_directory(directory, root)
        for directory in sessions:
            _safe_cleanup(directory, root)
        return len(sessions)
    except RegistrySessionError:
        raise
    except OSError:
        raise RegistrySessionError('Temporary Docker login recovery did not complete') from None


@contextmanager
def authenticated_registry(docker, scratch_root, *, runner=None, environ=None, docker_host=None):
    """Yield a credential-free child environment with a temporary DOCKER_CONFIG.

    The Docker auth file exists only during this context. The consumer should
    pass the yielded environment explicitly to the publication subprocess.
    A supplied DOCKER_HOST clears DOCKER_CONTEXT so no saved context is needed.
    `runner`/`environ` support tests without Docker, network, or real secrets.
    """
    child_env = dict(os.environ if environ is None else environ)
    username = child_env.get('DOCKERHUB_USERNAME')
    token = child_env.get('DOCKERHUB_TOKEN')
    if username != USERNAME:
        raise RegistrySessionError('Bind the approved Docker Hub account in Jenkins')
    if (not isinstance(token, str) or not token or len(token) > 8192
            or any(c.isspace() or c == '\x00' for c in token)):
        raise RegistrySessionError('Bind a nonempty Docker Hub token in Jenkins')
    executable = os.fspath(docker)
    if not executable or '\x00' in executable:
        raise RegistrySessionError('A Docker executable is required')
    for key in list(child_env):
        if key.upper() in SECRET_ENV_NAMES or key.upper() == 'DOCKER_CONFIG':
            del child_env[key]
    host = docker_host if docker_host is not None else child_env.get('DOCKER_HOST')
    if host is not None:
        if (not isinstance(host, str) or not host or '\x00' in host
                or '\r' in host or '\n' in host):
            raise RegistrySessionError('Invalid Docker engine endpoint')
        child_env['DOCKER_HOST'] = host
        for key in list(child_env):
            if key.upper() == 'DOCKER_CONTEXT':
                del child_env[key]
    root = _validate_scratch(scratch_root)
    directory = Path(tempfile.mkdtemp(prefix='docker-auth-', dir=root))
    try:
        (directory / MARKER).write_bytes(_owner_bytes(directory, root))
    except OSError:
        # Login has not run, and this newly created directory is still empty.
        if directory.resolve(strict=True).parent == root and not _linked(directory):
            directory.rmdir()
        raise RegistrySessionError('Unable to initialize temporary Docker login ownership') from None
    child_env['DOCKER_CONFIG'] = str(directory)
    command = [executable, '--config', str(directory), 'login',
               '--username', USERNAME, '--password-stdin', 'docker.io']
    invoke = subprocess.run if runner is None else runner
    try:
        try:
            result = invoke(command, input=token + '\n', text=True, encoding='utf-8',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=child_env.copy(), timeout=60, check=False)
        except Exception:
            # Raw exceptions and login output may echo credentials. Do not chain.
            raise RegistrySessionError('Docker Hub login did not complete') from None
        finally:
            token = None
        if result.returncode != 0:
            raise RegistrySessionError('Docker Hub login failed; check the bound Jenkins credential')
        yield child_env.copy()
    finally:
        _safe_cleanup(directory, root)