# 피부질환 AI 프로젝트 CI 테스트 안내서

## 다른 PC에서 처음 실행하기 (Windows)

**1. GitHub에서 테스트 브랜치를 내려받습니다.**

1. [테스트 브랜치 열기](https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases/tree/ci/two-server-lab)를 누릅니다. 파일 목록 위의 브랜치 이름이 `ci/two-server-lab`인지 확인합니다.
2. `main`이 보이면 브랜치 이름을 클릭하고 `ci/two-server-lab`을 검색해 선택합니다.
3. 파일 목록 위의 초록색 **Code** 버튼을 누르고 **Download ZIP**을 선택합니다.

**2. 압축을 풀고 프로젝트 폴더에서 터미널을 엽니다.**

1. 파일 탐색기의 **다운로드** 폴더에서 받은 ZIP을 우클릭하고 **모두 압축 풀기**를 선택합니다.
2. 압축을 푼 폴더를 엽니다. 안에 폴더가 하나만 보이면 한 번 더 들어갑니다. **`ci`와 `labs` 폴더가 나란히 보이는 위치**에서 멈춥니다.
3. 그 위치에서 파일 탐색기 위쪽의 **주소 표시줄**을 클릭하고 `powershell`을 입력한 뒤 **Enter**를 누릅니다. 현재 폴더에서 터미널이 열립니다.
4. 터미널에 `dir -Name`을 입력합니다. 목록에 `ci`와 `labs`가 모두 보이면 실행 위치가 맞습니다. 이미 `ci` 폴더 안에 들어갔다면 `cd ..`로 한 단계 올라옵니다.

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

## Jenkins 자동 검사

브랜치에 푸시하면 Jenkins가 자동으로 검사합니다. 기본 검사 15개와 서버 연결·복구 검사 7개를 통과하면 두 이미지를 Docker Hub에 올리고 `release.json`을 보관합니다.
