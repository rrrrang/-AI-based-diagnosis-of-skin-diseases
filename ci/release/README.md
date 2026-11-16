# 실제 서비스 이미지 빌드·검사·업로드

API, 실제 3모델 worker, 환자 UI, 의사 UI를 각각 이미지로 만듭니다.
이미지 검사·업로드와 전달 파일 생성을 담당하며 Git 병합이나 CD 배포는 실행하지 않습니다.
이 문서는 준비 브랜치의 main 전환 기준입니다. main 반영과 Jenkins 설정 변경은 별도로 진행합니다.

## 정한 내용

| 서비스 | Public Docker Hub 저장소 | 포트 |
| --- | --- | --- |
| API | rlarns982/skinai-api | 18165 |
| AI worker | rlarns982/skinai-worker | 외부 포트 없음 |
| 환자 UI | rlarns982/skinai-patient-ui | 18166 |
| 의사 UI | rlarns982/skinai-doctor-ui | 18167 |

worker에는 모델 파일도 포함됩니다. 로컬 검사는 127.0.0.1을 사용합니다.
다른 PC 접속 주소·허용 설정과 DB·사진 저장 위치·백업은 CD에서 준비합니다.
새 버전을 배포해도 기존 데이터를 유지합니다.

## Jenkins 자동 업로드

main 전환 후 사용할 `SkinAI-Release-CI` 설정입니다. 기존 작업 이름·경로·자격증명은 유지합니다.

| 설정 | 값 |
| --- | --- |
| Definition | Pipeline script from SCM |
| SCM | Git |
| Repository URL | https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases.git |
| Branch Specifier | */main |
| Script Path | ci/release/Jenkinsfile |
| Docker Hub 자격증명 ID | skinai-dockerhub |

UI·Backend·Workflow CI 중 하나가 성공할 때 main의 같은 커밋을 검사한 세 결과를 확인합니다.
세 작업이 모두 SUCCESS여야 진행하며 다른 브랜치의 성공 기록은 사용하지 않습니다.
아직 검사가 끝나지 않았으면 `NOT_BUILT`로 종료하고, 다음 CI 성공 때 다시 확인합니다.
하나라도 실패했거나 커밋이 다르면 이미지를 업로드하지 않습니다.

세 검사 성공 → 4개의 이미지 빌드·연결 검사 → Docker Hub 업로드 →
공개 접근·digest 확인 → 임시 서버·로그인 설정 정리 → `release.json` 보관 순서입니다.
`release.json`은 성공한 실행의 **Artifacts**에서 받습니다. 기존 CD는 자동 실행하지 않습니다.
실패한 실행에는 원인 확인용 보고서만 보관합니다.

- `TEST_BLOCK_UPLOAD`: 수동 차단 검사 전용이며 기본값은 해제입니다. 체크하면
  이미지 준비·로그인·업로드 전에 의도적으로 실패하고 `release.json`을 보관하지 않습니다.
- 같은 버전을 다시 실행하면 이미 검증한 공개 이미지와 전달 파일을 확인해 재사용합니다. 원본 release.json의 검사 번호는 유지하고, 이번 재확인 번호는 gate.json에 남깁니다.
- 일부만 업로드된 경우 같은 검사 이미지로 재시도합니다. 그 이미지가 없어졌다면
  Workflow CI를 다시 검사해 새 버전 번호를 사용합니다.
- 임시 로그인 정보는 Jenkins 자격증명에서 받아 별도 임시 폴더에만 두고 정리합니다.
- 영구 작업 기록은 `D:/SkinAI_DevOps/release_ci_state`에 자동 생성합니다.
  이전 실행의 이미지 근거와 재시도 기록이므로 임의로 지우거나 미리 만들지 않습니다.
- 현재 작업은 이 PC의 Windows·Docker·모델·Node 경로와 Jenkins 완료 기록을 사용합니다.
  다른 실행 PC로 옮길 때는 Jenkinsfile의 경로와 검사 환경을 함께 맞춥니다.

