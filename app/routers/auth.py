"""로그인·로그아웃과 환자의 내 예약 현황.

- 환자: 전화번호(아이디) + 이름(비밀번호). 처음 오면 계정을 만들고, 다음부터는 같은 값으로 로그인한다.
- 의사: 서버 설정으로 만든 아이디·비밀번호로 로그인한다.
"""
import re
import time
import uuid
from contextlib import closing
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app import accounts
from app.db import connect
from app.routers.cases import case_detail

router = APIRouter()
bearer = HTTPBearer(auto_error=False)

WRONG_LOGIN = "아이디 또는 비밀번호가 맞지 않아요."
WRONG_PATIENT = "전화번호 또는 이름이 맞지 않아요."


class Login(BaseModel):
    loginId: str = Field(max_length=30)
    password: str = Field(max_length=72)


class PatientLogin(BaseModel):
    phone: str = Field(max_length=20)
    name: str = Field(max_length=20)
    create: bool = False  # 첫 화면 '시작하기'는 true, '내 예약 확인'은 false


def current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    with closing(connect()) as connection:
        user = accounts.session_user(connection, credentials.credentials if credentials else None)
    if user is None:
        raise HTTPException(401, "로그인이 필요해요.", headers={"WWW-Authenticate": "Bearer"})
    return user


def user_view(user):
    view = {"loginId": user["login_id"], "name": user["name"], "role": user["role"],
            "doctorId": user["doctor_id"]}
    if user["doctor_id"]:
        with closing(connect()) as connection:
            doctor = connection.execute(
                "SELECT name, hospital FROM doctors WHERE id = ?", (user["doctor_id"],)
            ).fetchone()
        view.update(name=doctor["name"], hospital=doctor["hospital"])
    return view


def check_password(connection, user, password, wrong_message):
    """잠금 확인 → 비밀번호 확인 → 실패 횟수 기록. 통과하면 로그인 응답을 돌려준다."""
    now = time.time()
    if user["locked_until"] and user["locked_until"] > now:
        raise HTTPException(429, "로그인 시도가 너무 많아요. 5분 뒤에 다시 시도해 주세요.")
    if not accounts.verify_password(password, user["password_hash"]):
        failed = user["failed_count"] + 1
        locked = now + accounts.LOCK_SECONDS if failed >= accounts.MAX_FAILED_LOGINS else None
        connection.execute("UPDATE users SET failed_count = ?, locked_until = ? WHERE id = ?",
                           (0 if locked else failed, locked, user["id"]))
        connection.commit()
        raise HTTPException(401, wrong_message)
    connection.execute("UPDATE users SET failed_count = 0, locked_until = NULL WHERE id = ?", (user["id"],))
    token, expires = accounts.create_session(connection, user["id"])
    return {"accessToken": token, "expiresAt": expires, **user_view(user)}


@router.post("/api/auth/login")
def login(body: Login):
    """의사 로그인 (아이디·비밀번호)."""
    with closing(connect()) as connection, connection:
        user = connection.execute("SELECT * FROM users WHERE login_id = ?", (body.loginId,)).fetchone()
        if user is None:
            accounts.verify_password(body.password, accounts._DUMMY_HASH)
            raise HTTPException(401, WRONG_LOGIN)
        return check_password(connection, user, body.password, WRONG_LOGIN)


@router.post("/api/auth/patient")
def patient_login(body: PatientLogin):
    """환자 로그인. 아이디는 전화번호(숫자만), 비밀번호는 이름."""
    phone = re.sub(r"[\s-]", "", body.phone)
    name = body.name.strip()
    if not re.fullmatch(r"0\d{8,10}", phone) or not name:
        raise HTTPException(422, "전화번호(숫자 9~11자리)와 이름을 확인해 주세요.")
    with closing(connect()) as connection, connection:
        user = connection.execute("SELECT * FROM users WHERE login_id = ?", (phone,)).fetchone()
        if user is None and body.create:
            connection.execute(
                "INSERT INTO users (id, login_id, password_hash, role, name) VALUES (?, ?, ?, 'patient', ?)",
                ("USER-" + uuid.uuid4().hex, phone, accounts.hash_password(name), name),
            )
            user = connection.execute("SELECT * FROM users WHERE login_id = ?", (phone,)).fetchone()
        if user is None or user["role"] != "patient":
            accounts.verify_password(name, accounts._DUMMY_HASH)
            raise HTTPException(401, WRONG_PATIENT)
        return check_password(connection, user, name, WRONG_PATIENT)


@router.post("/api/auth/logout", status_code=204)
def logout(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is not None:
        with closing(connect()) as connection, connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?",
                               (accounts.token_hash(credentials.credentials),))
    return Response(status_code=204)


@router.get("/api/auth/me")
def me(user: Annotated[object, Depends(current_user)]):
    return user_view(user)


@router.get("/api/me/cases")
def my_cases(user: Annotated[object, Depends(current_user)]):
    """로그인한 환자의 예약 현황: 담당 의사, 예약 일시, 올린 사진 번호, 진행 상태, 공개된 소견.

    AI 후보·점수와 의사 임시 소견은 넣지 않는다.
    """
    if user["role"] != "patient":
        raise HTTPException(403, "환자 계정으로 로그인해 주세요.")
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM cases WHERE patient_user_id = ? ORDER BY rowid DESC", (user["id"],)
        ).fetchall()
        result = []
        for row in rows:
            item = case_detail(connection, row)
            doctor = connection.execute(
                "SELECT name, hospital FROM doctors WHERE id = ?", (row["doctor_id"],)
            ).fetchone()
            item["doctorName"], item["doctorHospital"] = doctor["name"], doctor["hospital"]
            item["photoIndices"] = [r[0] for r in connection.execute(
                "SELECT photo_index FROM photos WHERE case_id = ? ORDER BY photo_index", (row["id"],)
            )]
            result.append(item)
        return result
