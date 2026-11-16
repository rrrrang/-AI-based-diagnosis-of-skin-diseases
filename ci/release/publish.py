"""Publish the tested four-image bundle and create release.json only after verification."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE / 'handoff'))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / 'ci/ui_workflow'))
from candidate import validate_candidate
from release import (validate_release, REPOSITORIES, SOURCE_REPOSITORY, SOURCE_BRANCH,
                     VERIFICATION, DEPLOYMENT)
from provenance import assert_inputs_unchanged
from collect_ci_evidence import collect_evidence
from registry import get_public_repository, get_remote_digest, verify_public_image
from run_workflow import run_process, sanitize_text


def read_json(path):
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise ValueError('Duplicate JSON field: ' + key)
            value[key] = child
        return value
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def validate_gate(candidate, summary, commit):
    validate_candidate(candidate)
    if (candidate['source']['commit'] != commit
            or candidate['source']['working_tree_dirty'] is not False
            or candidate['packaging']['status'] != 'committed-draft'
            or candidate.get('verification', {}).get('status') != 'passed'):
        raise ValueError('A successful packaged-image run from the clean committed source is required')
    wanted = {'status': 'passed', 'services': 4, 'workflow_cases': 2,
              'no_host_source_or_model_mounts': True, 'ui_proxy_checks': 'passed',
              'cleanup': 'passed', 'source_inputs_unchanged': True,
              'existing_containers_unchanged': True, 'source_commit': commit}
    for key, expected in wanted.items():
        if type(summary.get(key)) is not type(expected) or summary[key] != expected:
            raise ValueError('Packaged-image gate failed: ' + key)
    images = {name: item['local_image_id'] for name, item in candidate['services'].items()}
    if summary.get('packaged_image_ids') != images:
        raise ValueError('Candidate images differ from the tested images')
    return images


def release_shell(candidate, summary_path, candidate_path, ci):
    commit = candidate['source']['commit']
    return {'schema': 'skinai.release/v2',
            'release_id': f"sha-{commit[:12]}-workflow-{ci['workflow']['build']}",
            'source': {'repository': SOURCE_REPOSITORY, 'branch': SOURCE_BRANCH,
                       'commit': commit, 'working_tree_dirty': False},
            'platform': 'linux/amd64', 'services': {}, 'ci': ci,
            'verification': dict(VERIFICATION), 'deployment': dict(DEPLOYMENT),
            'evidence_sha256': {'candidate': file_hash(candidate_path),
                               'preview_summary': file_hash(summary_path),
                               'model_manifest': candidate['model_bundle_manifest_sha256']}}


def publish_services(release, images, docker, output, command, inspect,
                     repository_reader=get_public_repository,
                     digest_reader=get_remote_digest, verifier=verify_public_image, allow_create=False):
    """No release.json is written until all four public immutable references agree."""
    status = {'status': 'running', 'release_id': release['release_id'], 'services': {}}
    report_path = output / 'publication_report.json'
    save(report_path, status)
    try:
        repositories = {name: repository_reader(repository) for name, repository in REPOSITORIES.items()}
        if not allow_create and any(value is None for value in repositories.values()):
            raise ValueError('Create the four Public repositories first, or explicitly authorize first-publication creation')
        for service, repository in REPOSITORIES.items():
            tag = release['release_id']
            target = repository + ':' + tag
            local_id = images[service]
            state = {'repository': repository, 'tag': tag, 'status': 'pending'}
            status['services'][service] = state
            save(report_path, status)
            public_repo = repositories[service]
            existing = digest_reader(repository, tag) if public_repo is not None else None
            if existing:
                # A retry may reuse an already published identical bundle. Never
                # overwrite a version tag whose content cannot be proven equal.
                observed = verifier(repository, tag, local_id, release['source']['commit'], expected_digest=existing)
                state['status'] = 'verified-existing'
            else:
                command([docker, 'tag', local_id, target], service + '-tag.log')
                if inspect(target)['Id'] != local_id:
                    raise ValueError('The upload tag no longer selects the tested image')
                # Docker Hub creates an absent repository using namespace defaults.
                # A private or unobservable repository cannot produce a release.
                pushed = command([docker, 'push', target], service + '-push.log', timeout=1800)
                state['status'] = 'pushed-awaiting-verification'
                save(report_path, status)
                matches = re.findall(r'\bdigest:\s*(sha256:[0-9a-f]{64})\b', pushed)
                if len(set(matches)) != 1 or inspect(target)['Id'] != local_id:
                    raise ValueError('Upload digest or image identity was not uniquely verified')
                observed = verifier(repository, tag, local_id, release['source']['commit'], expected_digest=matches[0])
                state['status'] = 'verified-public'
            record = {'repository': repository, 'tag': tag, 'digest': observed['digest'],
                      'image': repository + '@' + observed['digest'],
                      'platform_digest': observed['platform_digest'], 'config_digest': observed['config_digest'],
                      'local_image_id': local_id, 'visibility': 'public'}
            release['services'][service] = record
            state['digest'] = observed['digest']
            save(report_path, status)
        validate_release(release)
        status.update(status='images-verified', finished_at=datetime.now(timezone.utc).isoformat())
        save(report_path, status)
        return release
    except Exception as exc:
        status.update(status='failed', error=sanitize_text(str(exc)),
                      finished_at=datetime.now(timezone.utc).isoformat())
        save(report_path, status)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--docker', required=True)
    parser.add_argument('--jenkins-home', type=Path, required=True)
    for role in ('ui', 'backend', 'workflow'):
        parser.add_argument('--' + role + '-build', type=int, required=True)
    parser.add_argument('--publish', action='store_true', help='Perform public uploads; omitted means preflight only')
    parser.add_argument('--create-missing-repositories', action='store_true',
                        help='First publication only: allow Docker Hub to create approved missing names using namespace defaults; Public verification is still mandatory')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        parser.error('Use a new output folder; earlier release evidence is never overwritten')
    output.mkdir(parents=True)
    logs = output / 'logs'
    logs.mkdir()
    def command(values, log, timeout=60):
        result = run_process(values, cwd=REPO, timeout=timeout)
        (logs / log).write_text(sanitize_text(result.stdout), encoding='utf-8')
        if result.returncode:
            raise RuntimeError(f'{log}: command failed ({result.returncode}); see the log')
        return result.stdout
    def inspect(value):
        data = json.loads(command([args.docker, 'image', 'inspect', value], 'image-inspect.log'))
        if len(data) != 1:
            raise ValueError('A single local image was required')
        return data[0]
    try:
        if command(['git', 'status', '--porcelain'], 'git-status.log').strip():
            raise ValueError('Commit all release inputs before building and publishing')
        commit = command(['git', 'rev-parse', 'HEAD'], 'commit.log').strip()
        remote = command(['git', 'remote', 'get-url', 'origin'], 'origin.log').strip().removesuffix('.git')
        if remote != SOURCE_REPOSITORY:
            raise ValueError('Unexpected Git repository')
        candidate_path = args.run / 'candidate.json'
        summary_path = args.run / 'results/preview-summary.json'
        evidence_hashes = {path: file_hash(path) for path in (candidate_path, summary_path)}
        candidate = read_json(candidate_path)
        summary = read_json(summary_path)
        if any(file_hash(path) != value for path, value in evidence_hashes.items()):
            raise ValueError('Packaged-image evidence changed while being read')
        images = validate_gate(candidate, summary, commit)
        assert_inputs_unchanged(REPO, candidate['packaging']['files_sha256'])
        if file_hash(HERE / 'backend/model-lock.json') != candidate['model_bundle_manifest_sha256']:
            raise ValueError('Model manifest changed after the packaged-image run')
        builds = {role: getattr(args, role + '_build') for role in ('ui', 'backend', 'workflow')}
        ci, audit = collect_evidence(args.jenkins_home, commit, builds)
        save(output / 'ci-evidence.json', ci)
        save(output / 'ci-evidence.audit.json', audit)
        for service, local_id in images.items():
            detail = inspect(local_id)
            if (detail['Id'] != local_id or detail.get('Os') != 'linux' or detail.get('Architecture') != 'amd64'
                    or detail.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != commit):
                raise ValueError('Local image revision/platform mismatch: ' + service)
        save(output / 'preflight.json', {'status': 'passed', 'commit': commit, 'ci': ci, 'images': images,
                                        'public_repositories': REPOSITORIES})
        if not args.publish:
            print('PUBLISH_PREFLIGHT_PASSED: no images uploaded')
            return 0
        release = release_shell(candidate, summary_path, candidate_path, ci)
        if (release['evidence_sha256']['candidate'] != evidence_hashes[candidate_path]
                or release['evidence_sha256']['preview_summary'] != evidence_hashes[summary_path]):
            raise ValueError('Packaged-image evidence changed after validation')
        publish_services(release, images, args.docker, output, command, inspect,
                         allow_create=args.create_missing_repositories)
        # Recheck inputs and the exact three completed runs before writing the
        # success handoff. The old mock-server CD is never triggered here.
        assert_inputs_unchanged(REPO, candidate['packaging']['files_sha256'])
        if command(['git', 'rev-parse', 'HEAD'], 'final-commit.log').strip() != commit:
            raise ValueError('Source revision changed during publication')
        final_ci, _ = collect_evidence(args.jenkins_home, commit, builds)
        if final_ci != ci:
            raise ValueError('CI evidence changed during publication')
        validate_release(release)
        if command(['git', 'status', '--porcelain'], 'final-status.log').strip():
            raise ValueError('Working tree changed during publication')
        if any(file_hash(path) != value for path, value in evidence_hashes.items()):
            raise ValueError('Packaged-image evidence changed during publication')
        save(output / 'release.json', release)
        print('PUBLISHED_AND_VERIFIED:', release['release_id'])
        print('RELEASE_FILE:', output / 'release.json')
        return 0
    except Exception as exc:
        report_path = output / 'publication_report.json'
        if report_path.exists():
            report = read_json(report_path)
            report.update(status='failed', error=sanitize_text(str(exc)))
            save(report_path, report)
        save(output / 'failure.json', {'status': 'failed', 'error': sanitize_text(str(exc)),
                                      'release_created': (output / 'release.json').exists()})
        print('PUBLICATION_FAILED:', sanitize_text(str(exc)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
