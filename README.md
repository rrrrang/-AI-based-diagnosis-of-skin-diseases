# 백엔드 (FastAPI)

API 설계는 `../docs/backend-api-v1.md`를 봐 주세요.

## 처음 한 번 준비

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # 윈도우: .venv\Scripts\activate
pip install -r requirements.txt
```

## 서버 켜기

```bash
uvicorn app.main:app --reload --port 8000
```

- 브라우저에서 http://localhost:8000/docs 를 열면 API를 눌러 볼 수 있어요.

## 테스트

```bash
python -m pytest
```

## 지금 되는 것

| 주소 | 설명 |
| --- | --- |
| `GET /health/live` | 서버가 살아 있는지 |
| `GET /health/ready` | DB가 준비됐는지 (안 되면 503) |
| `GET /api/v1/doctors` | 의사 목록 3명 |

## 폴더 구조

```
backend/
├── app/
│   ├── main.py      # 서버 시작점, request_id 붙이기
│   ├── config.py    # 환경변수 읽기
│   ├── db.py        # SQLite 연결, 테이블 만들기
│   ├── errors.py    # 팀 공통 오류 모양
│   └── routers/     # API 주소별 파일
│       ├── health.py
│       └── doctors.py
└── tests/           # 테스트
```
