# 피부질환 AI 프로젝트 CI 테스트 안내서

## 다른 PC에서 처음 실행하기 (Windows)

이 검사는 CI 담당 PC에서 통과한 15개 테스트가 다른 팀원의 PC에서도 모두 통과하는지 확인하기 위해 실행합니다.

**1. GitHub에서 테스트 브랜치를 내려받습니다.**

 [테스트 브랜치 열기](https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases/tree/ci/two-server-lab)

**2. 압축을 풀고 프로젝트 폴더에서 터미널을 엽니다.**



**3. 테스트를 실행하고 결과를 확인합니다.**

터미널에 `python --version`을 입력해 Python 3.10 이상인지 확인한 뒤 아래 명령을 실행합니다.

```powershell
python -B -X utf8 -m unittest discover -s ci -p "test_*.py" -v
```

마지막에 **`Ran 15 tests`와 `OK`**가 나오면 통과입니다. Windows에서 `python` 명령을 찾지 못하면 `py -3 --version`으로 버전을 확인하고 위 명령의 첫 단어 `python`을 `py -3`로 바꿔 실행합니다.

## 담당별 준비

| 담당 | 할 일 |
| --- | --- |
| 백엔드 연동 담당 | 테스트 서버에서 받은 AI 분석 결과와 환자 조회 결과를 JSON으로 준비합니다. |
| 데이터 전처리 및 AI 모델 설계 담당 | 모델 파일, 설정 파일, 가중치 확인값(SHA-256), 검사 샘플을 준비합니다. |
| CI 담당 | [응답 검사](check_responses.py)와 [모델 파일 검사](check_model_package.py)를 실행하고 Jenkins 결과를 확인합니다. |

모델 패키지 검사는 `classes.json`의 라벨 번호가 건선 0, 아토피 1, 여드름 2, 정상 3, 주사 4, 지루 5와 일치해야 통과합니다.

## Jenkins 자동 검사

브랜치에 푸시하면 Jenkins가 자동으로 검사합니다. 기본 검사 15개와 서버 연결·복구 검사 7개를 통과하면 두 이미지를 Docker Hub에 올리고 `release.json`을 보관합니다.
