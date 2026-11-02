import json
from urllib.error import URLError
from urllib.request import Request, urlopen
from fastapi import FastAPI, HTTPException

app = FastAPI(title="SkinAI 실습 중앙 서버", version="0.1.0")


@app.get("/")
def home():
    return {
        "service": "central",
        "message": "중앙 서버가 실행 중입니다.",
        "practice_only": True,
    }


@app.get("/health")
def health():
    # 중앙 서버 자체의 실행 상태입니다. AI 연결은 /analyze에서 별도로 검사합니다.
    return {
        "status": "ok",
        "service": "central",
        "app_version": "0.1.0",
        "practice_only": True,
    }


@app.post("/analyze")
def analyze():
    request = Request(
        "http://ai-mock:8000/analyze",
        method="POST",
    )

    try:
        with urlopen(request, timeout=3) as response:
            ai_result = json.load(response)
    except (URLError, TimeoutError):
        raise HTTPException(
            status_code=503,
            detail="임시 AI 서버와의 통신에 실패했습니다.",
        ) from None

    return {
        "service": "central",
        "ai_response": ai_result,
    }
