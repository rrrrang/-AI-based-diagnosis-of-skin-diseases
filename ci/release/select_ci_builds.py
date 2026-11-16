"""Select complete checks for one exact revision from the fixed local CI jobs.

Reads numeric build folders and build.xml/log only. A newer attempt for the same
revision replaces an older success. Missing or unfinished evidence never passes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect_ci_evidence import (
    JOBS, BRANCH, REPOSITORY, COMMIT_RE, LAST_BUILD_REFERENCE,
    _read_evidence_file, _revision_sha, positive_build_number,
    verify_build_xml, verify_build_log, collect_evidence,
)

MAX_XML = 8 * 1024 * 1024
MAX_LOG = 64 * 1024 * 1024


def _home(value):
    path = Path(value).absolute()
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise ValueError('Refusing a redirected Jenkins home')
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Jenkins home must be a directory')
    return path


def _directory(home, path):
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError('Refusing redirected Jenkins evidence path')
        if item == home:
            break
    if not path.resolve(strict=True).is_relative_to(home) or not path.is_dir():
        raise ValueError('Unexpected Jenkins build directory')
    return path


def _metadata(raw, number):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported XML declaration')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError('Incomplete or invalid build metadata') from exc
    if root.tag != 'flow-build':
        raise ValueError('Expected Pipeline build metadata')
    identity = None
    data = root.findall('./actions/hudson.plugins.git.util.BuildData')
    if data:
        if len(data) != 1:
            raise ValueError('Ambiguous SCM metadata')
        urls = [entry.text for entry in data[0].findall('./remoteUrls/string')]
        entries = data[0].findall('./buildsByBranchName/entry')
        last = data[0].find('lastBuild')
        reference = LAST_BUILD_REFERENCE.fullmatch(last.get('reference', '')) if last is not None else None
        if reference is None or len(urls) != 1:
            raise ValueError('Unsupported current SCM identity')
        index = int(reference.group(1) or '1') - 1
        if index >= len(entries):
            raise ValueError('SCM reference does not exist')
        selected = entries[index]
        build = selected.find('hudson.plugins.git.util.Build')
        if build is None:
            raise ValueError('Missing current SCM revision')
        # During checkout, persisted data can still describe an earlier build.
        # Never attribute historical entries to this attempt.
        if build.findtext('hudsonBuildNumber') == str(number):
            identity = {'commit': _revision_sha(build), 'branch': selected.findtext('string'),
                        'repository': urls[0].removesuffix('.git') if isinstance(urls[0], str) else None}
    return root, identity


def _numbers(home, job):
    folder = home / 'jobs' / job / 'builds'
    if not folder.exists():
        return []
    _directory(home, folder)
    numbers = []
    for path in folder.iterdir():
        if not path.name.isdecimal() or path.name.startswith('0'):
            continue  # Never follow lastSuccessfulBuild or other convenience links.
        number = positive_build_number(path.name)
        _directory(home, path)
        numbers.append(number)
    if len(numbers) > 10000:
        raise ValueError('Build history exceeded the safe scan limit')
    return sorted(numbers, reverse=True)


def _job_selection(home, role, commit):
    job = JOBS[role]
    for number in _numbers(home, job):
        folder = home / 'jobs' / job / 'builds' / str(number)
        try:
            raw = _read_evidence_file(home, folder / 'build.xml', MAX_XML)
            root, identity = _metadata(raw, number)
        except FileNotFoundError:
            return {'job': job, 'build': number, 'state': 'WAITING', 'reason': 'METADATA_NOT_WRITTEN'}
        except (OSError, ValueError):
            return {'job': job, 'build': number, 'state': 'WAITING', 'reason': 'METADATA_UNAVAILABLE'}
        completed = root.findtext('completed') == 'true' and root.findtext('building') != 'true'
        if identity is None:
            return {'job': job, 'build': number, 'state': 'FAILED' if completed else 'WAITING',
                    'reason': 'CURRENT_REVISION_UNKNOWN'}
        if identity != {'commit': commit, 'branch': BRANCH, 'repository': REPOSITORY}:
            continue
        if not completed:
            return {'job': job, 'build': number, 'state': 'WAITING', 'reason': 'BUILD_RUNNING'}
        result = root.findtext('result')
        if result != 'SUCCESS':
            return {'job': job, 'build': number, 'state': 'FAILED', 'reason': 'BUILD_NOT_SUCCESS',
                    'result': result if result in {'FAILURE', 'ABORTED', 'UNSTABLE', 'NOT_BUILT'} else 'UNKNOWN'}
        try:
            log = _read_evidence_file(home, folder / 'log', MAX_LOG)
            verify_build_xml(raw, number, commit)
            verify_build_log(log, commit)
            if raw != _read_evidence_file(home, folder / 'build.xml', MAX_XML):
                return {'job': job, 'build': number, 'state': 'WAITING', 'reason': 'EVIDENCE_CHANGED'}
        except (OSError, ValueError):
            return {'job': job, 'build': number, 'state': 'FAILED', 'reason': 'SUCCESS_EVIDENCE_INVALID'}
        return {'job': job, 'build': number, 'state': 'SUCCESS', 'result': 'SUCCESS'}
    return {'job': job, 'build': None, 'state': 'WAITING', 'reason': 'NO_MATCHING_BUILD'}


def select_builds(jenkins_home, commit):
    """Return READY, WAITING or FAILED; READY includes existing collector proof."""
    if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
        raise ValueError('A full lowercase commit SHA is required')
    home = _home(jenkins_home)
    jobs = {role: _job_selection(home, role, commit) for role in JOBS}
    builds = {role: item['build'] for role, item in jobs.items() if item['state'] == 'SUCCESS'}
    status = ('FAILED' if any(item['state'] == 'FAILED' for item in jobs.values()) else
              'READY' if all(item['state'] == 'SUCCESS' for item in jobs.values()) else 'WAITING')
    result = {'schema': 'skinai.ci-selection/v1', 'status': status, 'commit': commit,
              'branch': BRANCH, 'builds': builds, 'jobs': jobs}
    if status == 'READY':
        try:
            ci, audit = collect_evidence(home, commit, builds)
        except (OSError, ValueError):
            result.update(status='WAITING', reason='EVIDENCE_CHANGED')
            return result
        second = {role: _job_selection(home, role, commit) for role in JOBS}
        if second != jobs:
            result.update(status='WAITING', reason='BUILD_ATTEMPTS_CHANGED', jobs=second)
            return result
        result.update(ci=ci, audit=audit)
    return result


def resolve_upstream_causes(jenkins_home, causes):
    """Resolve only completed, verified SUCCESS causes from the three fixed jobs."""
    if not isinstance(causes, list) or not 1 <= len(causes) <= 50:
        raise ValueError('Provide one or more upstream CI causes')
    home = _home(jenkins_home)
    roles = {job: role for role, job in JOBS.items()}
    resolved, seen = [], set()
    for cause in causes:
        if not isinstance(cause, dict) or cause.get('upstreamProject') not in roles:
            raise ValueError('Upstream cause is not one of the three allowed CI jobs')
        if cause.get('_class', 'hudson.model.Cause$UpstreamCause') != 'hudson.model.Cause$UpstreamCause':
            raise ValueError('Unexpected trigger cause type')
        job = cause['upstreamProject']
        number = positive_build_number(cause.get('upstreamBuild'))
        if (job, number) in seen:
            continue
        folder = home / 'jobs' / job / 'builds' / str(number)
        raw = _read_evidence_file(home, folder / 'build.xml', MAX_XML)
        _, identity = _metadata(raw, number)
        if identity is None or identity['branch'] != BRANCH or identity['repository'] != REPOSITORY:
            raise ValueError('Upstream cause has no verified CI branch revision')
        commit = identity['commit']
        verify_build_xml(raw, number, commit)
        verify_build_log(_read_evidence_file(home, folder / 'log', MAX_LOG), commit)
        if raw != _read_evidence_file(home, folder / 'build.xml', MAX_XML):
            raise ValueError('Upstream build changed during validation')
        resolved.append({'role': roles[job], 'job': job, 'build': number, 'commit': commit})
        seen.add((job, number))
    return resolved


def _json(path):
    if path.stat().st_size > 65536:
        raise ValueError('Cause file exceeds the size limit')
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError('Duplicate JSON field')
            data[key] = value
        return data
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jenkins-home', type=Path, default=Path('D:/JenkinsHome'))
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--causes', type=Path)
    args = parser.parse_args(argv)
    try:
        if COMMIT_RE.fullmatch(args.commit) is None:
            raise ValueError('A full lowercase commit SHA is required')
        if args.output.exists():
            raise ValueError('Use a new selection output path')
        causes = resolve_upstream_causes(args.jenkins_home, _json(args.causes)) if args.causes else None
        if causes is not None and not any(item['commit'] == args.commit for item in causes):
            result = {'schema': 'skinai.ci-selection/v1', 'status': 'WAITING', 'commit': args.commit,
                      'reason': 'UPSTREAM_COMMIT_MISMATCH', 'builds': {}, 'jobs': {}, 'causes': causes}
        else:
            result = select_builds(args.jenkins_home, args.commit)
            if causes is not None:
                result['causes'] = causes
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents a stale or previously successful verdict overwrite.
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print('CI_SELECTION_' + result['status'] + ': ' + args.commit)
        return 0
    except (OSError, ValueError) as exc:
        print('CI selection rejected: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())