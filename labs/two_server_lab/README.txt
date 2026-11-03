SkinAI 두 서버 CI 실습

목적
중앙 FastAPI 서버가 임시 AI 서버에 요청하고, 장애와 복구를 처리하는지 검사합니다.
임시 AI 서버는 실습용 입력을 받아 그대로 돌려줍니다. 실제 모델, 피부 사진 분석, 환자 정보 저장,
의사 검토 기능, 운영 배포는 추후 실제 서비스를 연결할 때 다룹니다.
CI는 검사에 성공한 중앙 서버와 임시 AI 서버 이미지를 Docker Hub에 올립니다.

실습 흐름
Git 코드 가져오기 -> 합성 응답·모델 파일 검사 도구의 자동 테스트
-> 모델 패키지를 지정한 경우 실제 파일 인수 검사 -> 두 Docker 이미지 빌드 -> 별도 테스트 서버 실행
-> 정상 연결 검사 -> 임시 AI 중지 및 503 응답 검사 -> AI 재시작 및 복구 검사
-> 통과하면 두 이미지 업로드 -> 테스트 서버 정리 -> 성공한 빌드에 release.json 보관
새 검사와 팀원 실행 방법은 저장소 루트의 ci/README.md에 있습니다.

이 실습 폴더의 파일 역할 (11개)
Jenkinsfile                 Jenkins가 실행하는 CI 순서
compose.ci.yaml              이번 빌드의 이미지로 별도 테스트 서버 실행
test_recovery.py             데이터 전달·입력 검증·장애·복구 자동검사
central/central_server.py    중앙 API의 /health 및 /analyze
ai_mock/mock_ai_server.py    실제 AI 대신 응답하는 임시 서버
central/Dockerfile           중앙 서버 이미지 정의
ai_mock/Dockerfile           임시 AI 이미지 정의
requirements.txt            서버 패키지 버전
.dockerignore               Docker 빌드에 불필요한 파일 제외
.gitignore                  Git에 환경설정·임시 파일이 올라가지 않도록 제외
README.txt                  CI 연결 및 검사 안내

Jenkins 연결
작업: SkinAI-Two-Server-CI
Definition: Pipeline script from SCM
SCM: Git
Repository URL: https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases.git
Credentials: 공개 저장소 읽기는 선택하지 않아도 됩니다.
Branch Specifier: */ci/two-server-lab
Script Path: labs/two_server_lab/Jenkinsfile
Jenkins는 Poll SCM으로 ci/two-server-lab 브랜치를 5분마다 확인하고, 새 커밋이 있으면 빌드를 시작합니다.

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

CI 실행 환경
프로젝트: skinai-two-server-ci-빌드번호
중앙 서버: 127.0.0.1:18120 / 임시 AI: Docker 내부 통신만 사용
Jenkins CI가 쓰는 18120 포트를 다른 작업과 함께 사용하지 않습니다.
같은 Jenkins 작업의 동시 실행을 막았으며, 다른 작업까지 잠그는 설정은 아닙니다.

검사 실행
자동 빌드에서 두 서버를 실행해 검사하고, 통과하면 두 이미지를 Docker Hub에 업로드한 뒤 테스트 환경을 정리합니다.
Jenkins가 TEST_PROJECT_NAME, IMAGE_TAG, TEST_COMPOSE_FILE, TEST_BASE_URL,
DOCKER_EXE를 설정합니다.
test_recovery.py는 CI 전용 검사입니다. TEST_PROJECT_NAME이 없으면 즉시 중단합니다.
기본 Compose 파일은 compose.ci.yaml, 기본 중앙 서버 주소는 http://127.0.0.1:18120입니다.
수동 실습 파일은 이 CI 폴더에서 제외했으며, 기존 개인 실습 폴더에 보관합니다.

데이터 검사
실제 사진이나 환자 정보 없이 아래 가짜 JSON으로 전달 과정을 검사합니다.
{"sample_id": "ci-case-001", "sample_text": "한글 연결 검사용 가짜 데이터입니다."}
sample_id: 이번 실습 요청을 구분하는 문자열 (1~64자)
sample_text: 그대로 전달할 테스트 문장 (1~200자)
두 항목은 이 실습에서만 사용하는 임시 규격이며, 팀의 최종 의료 API 규격이 아닙니다.
중앙 서버가 받은 값을 임시 AI에 보내면 임시 AI는 received 항목에 돌려줍니다.
실제 사진 분석이나 질환 분류는 수행하지 않습니다.
현재 /analyze는 위 JSON이 필요하므로 내용 없는 POST는 422로 거절합니다.

자동검사 7개
1. 서로 다른 가짜 데이터 2개가 중앙 서버 -> AI -> 중앙 서버를 거쳐 그대로 전달되는지
2. 요청 본문이 없으면 422로 거절하는지
3. 필수 항목이 빠지면 422로 거절하는지
4. 숫자 입력·빈 문자열·길이 초과를 422로 거절하는지
5. 약속하지 않은 항목이 들어오면 422로 거절하는지
6. 잘못된 HTTP 방법(GET)이면 405로 거절하는지
7. AI 중지 시 503, 중앙 서버 자체는 200 유지, AI 재시작 후 데이터 전달 복구
이 7개는 test_recovery.py에서 두 컨테이너를 대상으로 실행합니다. 저장소 루트의 ci/ 검사는 별도로 실행합니다.

검사 의미
중앙 서버 /health = 200: 중앙 서버 자체가 응답합니다.
올바른 JSON을 보낸 중앙 서버 /analyze = 200: 임시 AI와 연결됩니다.
임시 AI 중지 후 /analyze = 503: 연결 실패를 정해진 응답으로 처리합니다.
이때 중앙 서버 /health는 200을 유지합니다.
임시 AI 복구 후 /analyze = 200: 통신이 복구됩니다.
통신 검사 통과가 실제 모델 성능이나 의료적 유효성을 뜻하지 않습니다.

정리
검사가 실패해도 post always에서 해당 빌드의 테스트 서버 정리를 시도합니다.
Jenkins 프로세스나 Docker 엔진 자체가 강제 종료되면 정리가 남을 수 있습니다.
이미지는 자동 삭제하지 않습니다. 운영 서버를 교체하는 배포 단계는 없습니다.


