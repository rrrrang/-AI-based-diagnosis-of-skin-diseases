백엔드 기준 CI 검사

검사 코드는 ci/two-server-lab 브랜치에 보관합니다.
검사 대상은 main의 실제 백엔드 코드입니다. main에 이 검사 파일을 올리지 않아도 실행할 수 있습니다.
검증 기준: main 759f8bd (2026-11-13). 백엔드·UI 원본과 기존 서버 CI/CD는 수정하지 않습니다.

1. 검사 내용
- 기존 백엔드 접수·권한·작업 큐: 7개
- 기존 앙상블 판단 정책: 1개
- 실제 HTTP 접수·인증·사진·소견 공개·재시작: 17개
합계 25개. 별도로 검사 실패를 제대로 차단하는지 확인하는 test_runner.py 9개.

정상과 판단 보류 모두 의사가 검토할 수 있어야 합니다.
환자에게 AI 분석과 의사의 임시 소견이 보이면 실패합니다.
의사 확정 후에만 확정 소견이 보이고, 이후 임시 수정은 기존 공개 결과를 바꾸면 안 됩니다.
담당 의사별 목록 분리, 다른 환자·의사의 사진/분석 접근 차단도 검사합니다.
AI 결과는 합성 값이며 실제 모델 가중치·정확도 검사는 아닙니다.

2. 파일 역할
run_checks.py: 백엔드 → 정책 → HTTP 순서로 실행, 실패하면 중단하고 결과 기록
check_http.py: 별도 DB·사진·토큰과 임시 API 서버로 요청/응답 검사
test_runner.py: 0개 검사, 건너뛴 검사, 실패 결과가 통과하지 못하는지 검사
requirements-ci.txt: 이번에 검증한 Python 패키지 버전 고정
Jenkinsfile: 별도 Jenkins 작업에서 코드 받기 → 환경 설치 → 실패 차단 검사 → 백엔드 검사
README_검사안내.txt: 실행 방법과 남은 작업

3. 현재 PC에서 실행 (PowerShell)
아래 두 폴더는 서로 다릅니다. CI 폴더에는 검사 코드, backend 폴더에는 검사할 서버 코드가 있습니다.

$ciRoot = 'D:\SkinAI_DevOps\skinai_team_project'
$backendRoot = 'D:\SkinAI_DevOps\backend_ci_main_check_20261113'
$ciPython = 'D:\SkinAI_DevOps\backend_contract_env_20261113\Scripts\python.exe'
& $ciPython -B -X utf8 "$ciRoot\ci\backend_contract\run_checks.py" --source-root $backendRoot --output-root 'D:\SkinAI_DevOps\backend_contract_results'
$LASTEXITCODE

정상: 7개 OK → 1개 OK → 17개 OK → RESULT: PASS, 종료 코드 0
실패: RESULT: FAIL, 종료 코드 1. 다음 검사로 진행하지 않습니다.
검사가 0개이거나, 기준보다 적게 실행되거나, skip/예상 실패가 있어도 실패합니다.

검사기 자체의 실패 차단 확인:
& $ciPython -B -X utf8 "$ciRoot\ci\backend_contract\test_runner.py"
$LASTEXITCODE
정상: 9개 OK, 종료 코드 0

4. 다른 PC에서 준비
- Python 3.14로 검증했습니다. 실제 AI 모델용 환경과 따로 만듭니다.
- ci/two-server-lab 브랜치와 main 브랜치를 서로 다른 폴더에 내려받습니다.
- 아래 ciRoot/backendRoot/ciPython 경로를 해당 PC에 맞게 바꿉니다.
- 기존 폴더 위에 덮어쓰지 말고 새 경로를 사용합니다.

git clone --branch ci/two-server-lab --single-branch https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases.git D:\SkinAI_CI_Check\checks
git clone --branch main --single-branch https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases.git D:\SkinAI_CI_Check\backend
python -m venv D:\SkinAI_CI_Check\venv
& 'D:\SkinAI_CI_Check\venv\Scripts\python.exe' -m pip install -r 'D:\SkinAI_CI_Check\checks\ci\backend_contract\requirements-ci.txt'
& 'D:\SkinAI_CI_Check\venv\Scripts\python.exe' -m pip check

설치와 pip check가 성공하면 3번 명령의 경로를 이 폴더로 바꿔 실행합니다.
main이 이후 수정되면 summary.json의 source_commit으로 실제 검사한 코드를 확인합니다.
requirements-backend.txt가 바뀌면 CI 패키지 버전 목록도 재검증합니다.

5. 결과와 격리
--output-root 아래 실행일시_번호 폴더에 summary.json, backend.log, policy.log, http.log를 기록합니다.
HTTP 상세 결과는 http/http-results.json, 서버 기록은 http/server.log입니다.
검사마다 별도 DB·합성 사진·무작위 토큰을 사용합니다. DB/사진/토큰을 Git에 올리지 않습니다.
빈 로컬 포트를 자동 선택하고 자신이 시작한 API 서버만 종료합니다.
이미 사용 중인 포트를 지정하면 기존 서버를 건드리지 않고 실패합니다.
검사 파일 해시와 백엔드 커밋을 결과에 기록합니다.
Jenkins 보관 대상도 위 JSON·로그만 사용하며 DB·사진·가상환경은 제외합니다.

6. Jenkins 연결
- 작업 이름: SkinAI-Backend-CI (Pipeline)
- Definition: Pipeline script from SCM / SCM: Git
- Repository URL: https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases.git
- Branch: */ci/two-server-lab
- Script Path: ci/backend_contract/Jenkinsfile
- 처음에는 지금 빌드로 실행합니다. 이후 약 5분 간격으로 CI 브랜치와 main 변경을 확인합니다.
- D드라이브의 Windows 작업 폴더와 Python 3.14를 사용합니다.
  기본 Python은 D:/miniconda3/python.exe이며, 다른 PC에서는 CI_PYTHON_EXE 환경변수로 지정합니다.
- 빌드마다 별도 가상환경을 만들고 실패 차단 9개 + 백엔드 25개를 실행합니다.
- SUCCESS는 34개 검사가 모두 통과했다는 뜻입니다. 실패하면 다음 단계로 진행하지 않습니다.
- 결과는 Jenkins의 Artifacts에서 확인합니다. revisions.txt에 두 브랜치의 실제 커밋을 남깁니다.
- 검사 실패 시에도 생성된 JSON·로그를 보관합니다. 실제 모델 성능을 평가하는 작업은 아닙니다.

7. 적용 범위와 남은 작업
- 기존 서버 CI 작업은 이 브랜치의 변경을 감지해 원래 검사를 실행할 수 있습니다.
  기존 Docker 업로드와 CD 연결 설정을 이 패키지에서 바꾸지 않습니다.
- 새 검사는 Docker 이미지, release.json을 생성하거나 배포하지 않습니다.
- UI 수정본을 받은 뒤 화면 검사를 변경합니다. 아직 현재 UI 검사 기대값을 바꾸지 않습니다.
  정면 사진 누락 차단은 유지, 접수 시 부위 사진·증상·기간 생략은 허용.
  분석 요청에는 부위 사진이 필요. JPG/PNG, 8 MiB, 1,600만 픽셀 제한 확인.
  입력·접수·토큰 전달·의사 확정 전후 표시를 실제 화면과 함께 확인합니다.
- 실제 3개 모델 로딩·워커 기동·실제 사진 분석은 별도 검사입니다.
- 다른 PC의 네트워크 접속, 실제 환자 진료 성능 검증은 이 결과에 포함되지 않습니다.
