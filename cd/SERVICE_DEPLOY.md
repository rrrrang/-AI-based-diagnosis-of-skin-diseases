# 실제 서비스 이미지 배포

Jenkins `SkinAI-Release-CI` 성공 실행의 `release.json`을 사용합니다. 저장소 `main`에 있는 `ci/release/handoff/release.py`로 전달 파일을 검증하고, API·워커·환자 UI·의사 UI 이미지 4개를 digest로 고정합니다.

## Jenkins 자동 실행

현재 PC에서 기존 CI와 새 CD를 함께 실행하는 구성입니다. 기존 CI는 18165~18167, 새 CD는 **API 18265 · 환자 UI 18266 · 의사 UI 18267**을 사용합니다. 새 Compose 프로젝트는 `skinai-service-local`이며, DB·사진은 이 프로젝트의 별도 볼륨에 저장됩니다.

같은 PC에 배포 전용 Windows 에이전트를 추가하고 `skinai-cd` 라벨, 실행기 1개, **라벨이 일치하는 작업만 실행**을 설정합니다. 해당 계정에서 Linux Docker 엔진, Java 21 이상(현재 Jenkins 지원 버전), Git, Python, Node/npm, Playwright Chromium을 사용할 수 있어야 합니다. 기존 Jenkins 노드·작업·포트는 바꾸지 않습니다.

영속 설정·복구 기록은 `D:/SkinAI_DevOps/service_cd_runtime`, 에이전트 작업 폴더는 `D:/SkinAI_DevOps/service_cd_agent`를 사용합니다. DB·사진 데이터 자체는 `skinai-service-local_db`, `skinai-service-local_photos` Docker 볼륨에 있습니다. 이 저장 폴더와 볼륨의 백업은 별도로 준비합니다.

1. 변경을 main에 통합하고 `SkinAI-Service-CD` Pipeline 작업의 SCM을 `*/main`, Script Path를 `cd/Jenkinsfile`로 설정합니다. Copy Artifact 플러그인을 설치하고 `SkinAI-Release-CI`의 산출물을 이 작업이 복사할 수 있도록 허용합니다.
2. 에이전트 환경에 `SKINAI_CD_DIR=D:/SkinAI_DevOps/service_cd_runtime`과 합성 PNG 경로 `SKINAI_E2E_SAMPLE`을 설정합니다. `runtime.env`에 설정한 d1 토큰과 일치하는 Jenkins Secret Text `skinai-cd-doctor-token`을 등록합니다. Chromium이 별도 경로에 설치돼 있다면 `PLAYWRIGHT_BROWSERS_PATH`를 설정합니다.
3. 신규 Pipeline의 SCM 설정을 처음 한 번 읽히고, Release CI 성공 후 자동 실행되는지 확인합니다. CD는 해당 실행 번호의 `release.json`을 복사합니다. 수동 실행은 배포를 진행하지 않습니다.
4. 성공 실행에서 `release.json`과 `cd-evidence/candidate/`의 두 업무 흐름 검사 결과를 확인합니다. 검사 한 번당 합성 접수 2건이 배포 데이터에 남으므로 팀 검증 환경을 사용합니다.

검사 주소를 설정으로 받는 새 커밋이 세 CI와 Release 검사를 통과한 뒤 배포를 연결합니다. 기존 Release #10의 검사 주소는 CI 포트에 고정돼 있어 이 구성으로 실제 배포할 수 없습니다. #10은 설정 생성·이미지 확인 자료로만 사용하고 원본 커밋이나 검사 파일을 바꾸지 않습니다. 이 구성은 `cd/local-service-deploy` 브랜치에서 준비합니다. 브랜치에 커밋·푸시하는 것만으로 기존 main이나 Jenkins 작업 설정이 바뀌지는 않습니다. main 반영과 새 CD 작업 연결은 별도 단계로 진행합니다.

배포할 이미지의 소스 커밋은 `release.json`에서 가져옵니다. CD는 그 커밋의 Playwright 코드와 잠금 파일을 임시 폴더에 준비합니다. 이전 성공 구성이 있으면 해당 커밋의 검사도 배포 전에 준비합니다. 각 Compose 구성에서 API·환자 UI·의사 UI 주소를 읽어 `SKINAI_E2E_API_URL`, `SKINAI_E2E_PATIENT_URL`, `SKINAI_E2E_DOCTOR_URL`로 전달합니다. 해당 커밋이 이 설정을 지원하지 않거나 두 검사 중 하나라도 준비할 수 없으면 실행 중인 서비스를 교체하지 않습니다.

