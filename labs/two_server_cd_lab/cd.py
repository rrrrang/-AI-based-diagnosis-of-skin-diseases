"""Local two-service CD lab. Run without arguments to validate only."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parent


def state_directory():
    # Jenkins가 Git에서 받은 코드로 실행해도 기존 복구 기록은 같은 곳을 사용한다.
    configured = os.environ.get('SKINAI_CD_STATE_DIR')
    if configured is None:
        return ROOT / '.cd-state'  # 기존 수동 실행 방법도 유지한다.
    directory = Path(configured)
    if not configured.strip() or not directory.is_absolute():
        raise ValueError('SKINAI_CD_STATE_DIR must be an absolute path')
    if not directory.is_dir() or not (directory / 'state.json').is_file():
        raise ValueError('Existing CD recovery state.json was not found; deployment stopped')
    return directory.resolve()


STATE = state_directory()
PROJECT = 'skinai-cd-lab'
BASE_URL = 'http://127.0.0.1:18130'
SERVICES = {'central', 'ai-mock'}


def run(command, capture=False, timeout=300):
    result = subprocess.run(command, capture_output=capture, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {command}'
                           + (f'\n{result.stderr}' if capture else ''))
    return result.stdout if capture else None


def compose(path, *args, capture=False):
    return run(['docker', 'compose', '--project-name', PROJECT,
                '-f', str(path), *args], capture=capture)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate(release_path, compose_path):
    release = read_json(release_path)
    compose_text = compose_path.read_text(encoding='utf-8-sig')
    config = yaml.safe_load(compose_text)
    if '$' in compose_text or set(config) - {'name', 'services'}:
        raise ValueError('This lab requires a self-contained Compose without variable substitution')
    if release['ci']['result'] != 'SUCCESS':
        raise ValueError('CI must be SUCCESS')
    if release.get('practice_only') is not True or release.get('model_loaded') is not False:
        raise ValueError('This runner supports the mock lab release only')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', release['release_id']):
        raise ValueError('Invalid release_id')
    if release['platform'] != 'linux/amd64' or config.get('name') != PROJECT:
        raise ValueError('Expected linux/amd64 and skinai-cd-lab')
    if set(release['services']) != SERVICES or set(config['services']) != SERVICES:
        raise ValueError('Expected central and ai-mock only')
    for name in sorted(SERVICES):
        item = release['services'][name]
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', item['digest']):
            raise ValueError(f'{name}: invalid digest')
        expected = item['repository'] + '@' + item['digest']
        actual = config['services'][name]
        if set(actual) - {'image', 'platform', 'ports', 'depends_on', 'restart'}:
            raise ValueError(f'{name}: unsupported Compose fields; review snapshot contract first')
        if item['image'] != expected or actual['image'] != expected:
            raise ValueError(f'{name}: image mismatch')
        if actual.get('platform') != release['platform']:
            raise ValueError(f'{name}: platform mismatch')
    rendered = json.loads(compose(compose_path, 'config', '--format', 'json', capture=True))
    if set(rendered['services']) != SERVICES:
        raise ValueError('Rendered Compose services mismatch')
    for name in SERVICES:
        if rendered['services'][name]['image'] != release['services'][name]['image']:
            raise ValueError('Rendered image mismatch')
    ports = rendered['services']['central'].get('ports', [])
    if len(ports) != 1 or ports[0].get('host_ip') != '127.0.0.1' or str(ports[0].get('published')) != '18130' or ports[0].get('target') != 8000:
        raise ValueError('Expected central port 127.0.0.1:18130:8000')
    if rendered['services']['ai-mock'].get('ports'):
        raise ValueError('ai-mock must be internal')
    print(f"Release and Compose checks passed: {release['release_id']}", flush=True)
    return release


def smoke(timeout=45):
    sample = {'sample_id': 'cd-smoke-001', 'sample_text': 'CD integration smoke test'}
    deadline = time.monotonic() + timeout
    last_error = ''
    while time.monotonic() < deadline:
        try:
            with urlopen(BASE_URL + '/health', timeout=3) as response:
                health = json.load(response)
            if health.get('status') != 'ok' or health.get('service') != 'central':
                raise ValueError('Unexpected central health response')
            request = Request(BASE_URL + '/analyze', data=json.dumps(sample).encode(),
                              headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=5) as response:
                if response.status != 200:
                    raise ValueError('Unexpected HTTP status')
                result = json.load(response)
            ai = result.get('ai_response', {})
            if result.get('service') != 'central' or ai.get('service') != 'ai-mock' or ai.get('status') != 'ok' or ai.get('received') != sample or ai.get('practice_only') is not True or ai.get('model_loaded') is not False:
                raise ValueError('Unexpected mock response or round-trip data')
            print('Smoke passed: central -> ai-mock -> central', flush=True)
            return
        except (URLError, TimeoutError, ValueError) as error:
            last_error = str(error)
            time.sleep(1)
    raise RuntimeError(f'Smoke timed out: {last_error}')


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def deployment_lock():
    STATE.mkdir(exist_ok=True)
    path = STATE / 'deploy.lock'
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError('CD is locked. Check running deployment before removing .cd-state/deploy.lock') from None
    try:
        with os.fdopen(descriptor, 'w') as file:
            file.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def snapshot(release_path, compose_path):
    rb, cb = release_path.read_bytes(), compose_path.read_bytes()
    key = hashlib.sha256(rb + b'\0' + cb).hexdigest()
    folder = STATE / 'releases' / key
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in [('release.json', rb), ('compose.cd.yaml', cb)]:
        destination = folder / name
        if destination.exists() and destination.read_bytes() != value:
            raise ValueError('Snapshot content mismatch')
        destination.write_bytes(value)
    return key, folder


def deploy(release_path, compose_path):
    release = validate(release_path, compose_path)
    key, folder = snapshot(release_path, compose_path)
    manifest = folder / 'compose.cd.yaml'
    record_path = STATE / 'state.json'
    state = read_json(record_path) if record_path.exists() else {}
    write_json(STATE / 'attempt.json', {'target': key, 'status': 'running'})
    try:
        compose(manifest, 'pull')
        compose(manifest, 'up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '90')
        smoke()
    except Exception as error:
        write_json(STATE / 'attempt.json', {'target': key, 'status': 'failed', 'error': str(error)})
        raise
    if state.get('current') != key:
        state['previous'] = state.get('current')
    state.update(current=key, release_id=release['release_id'],
                 updated_at=datetime.now(timezone.utc).isoformat())
    write_json(record_path, state)
    write_json(STATE / 'attempt.json', {'target': key, 'status': 'success'})
    print(f"Deployment verified: {release['release_id']}")


def active_compose(default):
    record = STATE / 'state.json'
    attempt = STATE / 'attempt.json'
    if attempt.exists():
        key = read_json(attempt)['target']
        return STATE / 'releases' / key / 'compose.cd.yaml'
    if record.exists():
        return STATE / 'releases' / read_json(record)['current'] / 'compose.cd.yaml'
    return default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='check',
                        choices=['check', 'pull', 'up', 'smoke', 'status', 'logs', 'down', 'rollback'])
    parser.add_argument('--release', type=Path, default=ROOT / 'release.json')
    parser.add_argument('--compose', type=Path, default=ROOT / 'compose.cd.yaml')
    args = parser.parse_args()
    try:
        if args.command == 'check':
            validate(args.release, args.compose)
        elif args.command == 'smoke':
            smoke()
        elif args.command in ['status', 'logs']:
            manifest = active_compose(args.compose)
            compose(manifest, *(['ps', '-a'] if args.command == 'status' else ['logs', '--tail', '100']))
            if (STATE / 'state.json').exists():
                print((STATE / 'state.json').read_text(encoding='utf-8'))
        else:
            with deployment_lock():
                if args.command == 'pull':
                    validate(args.release, args.compose)
                    _, folder = snapshot(args.release, args.compose)
                    compose(folder / 'compose.cd.yaml', 'pull')
                elif args.command == 'up':
                    deploy(args.release, args.compose)
                elif args.command == 'down':
                    compose(active_compose(args.compose), 'down', '--timeout', '10')
                else:
                    state = read_json(STATE / 'state.json')
                    attempt = read_json(STATE / 'attempt.json') if (STATE / 'attempt.json').exists() else {}
                    target = state.get('current') if attempt.get('status') in ['running', 'failed'] else state.get('previous')
                    if not target:
                        raise ValueError('No verified rollback target. First deploy must succeed before recovery is available')
                    folder = STATE / 'releases' / target
                    deploy(folder / 'release.json', folder / 'compose.cd.yaml')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError, yaml.YAMLError) as error:
        print(f'CD failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
