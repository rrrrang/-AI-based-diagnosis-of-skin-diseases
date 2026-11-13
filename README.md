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

환자 접수는 `POST /api/cases`에 multipart 요청을 보내며, `photo0`은 필수입니다. 응답의 `accessToken`은 케이스 상세와 사진 조회의 Bearer 토큰입니다. 사진은 `SKINAI_PHOTO_DIR`로 지정한 비공개 폴더에 저장하며 기본 위치는 `data/private-photos`입니다. 시연에는 합성 사진을 사용합니다.

## 환자·의사 앱 연동 시연

API와 워커는 같은 `SKINAI_DB_PATH`와 `SKINAI_PHOTO_DIR`를 사용합니다. API 프로세스의 `SKINAI_DEMO_DOCTOR_TOKENS`에 의사 ID와 시연용 토큰을 JSON으로 설정합니다. 의사 앱에서 토큰을 입력해 배정된 접수에 접근합니다. 환자 접근 토큰은 현재 브라우저 탭의 세션에 보관합니다.

```powershell
python -m app.worker --mobilenet-root D:/models/mobile --resnet-root D:/models/resnet --yolo-root D:/models/yolo --thresholds ensemble/thresholds.example.json
```

환자와 의사 앱은 각각의 프론트 폴더에서 `npm ci` 후 `VITE_SKINAI_API=true`를 설정하고 `npm run dev`로 시작합니다. 기본 주소는 환자 5173, 의사 5174이며 개발 서버는 `/api`를 8000번 포트로 전달합니다. 다른 주소는 `SKINAI_API_TARGET`으로 지정합니다.

검증한 범위는 두 앱 빌드, 백엔드 테스트, Edge에서 환자 예약·합성 사진 업로드·문진 접수, 실제 세 가중치로 워커 추론, 담당 의사 소견 공개, 환자 화면에서 소견과 등록 사진 장수 확인까지입니다. 실제 신규 환자에 대한 성능은 검증 범위 밖입니다.

### 작업 큐와 응답

- SQLite에는 `doctors`, `cases`, `photos`, `analysis_jobs`, `analysis_workers`, `reviews`가 있습니다. 소견의 임시본과 공개본을 따로 저장합니다.
- 접수 응답의 `id`와 `accessToken`으로 `POST /api/cases/{id}/analyze`를 호출합니다. 신규 작업은 202, 기존 작업 조회는 200이며 예시 본문은 `{"jobId":"...","state":"pending"}`입니다. 실패 작업 재요청에는 `?retry=true`를 사용합니다.
- 작업 임대는 60초, 워커 갱신은 15초, 선점 상한은 총 3회입니다. 임대 만료 복구, 이전 임대의 결과 쓰기 차단, 선점 상한 이후 실패 처리를 격리 SQLite로 검증했습니다.
- 담당 의사 응답의 `analysis`에 `candidate`, `decision`, 질환별 `votes`, 모델별 `models`, 체크포인트 해시 `modelVersions`, `thresholds`, `analyzedPhotoIndex`를 제공합니다. 시연용 토큰은 서버 환경변수로만 설정합니다.
