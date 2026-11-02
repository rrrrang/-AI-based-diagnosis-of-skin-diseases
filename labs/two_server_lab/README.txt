SkinAI 두 서버 CI 실습

목적
중앙 FastAPI 서버가 임시 AI 서버에 요청하고, 장애와 복구를 처리하는지 검사합니다.
임시 AI 서버는 고정 응답만 반환합니다. 실제 모델, 피부 사진 분석, 환자 정보 저장,
의사 검토 기능, 운영 배포, 이미지 저장소 업로드는 구현하지 않았습니다.

실습 흐름
Git 코드 가져오기 -> 두 Docker 이미지 빌드 -> 별도 테스트 서버 실행
-> 정상 연결 검사 -> 임시 AI 중지 및 503 응답 검사 -> AI 재시작 및 복구 검사
-> 이번 빌드에서 사용한 테스트 서버 정리

파일 역할
Jenkinsfile                 Jenkins가 실행하는 CI 순서
compose.ci.yaml              이번 빌드의 이미지로 별도 테스트 서버 실행
test_recovery.py             정상 연결·장애 처리·복구 자동검사
central/central_server.py    중앙 API의 /health 및 /analyze
ai_mock/mock_ai_server.py    실제 AI 대신 응답하는 임시 서버
central/Dockerfile           중앙 서버 이미지 정의
ai_mock/Dockerfile           임시 AI 이미지 정의
requirements.txt            서버 패키지 버전
compose.yaml                수동 실습용 이미지 빌드 및 서버 실행
compose.test.yaml           수동 장애·복구 검사 환경
ai_mock/test_connection.py   수동 실습 서버(18100)의 정상 연결 검사

Jenkins 연결
작업: SkinAI-Two-Server-CI
Definition: Pipeline script from SCM
SCM: Git
Repository URL: https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases.git
Credentials: 공개 저장소 읽기는 선택하지 않아도 됩니다.
Branch Specifier: */ci/two-server-lab
Script Path: labs/two_server_lab/Jenkinsfile
처음에는 Build Now로 직접 시작합니다. 커밋 자동 감지 설정은 별도입니다.

실행 환경
이 Jenkinsfile은 Windows + Docker Desktop(Linux 컨테이너) 실습용입니다.
Docker 기본 경로: Jenkins 실행 계정의 LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe
Python 기본 경로: D:/miniconda3/python.exe
설치 위치가 다르면 Jenkins 실행 노드의 환경변수 CI_DOCKER_EXE, CI_PYTHON_EXE를 설정합니다.
Git도 Jenkins 실행 계정에서 사용할 수 있어야 합니다.
API는 Docker 안에서 실행하고, test_recovery.py는 Windows Python으로 실행합니다.
검사 스크립트 자체는 Python 표준 라이브러리만 사용합니다.

폴더와 버전
GitHub 저장소를 runs/빌드번호/source로 가져온 뒤 labs/two_server_lab에서 빌드·검사합니다.
Jenkinsfile의 checkout scm이 반환한 Git 커밋을 이미지 태그에 기록합니다.
예: sha-커밋앞12자리-build-빌드번호
테스트 중에는 이미지 재빌드 및 외부 이미지 pull을 하지 않습니다.

환경 구분
수동 실습: 프로젝트 skinai-two-server-lab / 중앙 18100 / 임시 AI 18101
수동 검사: 프로젝트 skinai-two-server-check / 중앙 18110
Jenkins CI: 프로젝트 skinai-two-server-ci-빌드번호 / 중앙 18120 / AI는 내부 통신만
Jenkins CI가 쓰는 18120 포트를 다른 작업과 함께 사용하지 않습니다.
같은 Jenkins 작업의 동시 실행을 막았으며, 다른 작업까지 잠그는 설정은 아닙니다.

수동 실습
터미널에서 저장소의 labs/two_server_lab 폴더로 이동한 뒤 실행합니다.
docker compose up -d --build
python ai_mock/test_connection.py

수동 장애·복구 검사
먼저 위 명령으로 practice 이미지가 있어야 합니다.
docker compose -p skinai-two-server-check -f compose.test.yaml up -d --no-build --wait
python test_recovery.py
docker compose -p skinai-two-server-check -f compose.test.yaml down --timeout 10

검사 의미
중앙 서버 /health = 200: 중앙 서버 자체가 응답합니다.
중앙 서버 /analyze = 200: 임시 AI와 연결됩니다.
임시 AI 중지 후 /analyze = 503: 연결 실패를 정해진 응답으로 처리합니다.
이때 중앙 서버 /health는 200을 유지합니다.
임시 AI 복구 후 /analyze = 200: 통신이 복구됩니다.
통신 검사 통과가 실제 모델 성능이나 의료적 유효성을 뜻하지 않습니다.

정리
검사가 실패해도 post always에서 해당 빌드의 테스트 서버 정리를 시도합니다.
Jenkins 프로세스나 Docker 엔진 자체가 강제 종료되면 정리가 남을 수 있습니다.
이미지는 자동 삭제하지 않습니다. 운영 서버를 교체하는 배포 단계는 없습니다.


