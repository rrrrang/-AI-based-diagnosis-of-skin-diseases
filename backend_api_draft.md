# 피부질환 AI 백엔드 API 초안 (v0.1, 작성: 수진)

기준: 미주님 프론트(`feature/frontend-ui`, `types/doctorCase.ts`), AI 모델 v0.1(`feature/skin-classifier-v0.1`, `Predictor().predict()`)
서버: FastAPI, 주소는 모두 `/api` 아래

## API 목록

| # | 방법 | 주소 | 하는 일 | 쓰는 화면 |
|---|---|---|---|---|
| 1 | GET | `/api/health` | 서버 살아 있는지 확인 | CI/CD 검사 |
| 2 | GET | `/api/doctors` | 예약 가능한 의사 목록 | 환자: 의사 예약 |
| 3 | POST | `/api/cases` | 접수 등록 (환자 정보 + 예약 + 사진 2~3장) → 접수번호 발급 | 환자: 정보 입력 완료 |
| 4 | POST | `/api/cases/{id}/analyze` | AI 분석 실행 (부위 사진으로) | 접수 직후 자동 |
| 5 | GET | `/api/cases/{id}` | 접수 1건 조회 (AI 결과 + 의사 소견 포함) | 환자: 결과 / 의사: 검토 |
| 6 | GET | `/api/cases?doctorId=d1` | 담당 의사의 접수 목록 | 의사: 대시보드 |
| 7 | PATCH | `/api/cases/{id}/review` | 의사 소견 임시 저장 / 결과 전달 | 의사: 검토 |
| 8 | GET | `/api/cases/{id}/photos/{0~2}` | 등록 사진 보기 (0 정면, 1·2 부위) | 의사: 검토 |
| 9 | GET | `/api/cases/{id}/analysis-image` | AI가 본 부위 표시 그림(overlay) | 의사: 검토 |

## 3. 접수 등록 (POST /api/cases)

- 형식: `multipart/form-data` (사진 파일 때문에)
- 보내는 값: `doctorId`, `date`(YYYY-MM-DD), `time`(HH:mm), `patientName`, `age`, `gender`(female/male/none), `symptoms`(목록), `duration`, `description`(최대 500자), `photo0`(정면, 필수), `photo1`(근접, 필수), `photo2`(추가 근접, 선택). 사진 필드마다 1장만 보내며 최소 2장, 최대 3장입니다. 필수 사진 누락·같은 사진 필드 중복·추가 파일은 접수 전에 422로 거절합니다.
- 받는 값: `{ "id": "REQ-...", "aiState": "대기", "reviewState": "검토 대기" }`

## 4. AI 분석 (POST /api/cases/{id}/analyze)

- 신규 접수는 필수 근접 사진 `photo1`을 분석합니다. 선택 사진 `photo2`는 저장하여 의사가 확인하며, 현재 두 근접 사진을 함께 분석하는 기능은 없습니다. 정면 `photo0`은 의사 검토용입니다. 기존 접수의 `photo1`이 없는 경우에만 워커의 `photo2` 대체 처리 규칙을 유지합니다.
- AI 상태 흐름: `대기` → `분석 중` → `완료` 또는 `실패`
- 모델 결과 → 프론트 형식 변환

| 모델 결과 (`predict()`) | 프론트 필드 |
|---|---|
| `probs` (6개 질환 확률) | `predictions: [{ "label": "여드름", "score": 0.93 }, ...]` (점수 높은 순) |
| `accepted = False` | 화면에 "판단 불가" 표시 (확신 0.82 미만) |
| `overlay` | `analysisPhoto` → 9번 주소로 제공 |
| `warnings` | 주의 문구 그대로 전달 |

받는 값 예시:
```json
{
  "id": "REQ-1234",
  "aiState": "완료",
  "accepted": true,
  "predictions": [
    { "label": "여드름", "score": 0.93 },
    { "label": "주사", "score": 0.04 },
    { "label": "지루", "score": 0.02 }
  ],
  "warnings": []
}
```

## 7. 의사 소견 (PATCH /api/cases/{id}/review)

- 보내는 값: `diagnosis`, `opinion`, `visitRequired`(true/false), `visitMessage`, `reviewState`(`임시 저장` 또는 `결과 전달 완료`)
- `결과 전달 완료`가 되면 환자 결과 화면(5번)에 소견이 보입니다.

## 오류 안내

| 코드 | 언제 |
|---|---|
| 400 / 422 | 필수값 없음, 사진 형식 오류 |
| 404 | 없는 접수번호 |
| 503 | AI 모델 서버 연결 실패 (서버는 멈추지 않음) |

## 팀과 맞춰야 할 것

1. **미주님**: 위 주소·필드 이름이 화면과 맞는지. 의사 목록(2번)을 서버에서 줄지, 지금처럼 화면에 고정할지.
2. **모델 담당**: 부위 사진 2장이면 둘 다 분석할지, 1장만 할지. 백엔드 안에서 모델을 직접 불러올지, AI 서버를 따로 둘지.
3. **동현님·희구님(CI/CD)**: 서버 이름·포트, `/api/health` 응답 형식.
4. 시연용이라 실제 환자 정보는 저장하지 않습니다. 저장소는 우선 SQLite(파일 DB), 사진은 서버 폴더에 저장.