## main 전환 순서

이 준비 코드의 업로드 기준은 이미 main입니다. 실제 전환은 아래 순서로 진행합니다.

1. `SkinAI-Release-CI`만 잠시 비활성화합니다. 실행 중인 Release는 완료될 때까지 기다리고,
   대기 중인 Release가 있으면 취소합니다. 비활성화만으로 진행 중인 업로드가 중단되지는 않습니다.
2. 검사를 마친 준비 코드를 main에 병합합니다.
3. 아래 네 작업의 SCM 브랜치를 모두 `*/main`으로 바꿉니다. 작업 이름과 Script Path는 유지합니다.
4. UI·Backend·Workflow 세 작업을 실행해 같은 새 main 커밋에서 모두 SUCCESS인지 확인합니다.
5. Release 작업을 다시 활성화하고 한 번 직접 실행합니다. 비활성화 중 끝난 검사는 자동 시작되지 않기 때문입니다.
6. 이후 main 변경은 세 CI의 변경 감지 → 검사 성공 → Release 자동 확인 순서로 처리합니다.

| Jenkins 작업 | 유지할 Script Path |
| --- | --- |
| SkinAI-UI-CI | Jenkinsfile |
| SkinAI-Backend-CI | ci/backend_contract/Jenkinsfile |
| SkinAI-Workflow-CI | ci/ui_workflow/Jenkinsfile |
| SkinAI-Release-CI | ci/release/Jenkinsfile |

세 검사 작업의 Poll SCM `H/5 * * * *`와 Release의 성공 후 자동 시작 조건은 유지합니다.
UI의 Poll SCM은 Jenkins 화면에 설정되어 있으므로 브랜치를 바꿀 때도 그대로 둡니다.

기존 CI 브랜치의 성공 번호를 main의 성공 근거로 재사용하지 않습니다.
기존 두 서버 CI·CD 작업과 포트·복구 기록은 전환 대상이 아닙니다.

## 1. 터미널에서 이미지 검사

Windows에서 Docker Desktop의 Linux 컨테이너, Python, Node.js,
Playwright Chromium, 검증된 모델 폴더와 비개인용 샘플 사진을 준비합니다.
18165~18167 포트를 비워 둡니다. Workflow CI와 이미지 검사는 공통 잠금으로 순서대로 실행됩니다. 잠금은 최대 15분 기다립니다.

검사할 체크아웃의 프로젝트 최상위 폴더에서 터미널을 엽니다. 경로는 현재 PC에 맞게 바꿉니다.
업로드할 때는 main 전환을 마친 체크아웃과 같은 커밋의 세 CI 성공 기록을 사용합니다.
결과 폴더는 실행마다 새로 지정합니다.

```powershell
# ci 폴더가 보이는 프로젝트 최상위 폴더에서 실행합니다.
git branch --show-current
$previewOutput = Join-Path 'D:\SkinAI_DevOps\release_preview' ('run-' + [guid]::NewGuid().ToString('N'))
& 'D:\miniconda3\python.exe' -B '.\ci\release\prepare_preview.py' `
  --output $previewOutput `
  --models 'D:\SkinAI_DevOps\ensemble_docker_check\models' `
  --sample 'D:\SkinAI_DevOps\backend_ensemble_check\samples\sample.png' `
  --docker 'C:\Users\human\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --node-dir 'D:\SkinAI_DevOps\tools\node-v24.22.2-win-x64' `
  --browsers 'D:\SkinAI_DevOps\playwright-browsers'
