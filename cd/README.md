# SkinAI CD 실습

CI는 `ci/`와 `labs/two_server_lab/`에서 빌드와 테스트를 수행한다. CD는 이 문서와 `labs/two_server_cd_lab/`에서 이미지 인수, 실행, 검증, 복구를 다룬다.

| 작업 | 안내 | 실행 폴더 | 로컬 포트 |
|---|---|---|---|
| CI | [CI 안내](../ci/README.md) | `labs/two_server_lab/` | 18120 |
| CD | 이 문서 | [CD 실습](../labs/two_server_cd_lab/README.txt) | 18130 |

CI가 성공한 빌드의 `release.json`을 전달하면 CD에서 `compose.cd.yaml`의 두 이미지 주소를 같은 릴리스의 값으로 맞춘다. 폴더에 포함된 두 파일은 빌드 9로 연습할 때 사용한다. 새 빌드를 배포할 때는 두 파일을 한 쌍으로 준비한다.

```powershell
cd .\labs\two_server_cd_lab
python -m pip install -r requirements.txt
python cd.py check
python cd.py up
python cd.py status
```

CD는 Docker가 실행되는 Windows PC의 로컬 실습을 기준으로 한다. Jenkins와의 자동 실행 연결은 CI 산출물 전달 방식과 CD 실행 위치를 정한 뒤 추가한다.
