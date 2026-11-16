# 실제 서비스 이미지 배포

Jenkins `SkinAI-Release-CI` 성공 실행의 `release.json`을 사용합니다. 저장소 `main`에 있는 `ci/release/handoff/release.py`로 전달 파일을 검증하고, API·워커·환자 UI·의사 UI 이미지 4개를 digest로 고정합니다.

## Jenkins 자동 실행

배포 전용 Windows 에이전트에 `skinai-cd` 라벨을 설정합니다. 해당 계정에서 Linux Docker 엔진, Python, Node/npm, Playwright Chromium을 사용할 수 있어야 합니다. 기존 릴리스 CI와 배포가 같은 포트를 쓰므로 별도의 배포 호스트를 사용합니다.

1. 변경을 main에 통합하고 `SkinAI-Service-CD` Pipeline 작업의 SCM을 `*/main`, Script Path를 `cd/Jenkinsfile`로 설정합니다. Copy Artifact 플러그인을 설치하고 `SkinAI-Release-CI`의 산출물을 이 작업이 복사할 수 있도록 허용합니다.
2. 에이전트 환경에 영속 디렉터리 `SKINAI_CD_DIR`과 합성 PNG 경로 `SKINAI_E2E_SAMPLE`을 설정합니다. `runtime.env`에 설정한 d1 토큰과 일치하는 Jenkins Secret Text `skinai-cd-doctor-token`을 등록합니다. Chromium이 별도 경로에 설치돼 있다면 `PLAYWRIGHT_BROWSERS_PATH`를 설정합니다.
3. 신규 Pipeline의 SCM 설정을 처음 한 번 읽히고, Release CI 성공 후 자동 실행되는지 확인합니다. CD는 해당 실행 번호의 `release.json`을 복사합니다. 수동 실행은 배포를 진행하지 않습니다.
4. 성공 실행에서 `release.json`과 두 업무 흐름 검사 결과를 확인합니다. CD는 합성 접수 2건을 배포 데이터에 남기므로 팀 검증 환경을 사용합니다.

이미지 준비·실행·업무 흐름 검사를 통과하면 같은 디렉터리에 `last-good.json`이 저장됩니다. 실행 또는 업무 흐름 검사에 실패하면 직전 성공 구성을 다시 실행합니다. 첫 배포가 실패하면 서비스 컨테이너를 멈추고 볼륨을 보존합니다.

[Jenkins Copy Artifact 설정](https://www.jenkins.io/doc/pipeline/steps/copyartifact/)

## 배포 서버에서 실행

Docker Compose가 실행 중인 Linux 컨테이너 호스트와 Python을 준비합니다. 최초 실행 전 출력 경로 옆에 Git 외부의 `runtime.env`를 만들고 서버에서 사용하는 `SKINAI_DEMO_DOCTOR_TOKENS`를 설정합니다. 아래는 Windows PowerShell 예시이며, `D:/skin-deploy` 폴더에는 Jenkins에서 받은 `release.json`을 둡니다.

```powershell
python cd/prepare_service_release.py D:/skin-deploy/release.json D:/skin-deploy/compose.current.json
docker compose -f D:/skin-deploy/compose.current.json config --quiet
docker compose -f D:/skin-deploy/compose.current.json pull
docker compose -f D:/skin-deploy/compose.current.json up -d --wait --wait-timeout 180
```

다른 체크아웃의 CI 검증기를 사용하려면 생성 명령에 `--validator <main 체크아웃>/ci/release/handoff/release.py`를 추가합니다. 출력 파일은 새 경로를 사용하며, 이전 구성은 롤백용으로 보관합니다.

## 배포 확인

- 배포 호스트에서 `http://127.0.0.1:18165/api/health`와 `docker compose -f D:/skin-deploy/compose.current.json ps`를 확인합니다.
- 환자 UI는 18166, 의사 UI는 18167을 사용합니다. 합성 사진으로 접수 → 실제 추론 완료 → 의사 소견 공개 → 환자 화면 조회까지 확인한 릴리스와 Compose 파일을 성공본으로 보관합니다.
- 포트는 배포 호스트의 루프백에 바인딩됩니다. 팀 PC에서 접근하려면 호스트의 접근 경로를 별도로 설정합니다.

## 롤백

배포 확인에 실패하면 같은 폴더에 보관한 직전 성공 Compose 파일에 `pull`과 `up -d --wait`를 실행합니다. 동일한 프로젝트 이름과 DB·사진 볼륨을 사용합니다. 볼륨 삭제 옵션을 사용하지 않습니다. 데이터 구조가 바뀌는 릴리스는 이전 이미지와의 호환성 및 백업을 확인한 뒤 적용합니다.
