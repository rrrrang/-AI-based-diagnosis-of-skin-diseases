# 로그인 인증 검사

로그인 API와 환자·의사 화면을 자동 검사합니다. 환자·의사 로그인 세션과 기존 접수별 토큰을 구분하며, 로그인 실패를 시연용 토큰으로 우회하지 않습니다.

## 검사 기준

| 대상 | 확인할 내용 |
| --- | --- |
| 환자 시작 | 전화번호·이름으로 첫 방문 계정을 자동 생성 |
| 내 예약 확인 | 같은 정보로 다시 로그인해 본인 접수 조회, 없는 계정·다른 이름은 401 |
| 의사 로그인 | 아이디·비밀번호로 로그인한 뒤 담당 접수 조회 |
| 의사 잠금 | 잘못된 비밀번호 1~5회는 401, 이후 잠금 중 요청은 429. 5분 뒤 정상 로그인, 성공 시 실패 횟수 초기화 |
| 로그아웃 | 해당 로그인 세션으로 사용자 정보·예약 조회·의사 검토 저장 불가. 다시 로그인한 새 세션은 사용 가능 |
| 역할 구분 | 환자 로그인으로 의사 목록·검토 저장 불가 |
| 결과 공개 | 임시 소견·AI 점수는 환자에게 비공개, 의사 확정 뒤 공개된 소견만 조회 |
| 전체 연결 | 정면+부위 사진 2장 / 선택 사진 포함 3장으로 접수·실제 3개 모델·의사 확정·환자 결과 조회 |

이름·전화번호를 모두 아는 사람의 본인 여부는 이번 최소 로그인 방식으로 구별하지 않습니다.

로그아웃은 **로그인 세션**을 무효화합니다. 기존 접수별 조회 토큰은 별도 자격증명이며 현재 서버에서는 로그아웃 후에도 유효합니다. 접수별 토큰 검사는 기존 방식 호환성 확인으로 유지하고, 로그인 세션 검사와 혼용하지 않습니다.

## 공통 파일

- Python: `ci/backend_contract/auth_support.py`
- Playwright: `frontend/patient-frontend/tests/support/auth.ts`
- 서버 로그인 회귀 검사: `tests/test_auth.py`
- 별도 HTTP 서버 검사: `ci/backend_contract/check_http.py`
- UI 전체 흐름: `frontend/patient-frontend/tests/workflow/`

검사 전용 계정·DB·합성 사진을 사용합니다. 배포 중인 의사 계정에 잠금 검사를 실행하지 않으며, 비밀번호와 토큰을 Git·검사 보고서에 남기지 않습니다. 로그인 잠금 시간 경계는 서버 단위검사에서 시간을 제어해 확인합니다.

## 실행 방법

프로젝트 최상위에서 백엔드 검사 패키지가 설치된 Python을 사용합니다.

```powershell
python -B -X utf8 ci/backend_contract/test_auth_support.py
python -B -X utf8 ci/backend_contract/test_runner.py
python -B -X utf8 ci/backend_contract/run_checks.py --source-root . --output-root verification/login-api/backend
```

UI 공통 인증 도구 검사:

```powershell
Set-Location frontend/patient-frontend
npm ci
npx playwright test --config playwright.auth-support.config.ts
```

실제 모델을 포함한 UI 검사는 기존 `ci/ui_workflow/run_workflow.py`를 별도 임시 환경에서 실행합니다. 모델 폴더·합성 샘플·Docker·Node·브라우저 경로를 명시하고, 검사 포트가 사용 중이면 기존 서버를 중단하지 않고 검사 시작을 거부합니다.

## 반영 범위

main 변경을 감지하면 기존 Jenkins 작업에서 실행합니다.

- `SkinAI-Backend-CI`: 인증 도구, 로그인·잠금·로그아웃, 접수·권한·결과 공개, Docker 호환성 검사.
- `SkinAI-UI-CI`: 두 UI 빌드, 인증 도구, 환자 필수 입력 검사.
- `SkinAI-Workflow-CI`: 실제 모델 3개를 포함한 사진 2장·3장 전체 흐름 검사.
- 같은 커밋의 세 검사가 통과한 뒤 기존 Release·CD 작업이 이미지 전달과 배포를 진행합니다.

앱 구현·의사 비밀번호·CD 설정은 이 변경에서 수정하지 않습니다. 현재 실행기의 worker 사진 폴더가 읽기 전용이어서 발생하는 환부 표시 이미지(overlay) 저장 경고는 별도 사항입니다. 분석 결과·로그인·의사 확정 검사 통과가 overlay 저장 성공을 뜻하지는 않습니다.

## 2026-11-18 확인 결과

- main `3f7c2f2`를 기준으로 준비 브랜치에서 검사했습니다.
- 서버 33개(로그인 검사 12개 포함), 정책 1개, 별도 HTTP 23개 통과.
- Python 공통 인증 도구 11개, 검사 누락·실패 차단 10개 통과.
- Playwright 인증 도구 8개와 TypeScript 검사 통과.
- 실제 모델 3개를 사용하는 사진 2장·3장 UI 흐름 모두 통과. 새 브라우저의 환자 재로그인·예약 조회, 의사·환자 로그아웃 후 세션 차단 포함.
- 기존 Docker 호환성 검사 8개, 릴리스 회귀 검사 116개 통과.
- 임시 컨테이너·네트워크·비밀 설정 정리 완료. 기존 배포 컨테이너 유지 확인.

위 수치는 별도 로컬 검사 기록입니다. main 반영 후 결과는 각 Jenkins 빌드에 보관되는 로그와 검사 보고서에서 확인합니다.