이미지 실행과 업무 흐름 검사가 통과하면 소스 커밋이 포함된 `last-good.json`을 저장합니다. 실행이나 검사에 실패하면 이전 이미지를 다시 띄우고 **이전 커밋의 검사 코드로 사진 접수 → 분석 → 의사 확정 → 환자 결과 조회**를 다시 실행합니다. `cd-evidence/rollback/`에서 검사 커밋과 결과를 확인할 수 있습니다. 롤백 검사가 통과해도 신규 배포는 실패로 기록됩니다. 첫 배포가 실패하면 서비스 컨테이너를 멈추고 볼륨을 보존합니다. 기존 포맷의 `last-good.json`에 소스 커밋이 없다면 대응하는 원본 릴리스 파일에서 설정을 다시 생성해야 합니다.

[Jenkins Copy Artifact 설정](https://www.jenkins.io/doc/pipeline/steps/copyartifact/)

## 배포 서버에서 실행

Docker Compose가 실행 중인 Linux 컨테이너 호스트와 Python을 준비합니다. 최초 실행 전 출력 경로 옆에 Git 외부의 `runtime.env`를 만들고 서버에서 사용하는 `SKINAI_DEMO_DOCTOR_TOKENS`를 설정합니다. 수동 검사에서도 `SKINAI_E2E_SAMPLE`과 `SKINAI_E2E_DOCTOR_TOKEN`을 먼저 설정합니다. 아래는 Windows PowerShell 예시이며, `D:/SkinAI_DevOps/service_cd_runtime` 폴더에는 Jenkins에서 받은 `release.json`을 둡니다.

```powershell
python cd/prepare_service_release.py D:/SkinAI_DevOps/service_cd_runtime/release.json D:/SkinAI_DevOps/service_cd_runtime/compose.current.json
docker compose -f D:/SkinAI_DevOps/service_cd_runtime/compose.current.json config --quiet
python cd/deploy_service_release.py D:/SkinAI_DevOps/service_cd_runtime/compose.current.json --evidence D:/SkinAI_DevOps/service_cd_runtime/evidence/manual
```

다른 체크아웃의 CI 검증기를 사용하려면 생성 명령에 `--validator <main 체크아웃>/ci/release/handoff/release.py`를 추가합니다. 출력 파일은 새 경로를 사용하며, 이전 구성은 롤백용으로 보관합니다.

## 배포 확인

- 배포 호스트에서 `http://127.0.0.1:18265/api/health`와 `docker compose -f D:/SkinAI_DevOps/service_cd_runtime/compose.current.json ps`를 확인합니다.
- 환자 UI는 18266, 의사 UI는 18267을 사용합니다. 합성 사진으로 접수 → 실제 추론 완료 → 의사 소견 공개 → 환자 화면 조회까지 확인한 릴리스와 Compose 파일을 성공본으로 보관합니다.
- 포트는 배포 호스트의 루프백에 바인딩됩니다. 팀 PC에서 접근하려면 호스트의 접근 경로를 별도로 설정합니다.

## 롤백

배포 확인에 실패하면 같은 폴더에 보관한 직전 성공 Compose 파일에 `pull`과 `up -d --wait`를 실행합니다. 동일한 프로젝트 이름과 DB·사진 볼륨을 사용합니다. 볼륨 삭제 옵션을 사용하지 않습니다. 데이터 구조가 바뀌는 릴리스는 이전 이미지와의 호환성 및 백업을 확인한 뒤 적용합니다.

## Grad-CAM 결과 그림 저장

새 구성은 `analysis` 볼륨을 `/data/analysis`에 연결하고 `SKINAI_ANALYSIS_DIR`로 지정합니다. 워커는 이 공간에 그림을 저장하고 API는 읽기 전용으로 조회합니다. 원본 `photos` 볼륨은 워커에서 계속 읽기 전용입니다. 결과 그림도 유지하려면 `skinai-service-local_analysis` 볼륨을 백업 대상에 포함합니다.

API는 이전 버전의 사진 폴더에 이미 저장된 그림도 조회합니다. 그림 없이 완료된 과거 접수는 자동 재분석하지 않으므로 새 합성 접수로 저장·PNG 조회·의사 화면 표시를 확인합니다.

Release #33처럼 별도 그림 경로를 모르는 버전으로 복구하면 새 버전에서 생성한 Grad-CAM은 표시되지 않을 수 있습니다. 새 그림 볼륨은 삭제하지 않으며 원본 사진·DB의 분석 결과·의사 소견은 그대로 유지합니다. 이 문서와 브랜치 수정만으로 현재 배포 설정이 바뀌지는 않습니다.
