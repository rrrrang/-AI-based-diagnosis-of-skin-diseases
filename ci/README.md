# 피부질환 프로젝트 CI 



저장소의 `ci/two-server-lab` 브랜치를 연 뒤, **저장소 루트** 터미널에서 실행하세요. Python 3.10 이상이면 됩니다. 패키지 설치, 학습 데이터, Docker, Jenkins 로그인 없이 실행할 수 있습니다.

```powershell
python -B -X utf8 -m unittest discover -s ci -p "test_*.py" -v
```

동현 PC에서 `python` 명령을 찾지 못하면 `D:\miniconda3\python.exe`로 바꿉니다. 마지막 줄이 `OK`이면 합성 응답과 파일을 대상으로 검사 도구가 기대대로 동작한 것입니다.

| 언제 | 누가 준비할 것 | CI에서 확인하는 것 |
| --- | --- | --- |
| 지금 | 저장소의 합성 예시 | 후보·판단 보류, 버전·작업 ID, 환자 응답 필드, 파일 누락·변경을 올바르게 판별하는지 |
| 3번의 API가 준비되면 | 테스트 계정으로 보낸 요청의 ID와 실제 받은 HTTP 상태·JSON | 동일한 검사기에 그 응답을 넣어 v1 규칙과 비교 |
| 1·2번의 모델이 준비되면 | 모델 폴더, 팀이 별도로 제공한 가중치 SHA-256, 클래스·전처리 규격, 실행 명령과 승인 샘플 | 먼저 필수 파일과 가중치 일치 여부 검사. 다음으로 실제 로딩·샘플 추론을 모델팀 명령으로 연결 |

## 3번의 첫 응답 받기

**합성 사진·문진을 쓴 테스트 접수**로 받은 JSON 본문을 저장소 밖에 저장하세요. 아래의 경로·ID·버전·라벨은 예시이므로 실제 테스트 요청과 승인 패키지 값으로 교체합니다.

```powershell
python -B ci/check_responses.py inference "D:/ci-input/ai-response.json" --job-id JOB_EX_001 --model-version test-v1 --preprocess-version prep-test --labels class_a class_b
python -B ci/check_responses.py patient "D:/ci-input/patient-response.json" --case-id CASE_EX_001 --status 200
```

- AI가 `HOLD`를 응답하면 후보는 빈 목록이고 허용된 보류 사유가 있어야 합니다. `CANDIDATES`는 허용 라벨·중복·점수 순서·모델 및 전처리 버전을 검사합니다.
- 환자 조회는 확정된 텍스트와 허용 필드만 검사합니다. 미확정 조회와 다른 환자 조회는 실제로 받은 응답 본문과 각각의 HTTP 상태 `409`, `403`을 넣습니다.
- 검사기는 저장한 응답만 읽습니다. 접근 통제 자체는 3번의 테스트 서버에서 소유자·타인 계정으로 각각 호출해 확인합니다.

## 모델 파일 받기

모델 폴더를 Git 밖에 둡니다. 기본 구성은 `model.pt`, `model_config.json`, `preprocess.json`, `classes.json`, `manifest.json`입니다. 가중치 확인값은 **모델을 보낸 팀원에게 별도로** 받습니다.

```powershell
python -B ci/check_model_package.py "D:/ci-input/approved-model" --weights-sha256 "여기에_팀원이_준_64자리_확인값"
```

가중치 파일명이 다르면 `--weights-file model.onnx`처럼 지정합니다. 성공은 필수 JSON 네 개가 비어 있지 않고 읽히며 가중치가 전달본과 일치한다는 뜻입니다. 라벨 번호·이름 대응, 설정 파일 내용의 정확성, 실제 로딩·추론 및 성능은 승인 샘플을 받으면 검증합니다. 사진·모델 파일·토큰·환자 응답은 Git에 넣지 않습니다.

## Jenkins에서 이어서 실행

- `SkinAI-Two-Server-CI`가 `ci/two-server-lab`의 새 커밋을 약 5분 간격으로 확인합니다. 합성 자료 검사 후 Docker 이미지 두 개를 만들고 기존 7개 연결 검사를 실행합니다. 필수 검사 실패 시 업로드와 새 릴리스 보관을 중단합니다.
- 실제 모델을 **Jenkins에서도** 검사하려면 Jenkins 실행 노드 환경에 `CI_MODEL_DIR`(Jenkins가 읽을 수 있는 폴더)와 `CI_MODEL_WEIGHTS_SHA256`(팀에서 준 값)을 함께 설정합니다. `CI_MODEL_WEIGHTS_FILE`은 파일명이 다를 때만 설정합니다. 처음에는 위 수동 명령으로 경로와 값을 확인하세요. 설정 후 코드 변경이 없으면 **Build Now**로 검사합니다.
- 모델 설정이 전부 비어 있으면 **모델 파일 인수 검사** 단계만 건너뜁니다. 일부만 입력했거나 파일·확인값이 틀리면 그 빌드를 중단합니다. 이 단계가 통과해도 현재 발행되는 이미지는 여전히 중앙 서버와 임시 AI 서버입니다.
- Jenkins는 동현 PC의 `http://127.0.0.1:8080`에서 실행됩니다. 자동 검사 기간에는 PC가 깨어 있고 Docker Desktop과 Jenkins 실행 터미널이 켜져 있어야 합니다. 다른 PC에서는 첫 번째 명령으로 합성 검사를 직접 실행할 수 있습니다. 재시작이 필요하면 동현 PC에서 Docker Desktop을 먼저 켜고 `D:\SkinAI_DevOps\jenkins\Start-Jenkins.cmd`를 실행합니다.
- 동현이 돌아온 뒤 첫 통합 검사는 **합성 사진 접수 → 같은 번호로 상태 조회 → 분석 완료 또는 판단 보류 → 의사 확정 전·후 환자 조회** 순서입니다. 이때 실제 서버가 반환한 값과 검사 결과를 기록합니다.

