"""Build and verify four local delivery images. Does not publish or deploy to CD."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import subprocess
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import urllib.request
import urllib.error

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'ci/ui_workflow'))
from run_workflow import run_process, sanitize_text, redact_artifacts
sys.path.insert(0, str(Path(__file__).parent / 'handoff'))
from candidate import validate_candidate
sys.path.insert(0, str(Path(__file__).parent))
from provenance import snapshot_inputs, assert_inputs_unchanged
SERVICES = ('api', 'worker', 'patient-ui', 'doctor-ui')
OWNER = 'skinai-release-preview'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def compose_for(images, project):
    restrictions = {'read_only': True, 'cap_drop': ['ALL'],
                    'security_opt': ['no-new-privileges:true'],
                    'tmpfs': ['/tmp:rw,nosuid,nodev,size=134217728,mode=1777'],
                    'labels': {'com.skinai.preview.owner': OWNER}}
    common = {**restrictions, 'environment': {'SKINAI_DB_PATH': '/data/db/backend.sqlite3', 'SKINAI_PHOTO_DIR': '/data/photos'}}
    api = {**common, 'image': images['api'], 'pull_policy': 'never',
           'env_file': [{'path': '.env.preview', 'required': False}],
           'ports': ['127.0.0.1:18165:8000'], 'volumes': ['db:/data/db', 'photos:/data/photos'],
           'networks': ['private'], 'mem_limit': '512m', 'cpus': 1}
    worker = {**common, 'image': images['worker'], 'pull_policy': 'never',
              'volumes': ['db:/data/db', 'photos:/data/photos:ro'], 'network_mode': 'none',
              'depends_on': {'api': {'condition': 'service_healthy'}}, 'mem_limit': '4g', 'cpus': 2, 'pids_limit': 128}
    services = {'api': api, 'worker': worker}
    for name, port in [('patient-ui', 18166), ('doctor-ui', 18167)]:
        services[name] = {**restrictions, 'image': images[name], 'pull_policy': 'never',
                          'ports': [f'127.0.0.1:{port}:8080'], 'networks': ['private'],
                          'depends_on': {'api': {'condition': 'service_healthy'}}, 'mem_limit': '128m', 'cpus': 0.5}
    return {'name': project, 'services': services,
            'networks': {'private': {'labels': {'com.skinai.preview.owner': OWNER}}},
            'volumes': {name: {'labels': {'com.skinai.preview.owner': OWNER}} for name in ['db', 'photos']}}


def cleanup(output, docker):
    output = output.resolve()
    state = json.loads((output / 'preview-state.json').read_text(encoding='utf-8'))
    project = state.get('project', '')
    if (state.get('owner') != OWNER or state.get('output') != str(output)
            or not re.fullmatch(r'skinai-release-preview-[0-9a-f]{8}', project)):
        raise RuntimeError('Refusing cleanup without matching preview ownership')
    compose_path = output / 'compose.preview.json'
    if compose_path.resolve() != compose_path or digest(compose_path) != state['compose_sha256']:
        raise RuntimeError('Refusing changed preview Compose file')
    config = json.loads(compose_path.read_text(encoding='utf-8'))
    if config != compose_for(state['images'], project):
        raise RuntimeError('Refusing unexpected preview configuration')
    for name in ['results', '.env.preview']:
        if (output / name).resolve() != output / name:
            raise RuntimeError('Refusing redirected preview path')
    # Test tokens use the same field names and URL-safe format as workflow reports.
    token = ''
    env_file = output / '.env.preview'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.startswith('SKINAI_DEMO_DOCTOR_TOKENS='):
                token = json.loads(line.split('=', 1)[1]).get('d1', '')
    redact_artifacts(output, [token])
    def call(args):
        result = run_process([docker, *args], cwd=output, timeout=120)
        if result.returncode:
            raise RuntimeError('Preview cleanup command failed: ' + sanitize_text(result.stdout[-1500:], [token]))
        return result.stdout
    # Compose addresses declared volumes by name, including resources without
    # project labels. Inspect those names explicitly before any removal.
    expected_names = {'network': [project + '_private'],
                      'volume': [project + '_db', project + '_photos']}
    def inspect_named(kind, name):
        # Missing-resource error text differs across Docker versions. Enumerate
        # exact names first; a Docker error is never treated as absence.
        names = call([kind, 'ls', '--format', '{{.Name}}']).splitlines()
        if name not in names:
            return None
        items = json.loads(call([kind, 'inspect', name]))
        if len(items) != 1 or items[0].get('Name') != name:
            raise RuntimeError('Unexpected named preview resource')
        return items[0]
    for kind, names in expected_names.items():
        for name in names:
            item = inspect_named(kind, name)
            if item is not None:
                labels = item.get('Labels') or {}
                if (labels.get('com.docker.compose.project') != project
                        or labels.get('com.skinai.preview.owner') != OWNER):
                    raise RuntimeError('Refusing an unowned named Docker resource')
    for kind in ['container', 'network', 'volume']:
        args = ['ps', '-a', '-q', '--no-trunc'] if kind == 'container' else [kind, 'ls', '-q']
        ids = call(args + ['--filter', f'label=com.docker.compose.project={project}']).split()
        if not ids:
            continue
        for item in json.loads(call([kind, 'inspect', *ids])):
            labels = item.get('Config', {}).get('Labels', {}) if kind == 'container' else item.get('Labels', {})
            labels = labels or {}
            if labels.get('com.docker.compose.project') != project or labels.get('com.skinai.preview.owner') != OWNER:
                raise RuntimeError('Refusing an unowned Docker resource')
            name = item['Name'].lstrip('/')
            if kind == 'container':
                service = labels.get('com.docker.compose.service')
                if service not in SERVICES or name != f'{project}-{service}-1':
                    raise RuntimeError('Unexpected preview container')
            elif kind == 'volume' and name not in {project + '_db', project + '_photos'}:
                raise RuntimeError('Unexpected preview volume')
            elif kind == 'network' and name != project + '_private':
                raise RuntimeError('Unexpected preview network')
    result = call(['compose', '-p', project, '-f', str(compose_path), 'down', '--volumes', '--timeout', '20'])
    (output / 'results/cleanup.log').write_text(sanitize_text(result, [token]), encoding='utf-8')
    for args in [['ps', '-a', '-q'], ['network', 'ls', '-q'], ['volume', 'ls', '-q']]:
        if call(args + ['--filter', f'label=com.docker.compose.project={project}']).strip():
            raise RuntimeError('Preview Docker resources remain')
    for kind, names in expected_names.items():
        if any(inspect_named(kind, name) is not None for name in names):
            raise RuntimeError('Named preview Docker resources remain')
    env_file.unlink(missing_ok=True)
    return {'status': 'passed', 'project': project, 'containers_network_volumes_removed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--models', type=Path)
    parser.add_argument('--sample', type=Path)
    parser.add_argument('--docker', required=True)
    parser.add_argument('--node-dir', type=Path)
    parser.add_argument('--browsers', type=Path)
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if args.cleanup:
        print(json.dumps(cleanup(output, args.docker), ensure_ascii=False))
        return 0
    for key in ['models', 'sample', 'node_dir', 'browsers']:
        if getattr(args, key) is None or not getattr(args, key).exists():
            parser.error(f'Existing --{key.replace("_", "-")} is required')
    if output.exists():
        parser.error('Use a new output directory')
    for port in [18165, 18166, 18167]:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                parser.error(f'Port {port} already in use; no existing server will be changed')
    output.mkdir(parents=True)
    results = output / 'results'
    results.mkdir()
    (output / 'temp').mkdir()
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8',
           'TEMP': str(output / 'temp'), 'TMP': str(output / 'temp'),
           'PATH': str(args.node_dir) + os.pathsep + os.environ.get('PATH', ''),
           'npm_config_cache': 'D:/SkinAI_DevOps/npm-cache', 'CI': 'true',
           'PLAYWRIGHT_BROWSERS_PATH': str(args.browsers)}
    token = secrets.token_urlsafe(32)
    env.update(SKINAI_E2E_DOCTOR_TOKEN=token, SKINAI_E2E_SAMPLE=str(args.sample.resolve()), SKINAI_E2E_OUTPUT=str(results))
    def run(command, log, timeout=300, cwd=REPO):
        print('RUN:', log, flush=True)
        try:
            result = run_process(command, cwd=cwd, env=env, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            body = exc.output or ''
            if isinstance(body, bytes):
                body = body.decode('utf-8', errors='replace')
            (results / log).write_text(sanitize_text(body, [token]), encoding='utf-8')
            raise RuntimeError(f'{log} timed out after {timeout} seconds') from None
        text = sanitize_text(result.stdout, [token])
        (results / log).write_text(text, encoding='utf-8')
        print(text[-3000:], flush=True)
        if result.returncode:
            raise RuntimeError(f'{log} failed; exit={result.returncode}')
        return result.stdout
    candidate = None
    report = {'status': 'failed', 'started_at': datetime.now(timezone.utc).isoformat()}
    before = {}
    input_hashes = None
    try:
        raw = run([args.docker, 'ps', '-a', '--no-trunc', '--format', '{{.ID}} {{.State}}'], 'before.log')
        before = dict(line.split(maxsplit=1) for line in raw.splitlines())
        commit = run(['git', 'rev-parse', 'HEAD'], 'source.log').strip()
        dirty = bool(run(['git', 'status', '--porcelain'], 'source-status.log').strip())
        input_hashes = snapshot_inputs(REPO)
        write_json(results/'source-inputs.json', input_hashes)
        run([sys.executable, '-B', str(REPO/'ci/release/backend/support/model_guard.py'), '--models-root', str(args.models.resolve())], 'model-bundle.log')
        suffix = commit[:12] + '-' + secrets.token_hex(4)
        images = {}
        tags = {}
        for service in SERVICES:
            tag = f'skinai-preview-{service}:{suffix}'
            command = [args.docker, 'build', '--load', '--platform', 'linux/amd64', '--progress=plain',
                       '--label', 'org.opencontainers.image.revision=' + commit, '-t', tag]
            if service in ('api', 'worker'):
                command += ['-f', 'ci/release/backend/Dockerfile', '--target', service]
                if service == 'worker':
                    command += ['--build-context', 'models=' + str(args.models.resolve())]
            else:
                app = 'patient-frontend' if service == 'patient-ui' else 'doctor-frontend'
                command += ['-f', 'ci/release/frontend/Dockerfile', '--build-arg', 'UI_APP=' + app]
            run(command + ['.'], service + '-image-build.log', timeout=1200)
            images[service] = run([args.docker, 'image', 'inspect', tag, '--format', '{{.Id}}'], service + '-image-id.log').strip()
            tags[service] = tag
        candidate = {'schema': 'skinai.local-candidate/v2', 'candidate_id': suffix,
                     'draft_only': True, 'deployable': False, 'target': 'local-preview', 'platform': 'linux/amd64',
                     'source': {'commit': commit, 'working_tree_dirty': dirty},
                     'packaging': {'status': 'uncommitted-draft' if dirty else 'committed-draft',
                                   'files_sha256': input_hashes},
                     'services': {s: {'local_image_id': images[s], 'local_tag': tags[s]} for s in SERVICES},
                     'model_bundle_manifest_sha256': digest(REPO/'ci/release/backend/model-lock.json'),
                     'verification': {'status': 'pending'},
                     'limitations': ['Local preview only; no registry publication', 'Demo doctor authentication',
                                     'CD configuration not approved', 'Not a clinical accuracy evaluation']}
        validate_candidate(candidate)
        write_json(output/'candidate.json', candidate)
        project = OWNER + '-' + secrets.token_hex(4)
        write_json(output/'compose.preview.json', compose_for(images, project))
        write_json(output/'preview-state.json', {'owner': OWNER, 'output': str(output), 'project': project,
                   'images': images, 'compose_sha256': digest(output/'compose.preview.json')})
        (output/'.env.preview').write_text('SKINAI_DEMO_DOCTOR_TOKENS=' + json.dumps({'d1':token}) + '\n', encoding='utf-8')
        run([args.docker, 'compose', '-p', project, '-f', str(output/'compose.preview.json'), 'up', '-d', '--wait', '--wait-timeout', '240'], 'startup.log', timeout=300)
        # Inspect actual built images/containers: no source or model bind mounts.
        ids = run([args.docker, 'compose', '-p', project, '-f', str(output/'compose.preview.json'), 'ps', '-q'], 'container-ids.log').split()
        containers = json.loads(run([args.docker, 'inspect', *ids], 'container-inspect.log'))
        if len(containers) != 4 or any(m.get('Type') == 'bind' for c in containers for m in c.get('Mounts', [])):
            raise RuntimeError('Expected four self-contained containers without host source/model mounts')
        actual_services = {}
        for container in containers:
            service = container['Config']['Labels'].get('com.docker.compose.service')
            if service not in SERVICES or service in actual_services:
                raise RuntimeError('Unexpected or duplicate packaged service')
            if (container['Config']['Image'] != images[service]
                    or container['Image'] != images[service]
                    or container['State'].get('Health', {}).get('Status') != 'healthy'):
                raise RuntimeError('Packaged image identity or readiness did not match')
            actual_services[service] = images[service]
        if set(actual_services) != set(SERVICES):
            raise RuntimeError('A packaged service is missing')
        write_json(results/'verified-images.json', actual_services)
        for port in [18166,18167]:
            for route in ['/healthz','/api/health']:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}{route}', timeout=5) as response:
                    if response.status != 200 or 'no-store' not in response.headers.get('Cache-Control',''):
                        raise RuntimeError('UI health/proxy/cache check failed')
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/api/not-a-real-route', timeout=5)
                raise RuntimeError('API error incorrectly became a successful SPA response')
            except urllib.error.HTTPError as error:
                if error.code != 404 or 'application/json' not in error.headers.get('Content-Type',''):
                    raise RuntimeError('API error was not preserved')
        run([args.node_dir/'npm.cmd','ci','--no-audit','--no-fund'], 'test-packages.log', cwd=REPO/'frontend/patient-frontend')
        run([args.node_dir/'npm.cmd','exec','--','playwright','test','--config','playwright.release.config.ts'],
            'image-workflow.log', timeout=1000, cwd=REPO/'frontend/patient-frontend')
        for count in [2,3]:
            if json.loads((results/f'workflow-{count}-photos.json').read_text(encoding='utf-8'))['status'] != 'passed':
                raise RuntimeError('Missing successful packaged workflow evidence')
        report.update(status='passed', services=4, no_host_source_or_model_mounts=True, ui_proxy_checks='passed',
                      workflow_cases=2, source_commit=commit, sample_sha256=digest(args.sample),
                      packaged_image_ids=actual_services)
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = sanitize_text(str(exc), [token])
        print('PREVIEW FAILED:', report['error'], flush=True)
        if (output/'preview-state.json').exists():
            try:
                run([args.docker, 'compose', '-p', project, '-f', str(output/'compose.preview.json'),
                     'logs', '--no-color', '--tail', '100'], 'failure-containers.log', timeout=30)
            except Exception as diagnostic_error:
                report['diagnostic_error'] = sanitize_text(str(diagnostic_error), [token])
    finally:
        if (output/'preview-state.json').exists():
            try:
                cleanup_report = cleanup(output, args.docker)
                write_json(results/'cleanup.json', cleanup_report)
                report['cleanup'] = 'passed'
            except Exception as exc:
                report.update(status='failed', cleanup='failed', cleanup_error=sanitize_text(str(exc),[token]))
        try:
            raw = run_process([args.docker,'ps','-a','--no-trunc','--format','{{.ID}} {{.State}}'],cwd=REPO,timeout=30)
            if raw.returncode:
                raise RuntimeError('Unable to verify Docker state')
            after = dict(line.split(maxsplit=1) for line in raw.stdout.splitlines())
            report['existing_containers_checked'] = len(before)
            report['existing_containers_unchanged'] = all(after.get(k)==v for k,v in before.items())
            if not report['existing_containers_unchanged']:
                raise RuntimeError('Existing Docker container state changed')
        except Exception as exc:
            report.update(status='failed', preservation_error=sanitize_text(str(exc), [token]))
        try:
            if input_hashes is not None:
                assert_inputs_unchanged(REPO, input_hashes)
                report['source_inputs_unchanged'] = True
        except Exception as exc:
            report.update(status='failed', source_verification_error=sanitize_text(str(exc), [token]))
        try:
            redact_artifacts(output,[token])
        except Exception as exc:
            report.update(status='failed', finalization_error=sanitize_text(str(exc), [token]))
        # A pass verdict is written only after cleanup, preservation, frozen-input
        # comparison and report redaction have all finished successfully.
        if candidate:
            candidate['verification']['status'] = report['status']
            validate_candidate(candidate)
            write_json(output/'candidate.json',candidate)
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        write_json(results/'preview-summary.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
