# 피부질환 AI 프로젝트 CI 테스트 안내서

`ci/two-server-lab` 브랜치의 **저장소 최상위 폴더**에서 아래 명령을 실행합니다.

| 담당 | 테스트 역할 |
| --- | --- |
| CI 담당 | 저장소에 포함된 합성 테스트 자료로 자동 검사를 실행하고 Jenkins 결과를 확인합니다. |
| 백엔드 연동 담당 | 테스트 서버에서 받은 AI 분석 응답과 환자 결과 응답을 준비합니다. 분석 작업 ID, 접수 번호, 실제 HTTP 상태 코드도 함께 기록합니다. |
| 데이터 전처리 및 AI 모델 설계 담당 | 모델 파일, 설정 파일, 가중치 SHA-256 확인값을 제공합니다. 실제 추론 검증에 사용할 실행 명령과 검사 샘플도 준비합니다. |

## 로컬 자동 검사

Python 3.10 이상에서 실행합니다. 이 검사는 합성 자료를 사용하므로 모델 파일이나 Docker가 없어도 됩니다.

```powershell
python -B -X utf8 -m unittest discover -s ci -p "test_*.py" -v
```

응답 형식 검사 7개와 모델 파일 검사 8개가 모두 통과하면 마지막에 **`Ran 15 tests`와 `OK`**가 표시됩니다. CI 실행 PC에서 `python` 명령을 찾지 못하면 `D:\miniconda3\python.exe`를 사용합니다.

## 백엔드 연동 응답 검사

합성 사진과 문진으로 접수한 뒤, 두 응답의 JSON 본문을 저장소 밖에 각각 저장합니다. 아래 경로와 ID는 예시입니다.

**AI 분석 응답**은 요청에 사용한 작업 ID와 승인된 모델 버전·전처리 버전·라벨 목록을 기준으로 검사합니다.

```powershell
python -B ci/check_responses.py inference "D:/ci-input/ai-response.json" --job-id JOB_EX_001 --model-version test-v1 --preprocess-version prep-test --labels class_a class_b
```

- `CANDIDATES`이면 후보가 한 개 이상 있어야 합니다. 각 라벨은 허용 목록에 있고 중복되지 않아야 하며, 점수는 높은 순서로 정렬되어야 합니다.
- `HOLD`이면 후보 목록은 비어 있고 허용된 보류 사유가 있어야 합니다.

**환자 결과 응답**은 테스트에 사용한 접수 번호와 실제로 관찰한 HTTP 상태 코드를 넣습니다.

```powershell
python -B ci/check_responses.py patient "D:/ci-input/patient-response.json" --case-id CASE_EX_001 --status 200
```

| 테스트 요청 | 예상 응답 |
| --- | --- |
| 본인이 의사 확정 후 조회 | `200`. 접수 정보와 의사가 확정한 텍스트만 반환합니다. 사진 주소, AI 후보 또는 LLM 초안이 들어가면 검사가 실패합니다. |
| 본인이 확정 전에 조회 | `409`와 `RESULT_NOT_READY` |
| 다른 환자 계정으로 조회 | `403`과 `FORBIDDEN` |

권한 검사는 테스트 서버에 각 계정으로 직접 요청해 확인합니다. 그런 다음 해당 요청에서 저장한 JSON과 상태 코드를 검사기에 넣습니다. 테스트 사진·응답 파일과 인증 토큰은 Git에 올리지 않습니다.

## 모델 패키지 검사

기본 구성은 가중치 `model.pt`와 설정 파일 `model_config.json`, `preprocess.json`, `classes.json`, `manifest.json`입니다. 모델 폴더는 저장소 밖에 두고, **데이터 전처리 및 AI 모델 설계 담당이 별도로 제공한 64자리 SHA-256**을 아래 명령에 넣습니다.

```powershell
python -B ci/check_model_package.py "D:/ci-input/approved-model" --weights-sha256 "전달받은_64자리_SHA256"
```

설정 파일 4개를 읽을 수 있고 내용이 비어 있지 않으며 가중치 확인값이 일치하면 통과합니다. 가중치 파일 이름이 다르면 `--weights-file model.onnx`처럼 지정합니다. 실제 모델 로딩, 라벨 번호와 질환 이름의 대응, 추론 성능은 승인된 샘플로 별도 검증합니다.

## Jenkins 자동 검사

`SkinAI-Two-Server-CI`는 약 5분마다 브랜치의 새 커밋을 확인합니다. 로컬과 같은 15개 검사를 실행한 뒤 중앙 서버와 임시 AI 서버 이미지를 만들고, 두 서버의 연결·장애·복구 검사 7개를 실행합니다. 검사가 모두 통과하면 두 이미지를 Docker Hub에 올리고 성공한 빌드에 `release.json`을 보관합니다.

실제 모델 패키지도 검사할 때는 CI 담당이 Jenkins 실행 노드에 아래 환경변수를 설정합니다.

| 환경변수 | 설정값 |
| --- | --- |
| `CI_MODEL_DIR` | Jenkins가 읽을 수 있는 모델 폴더 경로 |
| `CI_MODEL_WEIGHTS_SHA256` | 전달받은 가중치 확인값 |
| `CI_MODEL_WEIGHTS_FILE` | 가중치 파일명이 `model.pt`와 다를 때 지정 |

세 값이 모두 비어 있으면 모델 패키지 검사만 건너뜁니다. 설정할 때는 폴더와 확인값을 함께 입력합니다. 둘 중 하나가 빠지거나 파일 검사가 실패하면 이미지 빌드 전에 중단합니다. 코드 변경 없이 설정만 바꿨을 때는 **Build Now**로 실행합니다.

Jenkins 접속 주소는 CI 실행 PC의 `http://127.0.0.1:8080`입니다. 자동 검사를 실행하는 동안 해당 PC와 Docker Desktop, Jenkins가 켜져 있어야 합니다. 재시작할 때는 Docker Desktop을 먼저 켠 뒤 `D:\SkinAI_DevOps\jenkins\Start-Jenkins.cmd`를 실행합니다.
