사진 접수 규칙 및 백엔드 CI 검사

1. 새 사진 규칙
- photo0: 얼굴 전체 정면 사진 1장 필수
- photo1: 첫 번째 근접 부위 사진 1장 필수
- photo2: 추가 근접 부위 사진 1장 선택
- 최소 2장, 최대 3장. photo2만으로 photo1을 대신할 수 없습니다.
- 필수 사진 누락, 중복 사진 필드, photo3 등 추가 파일은 422로 차단합니다.
- 잘못된 접수는 접수 정보·사진·분석 작업을 저장하지 않습니다.
- API의 증상·기간·설명 선택 입력 정책은 유지합니다.

2. 검사 범위
- 백엔드 단위 검사: 17개 (접수·권한·작업 큐·새 사진 규칙)
- 앙상블 판단 정책: 1개
- 별도 HTTP 서버 검사: 20개
- 별도 Docker HTTP 검사: 8개
- 검사기 자체의 실패 차단 확인: 9개
정상·판단 보류 결과 모두 의사 확정 전에는 환자에게 공개하지 않습니다.
의사 임시 소견, 다른 환자·의사 접근 차단과 재시작 후 자료 유지도 확인합니다.
합성 사진과 모의 모델 결과로 API 동작을 검사하며 실제 모델 정확도 평가는 아닙니다.

3. 현재 PC에서 실행 (PowerShell)
$ciRoot = 'D:\SkinAI_DevOps\photo_intake_ci'
$ciPython = 'D:\SkinAI_DevOps\backend_contract_env_20261113\Scripts\python.exe'
& $ciPython -B -X utf8 "$ciRoot\ci\backend_contract\test_runner.py"
& $ciPython -B -X utf8 "$ciRoot\ci\backend_contract\run_checks.py" --source-root $ciRoot --output-root 'D:\SkinAI_DevOps\photo_intake_results'
$LASTEXITCODE

정상: 각 검사 OK, RESULT: PASS, 종료 코드 0.
실패·누락·건너뛴 검사는 통과하지 못하며 다음 단계로 진행하지 않습니다.
결과 폴더에 summary.json과 검사 로그가 남습니다. DB·사진·토큰은 공유하지 않습니다.

4. Jenkins 연결 준비
이 브랜치는 ci/photo-intake-contract입니다. 서버 코드와 CI 코드를 동일한 커밋에서 검사합니다.
main을 따로 가져오지 않으므로 새 검사 기준을 이전 서버 코드에 잘못 적용하지 않습니다.
- Definition: Pipeline script from SCM / SCM: Git
- Repository URL: https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases.git
- Branch: */ci/photo-intake-contract
- Script Path: ci/backend_contract/Jenkinsfile
- D드라이브 작업 폴더의 Windows Jenkins, Python 3.14, Linux 모드 Docker 사용
- 기본 Python: D:/miniconda3/python.exe (CI_PYTHON_EXE로 변경 가능)
- 브랜치 업로드와 Jenkins 작업 설정 변경은 별도 작업입니다. 이 파일 수정만으로 기존 Jenkins가 바뀌지는 않습니다.
- 약 5분 간격 변경 감지, 필수 검사 통과 여부와 로그 보관을 수행합니다.
- Docker 검사는 임의의 localhost 포트와 전용 컨테이너를 사용한 뒤 정리합니다.
- Docker Hub 업로드·release.json 작성·CD 배포는 하지 않습니다.

5. 파일 역할
Jenkinsfile: 같은 커밋 받기 → 환경 준비 → 검사 → Docker 검사·정리
run_checks.py: 백엔드·정책·HTTP 검사를 순서대로 실행하고 결과 검증
check_http.py: 별도 API 서버로 사진 접수·권한·공개·재시작 검사
run_container_checks.py: 임시 Docker 이미지/컨테이너 생성·검사·정리
test_container_http.py: 실행 중인 검사 전용 Docker API에 HTTP 요청
test_runner.py: 검사 실패나 미실행이 성공으로 처리되지 않는지 확인
requirements-ci.txt: CI용 패키지 버전

실제 3개 모델 추론, 환자 브라우저 동작, 다른 PC 접속 검증은 별도 결과로 확인합니다.