```

모델 파일 확인 → 4개의 이미지 빌드 → 임시 서버 시작 → 사진 2장·3장 접수 →
분석 → 의사 확정 → 환자 조회 → 임시 서버·데이터 정리 순서입니다.
호스트 소스·모델을 연결하지 않고 이미지 안의 파일로 검사합니다.
UI의 /api 연결, 오류 응답과 준비 상태도 확인합니다.

- candidate.json: 로컬 이미지 ID, 소스·모델 근거. 배포용 파일이 아닙니다.
- results/preview-summary.json: 전체 결과, 기존 컨테이너 보존, 정리 결과.
- results/workflow-2-photos.json, workflow-3-photos.json: 연결 검사 결과.
- compose.preview.json: 임시 실행 설정. 실제 CD에 그대로 적용하지 않습니다.

원본 로그에는 테스트 접수 번호 등이 남으므로 전달 자료와 구분합니다.

## 2. 검사한 이미지 업로드

SkinAI-UI-CI, SkinAI-Backend-CI, SkinAI-Workflow-CI가 main의 같은 커밋에서
모두 SUCCESS여야 합니다. 아래 번호는 실제 성공 번호로 바꿉니다.
서로 다른 커밋의 최근 성공 번호를 조합하지 않습니다.
Docker CLI에는 rlarns982 계정으로 로그인해 둡니다.

```powershell
$publishOutput = Join-Path 'D:\SkinAI_DevOps\release_publish' ('run-' + [guid]::NewGuid().ToString('N'))
& 'D:\miniconda3\python.exe' -B '.\ci\release\publish.py' `
  --run $previewOutput --output $publishOutput `
  --docker 'C:\Users\human\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --jenkins-home 'D:\JenkinsHome' `
  --ui-build <UI성공번호> --backend-build <Backend성공번호> --workflow-build <Workflow성공번호> `
  --publish
```

`--publish`를 빼면 업로드 전 조건만 검사합니다. 실행마다 새 결과 폴더가 필요합니다.
이 도구는 현재 PC의 Jenkins 완료 기록을 읽습니다. Jenkins에서는 위 자동 업로드 작업이 검사 번호와 실행 순서를 관리합니다.

기본값은 네 저장소가 이미 Public으로 확인되어야 업로드합니다.
승인된 최초 생성에 한해 `--create-missing-repositories`를 추가할 수 있습니다.
Docker Hub 기본 설정으로 생성된 저장소가 Public이 아니면 최종 파일을 만들지 않습니다.
비공개 저장소의 존재·태그는 익명 조회로 확인할 수 없으므로 최초 생성 옵션은
새 이름과 새 커밋의 첫 업로드에만 사용합니다.

태그는 sha-커밋12자리-workflow-검사번호입니다. 기존 공개 태그는 동일한 이미지일 때만
재사용합니다. 저장소 자체의 태그 불변성이나 동시 업로드 잠금은 이 도구가 설정하지 않습니다.

업로드 뒤 로그인 없이 접근 가능한지, 원격 digest, 플랫폼, 소스 커밋과
검사한 이미지의 일치를 확인합니다. 모두 통과해야 release.json을 만듭니다.
실패 시 일부 이미지가 올라갔을 수 있으니 publication_report.json을 확인합니다.
최종 release.json이 없으면 CD로 전달하지 않습니다.

## 3. CD 전달

release.json은 4개의 이미지에 대한 고정 주소와 커밋, 세 CI 성공 번호를 담습니다.
기존 central/ai-mock용 파일과 구조가 다르므로 기존 CD에 넣지 않습니다.
CD는 별도 실행 설정, 데이터 보존·백업·복구를 준비합니다.
배포 후 사진 접수 → 분석 → 의사 확정 → 환자 조회를 확인합니다.
배포·연결 실패는 이전 정상 이미지로 복구하며, DB·사진 복구는 별도로 관리합니다.
현재 의사 인증은 시연 토큰 방식이며, 이 검사는 모델의 의학적 정확도 평가가 아닙니다.

## 중단된 임시 실행 정리

```powershell
& 'D:\miniconda3\python.exe' -B '.\ci\release\prepare_preview.py' `
  --cleanup --output $previewOutput `
  --docker 'C:\Users\human\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
```

소유 정보가 일치하는 이번 임시 자원만 정리하며 기존 CD 데이터는 정리하지 않습니다.