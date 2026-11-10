"""CI 릴리스의 이미지 주소로 CD 실행 설정을 생성한다."""

import argparse
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from cd import ROOT, STATE, deploy, deployment_lock, read_json, validate


def prepare_compose(release_path: Path, output: Path) -> None:
    # 1. Jenkins의 release.json에서 서비스별 이미지 주소를 읽는다.
    release = read_json(release_path)
    release_services = release["services"]

    # 2. 포트와 서비스 연결 설정은 기존 Compose 파일에서 가져온다.
    template = ROOT / "compose.cd.yaml"
    config = yaml.safe_load(template.read_text(encoding="utf-8-sig"))

    # 3. central과 ai-mock의 image 값만 새 릴리스의 주소로 바꾼다.
    for name in ("central", "ai-mock"):
        config["services"][name]["image"] = release_services[name]["image"]

    # 4. 검사용 임시 Compose 파일을 만든다.
    output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=ROOT / "release.json")
    parser.add_argument("--deploy", action="store_true",
                        help="생성한 설정으로 배포하고 스모크 테스트까지 실행한다")
    args = parser.parse_args()

    try:
        # 생성과 배포를 한 번에 하나씩 실행해 다른 릴리스가 결과를 덮지 않게 한다.
        with deployment_lock(), TemporaryDirectory(dir=STATE) as temporary:
            workspace = Path(temporary)
            release_path = workspace / "release.json"
            candidate = workspace / "compose.cd.yaml"

            # 읽기·검사·배포에서 같은 릴리스 파일을 사용한다.
            release_path.write_bytes(args.release.read_bytes())
            prepare_compose(release_path, candidate)

            if args.deploy:
                # 기존 CD가 검사, pull, up, 스모크 테스트, 성공 기록을 처리한다.
                deploy(release_path, candidate)
            else:
                validate(release_path, candidate)

            output = STATE / "compose.generated.yaml"
            candidate.replace(output)
    except (KeyError, OSError, ValueError, TypeError, AttributeError, RuntimeError,
            subprocess.SubprocessError, yaml.YAMLError) as error:
        print(f"CD 준비 또는 실행 실패: {error}", file=sys.stderr)
        return 1

    print(f"생성된 Compose: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
