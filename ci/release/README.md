# 실제 서비스 이미지 빌드·검사·업로드

API, 실제 3모델 worker, 환자 UI, 의사 UI를 각각 이미지로 만듭니다.
기존 두 서버 CI·CD와 main은 변경하지 않습니다.

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

## 1. 이미지 검사

Windows에서 Docker Desktop의 Linux 컨테이너, Python, Node.js,
Playwright Chromium, 검증된 모델 폴더와 비개인용 샘플 사진을 준비합니다.
18165~18167 포트를 비워 둡니다. Workflow CI와 동시에 실행하지 않습니다.

프로젝트 최상위 폴더에서 실행하며, 경로는 현재 PC에 맞게 바꿉니다.
업로드할 때는 먼저 커밋·푸시하고 같은 커밋의 세 CI 성공을 확인합니다.
결과 폴더는 실행마다 새로 지정합니다.

```powershell
Set-Location 'D:\SkinAI_DevOps\photo_intake_ci'
$previewOutput = Join-Path 'D:\SkinAI_DevOps\release_preview' ('run-' + [guid]::NewGuid().ToString('N'))
& 'D:\miniconda3\python.exe' -B '.\ci\release\prepare_preview.py' `
  --output $previewOutput `
  --models 'D:\SkinAI_DevOps\ensemble_docker_check\models' `
  --sample 'D:\SkinAI_DevOps\backend_ensemble_check\samples\sample.png' `
  --docker 'C:\Users\human\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' `
  --node-dir 'D:\SkinAI_DevOps\tools\node-v24.22.2-win-x64' `
  --browsers 'D:\SkinAI_DevOps\playwright-browsers'
```

모델 파일 확인 → 네 이미지 빌드 → 임시 서버 시작 → 사진 2장·3장 접수 →
분석 → 의사 확정 → 환자 조회 → 임시 서버·데이터 정리 순서입니다.
호스트 소스·모델을 연결하지 않고 이미지 안의 파일로 검사합니다.
UI의 /api 연결, 오류 응답과 준비 상태도 확인합니다.

- candidate.json: 로컬 이미지 ID, 소스·모델 근거. 배포용 파일이 아닙니다.
- results/preview-summary.json: 전체 결과, 기존 컨테이너 보존, 정리 결과.
- results/workflow-2-photos.json, workflow-3-photos.json: 연결 검사 결과.
- compose.preview.json: 임시 실행 설정. 실제 CD에 그대로 적용하지 않습니다.

원본 로그에는 테스트 접수 번호 등이 남으므로 전달 자료와 구분합니다.

## 2. 검사한 이미지 업로드

SkinAI-UI-CI, SkinAI-Backend-CI, SkinAI-Workflow-CI의 같은 커밋이
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
이 도구는 현재 PC의 Jenkins 완료 기록을 읽으며, Jenkins 자동 실행에는 아직 연결하지 않았습니다.

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

release.json은 네 이미지의 고정 주소, 커밋, 세 CI 성공 번호를 담습니다.
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