"""검증된 CD 릴리스를 배포하고, 서버 변경 후 실패하면 직전 정상본을 복구한다."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from datetime import datetime, timezone

import cd
from prepare_compose import prepare_compose


def compose(manifest, *args, timeout=150):
    return cd.run(
        ['docker', 'compose', '--project-name', cd.PROJECT,
         '-f', str(manifest), *args], timeout=timeout
    )


def start_servers(manifest):
    compose(manifest, 'up', '-d', '--no-build', '--pull', 'never',
            '--wait', '--wait-timeout', '90')


def publish_manifest(manifest):
    output = cd.STATE / 'compose.generated.yaml'
    temporary = output.with_suffix('.tmp')
    temporary.write_bytes(manifest.read_bytes())
    os.replace(temporary, output)


def baseline():
    # previous가 아니라 이번 배포 시작 당시 정상본인 current를 보존한다.
    state = cd.read_json(cd.STATE / 'state.json')
    key = state.get('current', '')
    if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key):
        raise ValueError('정상 배포 기록이 없습니다. 먼저 기존 방식으로 정상 배포하세요.')
    folder = cd.STATE / 'releases' / key
    release_file, manifest = folder / 'release.json', folder / 'compose.cd.yaml'
    expected = hashlib.sha256(
        release_file.read_bytes() + b'\0' + manifest.read_bytes()
    ).hexdigest()
    if expected != key:
        raise ValueError('정상본 보관 파일의 내용이 변경되었습니다.')
    release = cd.validate(release_file, manifest)
    # 복구 중 Docker Hub에 접속하지 않도록 정상 이미지를 미리 확인한다.
    for item in release['services'].values():
        cd.run(['docker', 'image', 'inspect', item['image']],
               capture=True, timeout=30)
    return state, folder, release


def execute(release_file, ci_build, report_file, test_stop_ai=False):
    report = {'status': 'PRECHECK_FAILED', 'ci_build': ci_build,
              'test_stop_ai': test_stop_ai, 'server_change_attempted': False}
    exit_code = 1
    try:
        with cd.deployment_lock(), TemporaryDirectory(dir=cd.STATE) as temporary:
            work = Path(temporary)
            frozen = work / 'release.json'
            candidate = work / 'compose.cd.yaml'
            frozen.write_bytes(Path(release_file).read_bytes())
            prepare_compose(frozen, candidate)
            release = cd.validate(frozen, candidate)
            if release['ci']['job'] != 'SkinAI-Two-Server-CI' or release['ci']['build'] != ci_build:
                raise ValueError('요청한 CI 번호와 release.json의 CI 정보가 다릅니다.')
            if test_stop_ai and os.environ.get('CD_RUN_MODE') != 'manual':
                raise ValueError('장애 주입 시험은 수동 CD 실행에서만 허용합니다.')

            saved_state, saved_folder, saved_release = baseline()
            saved_key = saved_state['current']
            key, folder = cd.snapshot(frozen, candidate)
            manifest = folder / 'compose.cd.yaml'
            report.update(
                candidate_release_id=release['release_id'], candidate_key=key,
                restore_release_id=saved_release['release_id'], restore_key=saved_key
            )
            print(f"Recovery baseline: {saved_release['release_id']}", flush=True)

            # 다운로드까지는 실행 중인 컨테이너를 바꾸지 않는다.
            report['status'] = 'PULL_FAILED'
            compose(manifest, 'pull', timeout=300)
            cd.write_json(cd.STATE / 'attempt.json',
                          {'target': key, 'status': 'running'})

            try:
                # up가 도중 실패해도 일부 컨테이너는 바뀌었을 수 있다.
                report['server_change_attempted'] = True
                start_servers(manifest)
                if test_stop_ai:
                    print('TEST: stopping CD ai-mock before connection check', flush=True)
                    compose(manifest, 'stop', '--timeout', '3', 'ai-mock', timeout=30)
                # 시험에서도 가짜 예외 대신 실제 HTTP 연결 실패를 확인한다.
                cd.smoke(timeout=5 if test_stop_ai else 45)

                state = dict(saved_state)
                if key != saved_key:
                    state['previous'] = saved_key
                state.update(current=key, release_id=release['release_id'],
                             updated_at=datetime.now(timezone.utc).isoformat())
                publish_manifest(manifest)
                cd.write_json(cd.STATE / 'state.json', state)
                cd.write_json(cd.STATE / 'attempt.json',
                              {'target': key, 'status': 'success'})
                report['status'] = 'DEPLOYED'
                exit_code = 0
                print(f"Deployment verified: {release['release_id']}", flush=True)
            except Exception as deployment_error:
                report.update(status='ROLLBACK_FAILED',
                              deployment_error=str(deployment_error))
                print(f'DEPLOYMENT FAILED: {deployment_error}', flush=True)
                print(f"Restoring: {saved_release['release_id']}", flush=True)
                try:
                    # 정상본은 로컬 이미지로 복구한다. 장애 주입을 반복하지 않는다.
                    start_servers(saved_folder / 'compose.cd.yaml')
                    cd.smoke()
                    publish_manifest(saved_folder / 'compose.cd.yaml')
                    cd.write_json(cd.STATE / 'state.json', saved_state)
                    # 기존 cd.py status/logs가 복원된 manifest를 찾도록 target도 맞춘다.
                    cd.write_json(cd.STATE / 'attempt.json', {
                        'target': saved_key, 'failed_target': key,
                        'status': 'rolled_back',
                        'error': str(deployment_error)
                    })
                    report['status'] = 'ROLLED_BACK'
                    exit_code = 1  # 복구되어도 원래 배포는 실패이다.
                    print(f"ROLLBACK VERIFIED: {saved_release['release_id']}", flush=True)
                except Exception as rollback_error:
                    report['rollback_error'] = str(rollback_error)
                    exit_code = 2
                    # 복구 중 부분 변경 상태일 수 있으므로 정상 복구라고 표시하지 않는다.
                    try:
                        cd.write_json(cd.STATE / 'attempt.json', {
                            'target': saved_key, 'failed_target': key,
                            'status': 'rollback_failed',
                            'error': str(deployment_error),
                            'rollback_error': str(rollback_error)
                        })
                    except Exception as record_error:
                        report['record_error'] = str(record_error)
                    print(f'ROLLBACK FAILED: {rollback_error}', flush=True)
    except Exception as error:
        if report['status'] in ('DEPLOYED', 'ROLLED_BACK'):
            report['completed_operation'] = report['status']
            report['status'] = 'FINALIZATION_FAILED'
        report['error'] = str(error)
        exit_code = 2 if exit_code == 2 else 1
        print(f"CD stopped ({report['status']}): {error}", flush=True)

    # 보고서는 이번 Jenkins 빌드 폴더에 저장한다. 공용 정상 기록과 구분한다.
    report['finished_at'] = datetime.now(timezone.utc).isoformat()
    cd.write_json(Path(report_file), report)
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True, type=Path)
    parser.add_argument('--ci-build', required=True, type=int)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--test-stop-ai', action='store_true')
    args = parser.parse_args()
    return execute(args.release, args.ci_build, args.report, args.test_stop_ai)


if __name__ == '__main__':
    sys.exit(main())
