SkinAI 두 서버 CD 실습

목적
CI가 전달한 중앙 서버와 모의 AI 이미지를 Docker Compose로 실행하고
중앙 서버에서 모의 AI까지 샘플 요청과 응답이 오가는지 확인합니다.

파일 역할
cd.py              릴리스 검사, 이미지 다운로드, 실행, 상태, 로그, 종료, 복구
compose.cd.yaml    중앙 서버와 모의 AI 실행 설정
release.json       빌드 9 실습용 인수물
smoke_test.py      스모크 테스트만 실행
requirements.txt  CD 도구에 필요한 Python 패키지
.gitignore        로컬 실행 기록과 캐시 제외

실행 환경
Python, Docker Desktop Linux 컨테이너, Docker Compose를 사용합니다.
프로젝트 이름은 skinai-cd-lab이고 중앙 서버는 127.0.0.1:18130을 사용합니다.
기존 CD 실습이 같은 프로젝트 이름으로 실행 중이면 같은 컨테이너를 제어합니다.

실습 순서
python -m pip install -r requirements.txt
python cd.py check    릴리스와 Compose 설정 검사
python cd.py pull     지정된 이미지 다운로드
python cd.py up       설정 검사, 다운로드, 실행, 준비 대기, 스모크, 성공 기록
python cd.py status   컨테이너 상태와 성공 기록 확인
python cd.py smoke    /health와 /analyze 요청 확인
python cd.py logs     최근 로그 확인
python cd.py down     실습 컨테이너와 네트워크 종료
python cd.py rollback 이전 정상 릴리스 복구

성공과 실패
컨테이너가 준비되고 스모크 테스트까지 통과하면 .cd-state에 성공 릴리스를 기록합니다.
실패하면 logs와 status로 원인을 확인합니다. rollback에는 기록된 정상본이 필요합니다.
기존 폴더에서 실행한 성공 기록은 해당 폴더의 .cd-state에 있습니다.
이 폴더에서 up을 실행하면 이 폴더에 별도의 성공 기록을 생성합니다.

새 빌드 받기
Jenkins 성공 빌드에서 release.json을 받습니다. compose.cd.yaml의 central과
ai-mock image를 새 릴리스에 적힌 주소로 갱신하고 check부터 실행합니다.
