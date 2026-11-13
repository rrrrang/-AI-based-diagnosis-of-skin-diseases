# 피부질환 AI 진단 보조 시스템

- [백엔드 통합 규칙 초안](backend_integration_rules.md)
- [기존 API 초안](backend_api_draft.md)
- [환자 UI](frontend/patient-frontend)
- [의사 UI](frontend/doctor-frontend)
- [3모델 앙상블 실행 방법](ensemble/README.md)
- [600장 추론 결과와 검증 범위](ensemble/RESULTS.md)

FastAPI 진입점 초안은 저장소 루트의 [main.py](main.py)에 있습니다. 이 체크아웃에서 참조하는 `app/` 패키지를 추가하거나 팀의 기존 구현을 가져온 뒤 서버 실행을 검증해야 합니다. 기존 README에 제시된 `backend/`와 `docs/backend-api-v1.md`는 이 체크아웃에 없습니다.
