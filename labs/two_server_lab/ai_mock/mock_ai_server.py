from fastapi import FastAPI

app = FastAPI(title="SkinAI 실습 임시 AI 서버", version="0.1.0")


@app.get("/")
def home():
    return {
        "service": "ai-mock",
        "message": "연결 실습용 서버입니다. 실제 AI 모델은 아직 없습니다.",
        "model_loaded": False,
        "practice_only": True,
    }


@app.get("/health")
def health():
    # status는 서버 실행 상태입니다. model_loaded는 실제 모델 연결 여부입니다.
    return {
        "status": "ok",
        "service": "ai-mock",
        "app_version": "0.1.0",
        "model_loaded": False,
        "practice_only": True,
    }


@app.post("/analyze")
def analyze():
    return {
        "status": "ok",
        "service": "ai-mock",
        "message": "연결 실습용 응답입니다.",
        "model_loaded": False,
        "practice_only": True,
    }