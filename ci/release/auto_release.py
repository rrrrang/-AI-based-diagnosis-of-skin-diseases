"""Controller for the four-image release job; all external effects follow CI gates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'handoff'))
sys.path.insert(0, str(REPO / 'ci/ui_workflow'))
from select_ci_builds import select_builds, resolve_upstream_causes
from collect_ci_evidence import JOBS, BRANCH, COMMIT_RE, positive_build_number
from publish import read_json, validate_gate, file_hash
from provenance import assert_inputs_unchanged
from release import load_release, SOURCE_REPOSITORY
from registry import verify_public_image
from registry_session import RegistrySessionError
from run_workflow import run_process

OWNER = 'SkinAI-Release-CI/v1'
SECRET_NAMES = {'DOCKERHUB_USERNAME', 'DOCKERHUB_TOKEN', 'DOCKER_AUTH_CONFIG',
                'DOCKER_PASSWORD', 'DOCKERHUB_PASSWORD'}
PREVIEW_NAME = re.compile(r'preview-[0-9a-f]{32}')
PUBLISH_NAME = re.compile(r'publish-[0-9a-f]{32}')


class ReleaseError(RuntimeError):
    """Messages are fixed diagnostics, never captured child/login output."""


def _physical(path, outside_git=True):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ReleaseError('Refusing a redirected release path')
        if outside_git and (item / '.git').exists():
            raise ReleaseError('Release state and artifacts must be outside Git checkouts')
    if path.resolve() != path or path == Path(path.anchor):
        raise ReleaseError('Expected a physical task directory')
    return path


def _write(path, data):
    path = _physical(path)
    temp = path.with_name(path.name + '.tmp')
    _physical(temp)
    temp.write_bytes(data)
    temp.replace(path)


def _json(path, value):
    _write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def _props(path, values):
    # Do not feed file-system paths or arbitrary JSON back into shell variables.
    text = ''.join(f'{key}={value}\n' for key, value in values.items())
    _write(path, text.encode('utf-8'))


def _output(path, fresh=False):
    path = _physical(path)
    marker = path / '.release-output-owner.json'
    if fresh and path.exists():
        raise ReleaseError('Gate output must be a fresh directory')
    if path.exists():
        if not marker.is_file() or read_json(marker) != {'owner': OWNER}:
            raise ReleaseError('Artifact directory has no matching owner')
    else:
        path.mkdir(parents=True)
        _json(marker, {'owner': OWNER})
    return path


def _environment():
    return {key: value for key, value in os.environ.items() if key.upper() not in SECRET_NAMES}


def _run(command, timeout=60, env=None):
    result = run_process(command, cwd=REPO, env=_environment() if env is None else env, timeout=timeout)
    if result.returncode:
        raise ReleaseError('Release command failed; inspect the retained preview/publication report')
    return result.stdout


def _source(commit):
    if _run(['git', 'rev-parse', 'HEAD']).strip() != commit:
        raise ReleaseError('Checkout commit differs from the selected CI commit')
    if _run(['git', 'status', '--porcelain']).strip():
        raise ReleaseError('Release checkout contains uncommitted changes')
    remote = _run(['git', 'remote', 'get-url', 'origin']).strip().removesuffix('.git')
    if remote != SOURCE_REPOSITORY:
        raise ReleaseError('Unexpected source repository')


def _gate(path):
    data = read_json(_physical(path))
    if (data.get('schema') != 'skinai.ci-selection/v1'
            or data.get('status') not in {'READY', 'WAITING', 'FAILED'}
            or not isinstance(data.get('commit'), str) or COMMIT_RE.fullmatch(data['commit']) is None):
        raise ReleaseError('Invalid CI gate record')
    if data['status'] == 'READY':
        if data.get('branch') != BRANCH or set(data.get('builds', {})) != set(JOBS):
            raise ReleaseError('Incomplete ready gate')
        for number in data['builds'].values():
            positive_build_number(number)
    return data


def _current(gate, home):
    if gate['status'] != 'READY':
        raise ReleaseError('All three CI checks must pass before release work')
    current = select_builds(home, gate['commit'])
    if current['status'] != 'READY' or current['builds'] != gate['builds']:
        raise ReleaseError('Latest CI attempts changed or are no longer successful')
    _source(gate['commit'])
    return current


def _state(root, gate, create):
    root = _physical(root)
    marker = root / 'owner.json'
    if not root.exists():
        if not create:
            return None, None
        root.mkdir(parents=True)
        _json(marker, {'owner': OWNER})
    if not marker.is_file() or read_json(marker) != {'owner': OWNER}:
        raise ReleaseError('Persistent release root has no matching owner')
    number = positive_build_number(gate['builds']['workflow'])
    path = _physical(root / gate['commit'] / f'workflow-{number}')
    if not path.exists():
        if not create:
            return None, None
        path.mkdir(parents=True)
        state = {'owner': OWNER, 'commit': gate['commit'], 'workflow_build': number,
                 'preview': None, 'publish_attempts': []}
        _json(path / 'state.json', state)
    state = read_json(_physical(path / 'state.json'))
    if (set(state) != {'owner', 'commit', 'workflow_build', 'preview', 'publish_attempts'}
            or state['owner'] != OWNER or state['commit'] != gate['commit']
            or state['workflow_build'] != number
            or (state['preview'] is not None and not PREVIEW_NAME.fullmatch(str(state['preview'])))
            or not isinstance(state['publish_attempts'], list)
            or any(not isinstance(name, str) or not PUBLISH_NAME.fullmatch(name) for name in state['publish_attempts'])):
        raise ReleaseError('Persistent release state identity did not match')
    return path, state


def _preview(state_path, state):
    return _physical(state_path / state['preview']) if state['preview'] else None


def _valid_preview(path, commit):
    if path is None:
        raise ReleaseError('No prepared image candidate exists')
    candidate = read_json(_physical(path / 'candidate.json'))
    summary = read_json(_physical(path / 'results/preview-summary.json'))
    validate_gate(candidate, summary, commit)
    assert_inputs_unchanged(REPO, candidate['packaging']['files_sha256'])
    if candidate['model_bundle_manifest_sha256'] != file_hash(HERE / 'backend/model-lock.json'):
        raise ReleaseError('Model manifest changed after preparation')
    return candidate


def _clean_preview(path, docker):
    if path is not None and path.exists() and (path / 'preview-state.json').is_file():
        _physical(path / 'preview-state.json')
        _run([sys.executable, '-B', HERE / 'prepare_preview.py', '--cleanup', '--output', path,
              '--docker', docker], timeout=1200)


def _completed(path, gate):
    release = load_release(_physical(path))
    if release['source']['commit'] != gate['commit'] or release['ci']['workflow']['build'] != gate['builds']['workflow']:
        raise ReleaseError('Existing release belongs to a different source or workflow run')
    for item in release['services'].values():
        verified = verify_public_image(item['repository'], item['tag'], item['local_image_id'],
                                       gate['commit'], expected_digest=item['digest'])
        if any(verified[key] != item[key] for key in ('digest', 'platform_digest', 'config_digest', 'visibility')):
            raise ReleaseError('Published image evidence changed')
    return release


def _preparation(output, mode, state_path, preview):
    value = {'mode': mode, 'state_path': str(state_path), 'preview_path': str(preview) if preview else None}
    _json(output / 'preparation.json', value)
    _props(output / 'preparation.properties', {'mode': mode})


def gate_command(args):
    if COMMIT_RE.fullmatch(args.commit) is None:
        raise ReleaseError('Expected a full commit SHA')
    output = _output(args.output, fresh=True)
    causes = read_json(_physical(args.causes)) if args.causes else []
    if not isinstance(causes, list):
        raise ReleaseError('Expected an upstream cause array')
    resolved = resolve_upstream_causes(args.jenkins_home, causes) if causes else []
    if resolved and not any(item['commit'] == args.commit for item in resolved):
        result = {'schema': 'skinai.ci-selection/v1', 'status': 'WAITING', 'commit': args.commit,
                  'reason': 'UPSTREAM_COMMIT_MISMATCH', 'builds': {}, 'jobs': {}, 'causes': resolved}
    else:
        result = select_builds(args.jenkins_home, args.commit)
        result['causes'] = resolved
    _json(output / 'gate.json', result)
    _props(output / 'gate.properties', {'status': result['status'], 'commit': args.commit,
                                      **{role + '_build': value for role, value in result['builds'].items()}})
    print('CI_GATE_' + result['status'])


def prepare_command(args):
    gate = _gate(args.gate)
    current = _current(gate, args.jenkins_home)
    output = _output(args.output)
    _json(output / 'gate.json', gate)
    path, state = _state(args.state_root, gate, True)
    preview = _preview(path, state)
    _json(output / 'preparation-state.json', {'state_path': str(path),
                                           'preview_path': str(preview) if preview else None})
    if (path / 'release.json').exists():
        _completed(path / 'release.json', gate)
        _current(gate, args.jenkins_home)
        _preparation(output, 'reuse', path, preview)
        return
    valid = False
    try:
        _valid_preview(preview, gate['commit'])
        valid = True
    except (OSError, ValueError, ReleaseError):
        if state['publish_attempts']:
            raise ReleaseError('A publication was attempted; preserve its image candidate or use a new workflow build')
    if not valid:
        _clean_preview(preview, args.docker)
        state['preview'] = 'preview-' + uuid4().hex
        _json(path / 'state.json', state)  # Durable pointer before Docker can change.
        preview = _preview(path, state)
        _json(output / 'preparation-state.json', {'state_path': str(path), 'preview_path': str(preview)})
        try:
            _run([sys.executable, '-B', HERE / 'prepare_preview.py', '--output', preview,
                  '--models', args.models, '--sample', args.sample, '--docker', args.docker,
                  '--node-dir', args.node_dir, '--browsers', args.browsers], timeout=2700)
            _valid_preview(preview, gate['commit'])
        except Exception:
            # The preview finalizer redacts this bounded summary. Raw process,
            # container and browser logs remain only in the owned state folder.
            summary_path = _physical(preview / 'results/preview-summary.json')
            if summary_path.is_file():
                _write(output / 'preview-summary.json', summary_path.read_bytes())
            raise
    _current(gate, args.jenkins_home)
    _json(output / 'ci-evidence.json', current['ci'])
    _preparation(output, 'publish', path, preview)
    _write(output / 'preview-summary.json', _physical(preview / 'results/preview-summary.json').read_bytes())
    print('RELEASE_PREPARED')


def _auth_session(docker, scratch):
    from registry_session import authenticated_registry
    return authenticated_registry(docker, scratch)


def _auth_cleanup(scratch):
    from registry_session import cleanup_registry_sessions
    return cleanup_registry_sessions(scratch)


def _export(output, path, state, gate, release_path, home):
    # Everything except release.json is copied first. No raw logs, token files,
    # Docker config, screenshots, DB or photo content enter the artifact folder.
    preview = _preview(path, state)
    if preview and (preview / 'results/preview-summary.json').is_file():
        _write(output / 'preview-summary.json', _physical(preview / 'results/preview-summary.json').read_bytes())
    for name in ('publication_report.json', 'ci-evidence.json'):
        for attempt in reversed(state['publish_attempts']):
            source = _physical(path / attempt / name)
            if source.is_file():
                _write(output / name, source.read_bytes())
                break
    _current(gate, home)
    _write(output / 'release.json', _physical(release_path).read_bytes())


def publish_command(args):
    gate = _gate(args.gate)
    _current(gate, args.jenkins_home)
    output = _output(args.output)
    _json(output / 'gate.json', gate)
    path, state = _state(args.state_root, gate, False)
    if path is None:
        raise ReleaseError('Prepare the release before publication')
    final = path / 'release.json'
    if final.exists():
        _completed(final, gate)  # Anonymous reads; no login/credential required.
    else:
        preview = _preview(path, state)
        _valid_preview(preview, gate['commit'])
        attempt = 'publish-' + uuid4().hex
        state['publish_attempts'].append(attempt)
        _json(path / 'state.json', state)  # Prevent rebuilding after partial pushes.
        publish_output = _physical(path / attempt)
        command = [sys.executable, '-B', HERE / 'publish.py', '--run', preview,
                   '--output', publish_output, '--docker', args.docker, '--jenkins-home', args.jenkins_home]
        for role, number in gate['builds'].items():
            command += ['--' + role + '-build', str(number)]
        command += ['--publish']
        try:
            with _auth_session(args.docker, args.auth_scratch) as environment:
                _run(command, timeout=3600, env=environment)
        finally:
            if (publish_output / 'publication_report.json').is_file():
                _write(output / 'publication_report.json', _physical(publish_output / 'publication_report.json').read_bytes())
        # Login cleanup has already completed before any success artifact.
        _completed(publish_output / 'release.json', gate)
        _valid_preview(preview, gate['commit'])
        _current(gate, args.jenkins_home)
        _write(final, _physical(publish_output / 'release.json').read_bytes())
    _current(gate, args.jenkins_home)
    _export(output, path, state, gate, final, args.jenkins_home)
    print('RELEASE_ARCHIVE_READY')


def cleanup_command(args):
    # Remove the login state before Docker/port-lock cleanup can block or be
    # terminated by Jenkins. A prior auth-cleanup error still fails the job.
    auth_error = None
    try:
        removed = _auth_cleanup(args.auth_scratch)
        print('RELEASE_AUTH_CLEANUP_OK:', removed)
    except Exception as exc:
        auth_error = exc
    try:
        if Path(args.gate).is_file():
            gate = _gate(args.gate)
            if gate['status'] == 'READY':
                path, state = _state(args.state_root, gate, False)
                if path is not None:
                    _clean_preview(_preview(path, state), args.docker)
    finally:
        if auth_error is not None:
            raise auth_error
    if args.output:
        output = _output(args.output)
        _json(output / 'cleanup.json', {'status': 'passed'})
    print('RELEASE_CLEANUP_OK')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    gate = commands.add_parser('gate')
    gate.add_argument('--jenkins-home', type=Path, required=True)
    gate.add_argument('--commit', required=True)
    gate.add_argument('--output', type=Path, required=True)
    gate.add_argument('--causes', type=Path)
    for name in ('prepare', 'publish', 'cleanup'):
        command = commands.add_parser(name)
        command.add_argument('--gate', type=Path, required=True)
        command.add_argument('--state-root', type=Path, required=True)
        command.add_argument('--docker', required=True)
        command.add_argument('--output', type=Path, required=name != 'cleanup')
        if name != 'cleanup':
            command.add_argument('--jenkins-home', type=Path, required=True)
        if name == 'prepare':
            for flag in ('models', 'sample', 'node-dir', 'browsers'):
                command.add_argument('--' + flag, type=Path, required=True)
        if name in ('publish', 'cleanup'):
            command.add_argument('--auth-scratch', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        {'gate': gate_command, 'prepare': prepare_command, 'publish': publish_command,
         'cleanup': cleanup_command}[args.operation](args)
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, (ReleaseError, RegistrySessionError)) else 'Operation could not be verified; no successful release artifact was created'
        if args.output and Path(args.output).is_dir():
            try:
                _json(_output(args.output) / 'failure.json', {'status': 'failed', 'stage': args.operation,
                                                             'reason': reason, 'error_type': type(exc).__name__})
            except Exception:
                pass
        print('RELEASE_OPERATION_FAILED:', reason, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())