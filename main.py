"""서버 시작점. 실행: uvicorn main:app --reload --port 8000"""
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app import db
from app.errors import register_error_handlers
from app.routers import cases, doctors, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()  # 서버가 켜질 때 테이블 준비
    yield


app = FastAPI(title="피부질환 AI 진단 보조 API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """요청마다 추적용 request_id를 붙입니다. 오류 응답과 헤더에 들어갑니다."""
    request.state.request_id = "REQ_" + uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


register_error_handlers(app)
app.include_router(health.router)
app.include_router(doctors.router)
app.include_router(cases.router)
