# 피부질환 AI 진단 보조 시스템

- [백엔드 통합 규칙 초안](backend_integration_rules.md)
- [기존 API 초안](backend_api_draft.md)
- [환자 UI](frontend/patient-frontend)
- [의사 UI](frontend/doctor-frontend)
- [3모델 앙상블 실행 방법](ensemble/README.md)
- [600장 추론 결과와 검증 범위](ensemble/RESULTS.md)


## 백엔드 실행

저장소 루트에서 실행합니다.

```powershell
python -m pip install -r requirements-backend.txt
python -m uvicorn main:app --port 8000
python -m unittest discover -s tests
```

`GET /api/health`와 `GET /api/doctors`를 사용할 수 있습니다. SQLite 경로는 `SKINAI_DB_PATH`로 지정합니다. 의사 목록은 시연 데이터입니다.
