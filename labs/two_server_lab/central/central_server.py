import json
from urllib.error import URLError
from urllib.request import Request, urlopen
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class PracticeRequest(BaseModel):
    """실제 의료 API와 별개인 연결 실습용 입력입니다."""

    model_config = ConfigDict(strict=True, extra="forbid")

    sample_id: str = Field(min_length=1, max_length=64)
    sample_text: str = Field(min_length=1, max_length=200)


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
def analyze(payload: PracticeRequest):
    request = Request(
        "http://ai-mock:8000/analyze",
        data=json.dumps(payload.model_dump(), ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
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
