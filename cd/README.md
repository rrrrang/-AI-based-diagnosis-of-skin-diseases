# SkinAI CD 실습

CI는 `ci/`와 `labs/two_server_lab/`에서 빌드와 테스트를 수행한다. CD는 이 문서와 `labs/two_server_cd_lab/`에서 이미지 인수, 실행, 검증, 복구를 다룬다.

| 작업 | 안내 | 실행 폴더 | 로컬 포트 |
|---|---|---|---|
| CI | [CI 안내](../ci/README.md) | `labs/two_server_lab/` | 18120 |
| CD | 이 문서 | [CD 실습](../labs/two_server_cd_lab/README.txt) | 18130 |

CI가 전달한 성공 빌드의 `release.json`을 `prepare_compose.py`에 넘긴다. 도구가 기존 Compose를 읽고 두 이미지 주소를 새 릴리스의 값으로 반영한다. 폴더에 포함된 `release.json`은 빌드 9 실습용이다.

```powershell
cd .\labs\two_server_cd_lab
python -m pip install -r requirements.txt
python prepare_compose.py --release .\release.json
python prepare_compose.py --release .\release.json --deploy
python cd.py status
```

첫 명령은 생성과 설정 검사만 실행한다. `--deploy`를 붙이면 다운로드부터 스모크 테스트까지 진행한다. Jenkins와의 자동 실행 연결은 CI 산출물 전달 방식과 CD 실행 위치를 정한 뒤 추가한다.
