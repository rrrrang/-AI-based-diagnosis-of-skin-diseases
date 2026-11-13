import hashlib
import hmac
import json
import os
import secrets
import uuid
from contextlib import closing
from datetime import date, time
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.db import connect
from app.jobs import enqueue, latest

router = APIRouter(prefix="/api/cases")
bearer = HTTPBearer(auto_error=False)
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png"}


def photo_root():
    return Path(os.environ.get("SKINAI_PHOTO_DIR", "data/private-photos"))


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def doctor_identity(credentials):
    if credentials is None:
        return None
    configured = json.loads(os.environ.get("SKINAI_DEMO_DOCTOR_TOKENS", "{}"))
    matches = [doctor for doctor, token in configured.items()
               if token and hmac.compare_digest(token.encode(), credentials.credentials.encode())]
    return matches[0] if len(matches) == 1 else None


class Review(BaseModel):
    diagnosis: str = Field(max_length=500)
    opinion: str = Field(max_length=4000)
    visitRequired: bool
    visitMessage: str = Field(max_length=1000)
    reviewState: Literal["임시 저장", "결과 전달 완료"]


def patient_case(case_id: str, credentials: Annotated[
    HTTPAuthorizationCredentials | None, Depends(bearer)
]):
    if credentials is None:
        raise HTTPException(401, "Case access token required", headers={"WWW-Authenticate": "Bearer"})
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM cases WHERE id = ? AND token_hash = ?",
            (case_id, token_digest(credentials.credentials)),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Case not found")
    return row


def validate_photo(upload):
    data = upload.file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo exceeds 8 MiB")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in MEDIA_TYPES or image.width * image.height > 16_000_000:
                raise HTTPException(422, "Provide a PNG or JPEG up to 16 megapixels")
            media_type = MEDIA_TYPES[image.format]
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(422, "Invalid photo") from error
    return data, media_type


@router.post("", status_code=201)
def create_case(
    doctorId: Annotated[str, Form()],
    date: Annotated[date, Form()],
    time: Annotated[time, Form()],
    patientName: Annotated[str, Form(min_length=1, max_length=100)],
    age: Annotated[int, Form(ge=0, le=130)],
    gender: Annotated[Literal["female", "male", "none"], Form()],
    photo0: UploadFile,
    photo1: UploadFile | None = None,
    photo2: UploadFile | None = None,
    symptoms: Annotated[list[str] | None, Form()] = None,
    duration: Annotated[str, Form(max_length=100)] = "",
    description: Annotated[str, Form(max_length=500)] = "",
):
    with closing(connect()) as connection:
        doctor = connection.execute("SELECT id FROM doctors WHERE id = ?", (doctorId,)).fetchone()
        if doctor is None:
            raise HTTPException(422, "Unknown doctor")
        photos = [(index, *validate_photo(upload))
                  for index, upload in enumerate((photo0, photo1, photo2)) if upload is not None]
        case_id = "CASE-" + uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        intake = json.dumps({
            "doctorId": doctorId, "date": date.isoformat(), "time": time.isoformat(timespec="minutes"),
            "patientName": patientName, "age": age, "gender": gender,
            "symptoms": symptoms or [], "duration": duration, "description": description,
        }, ensure_ascii=False)
        directory = photo_root() / case_id
        directory.mkdir(parents=True)
        try:
            with connection:
                connection.execute(
                    "INSERT INTO cases (id, doctor_id, token_hash, intake) VALUES (?, ?, ?, ?)",
                    (case_id, doctorId, token_digest(token), intake),
                )
                for index, data, media_type in photos:
                    (directory / str(index)).write_bytes(data)
                    connection.execute("INSERT INTO photos VALUES (?, ?, ?)", (case_id, index, media_type))
        except Exception:
            for index, _, _ in photos:
                (directory / str(index)).unlink(missing_ok=True)
            directory.rmdir()
            raise
    return {"id": case_id, "accessToken": token, "aiState": "대기", "reviewState": "검토 대기"}


def case_for_view(case_id, credentials):
    doctor = doctor_identity(credentials)
    if doctor is None:
        return patient_case(case_id, credentials), False
    with closing(connect()) as connection:
        case = connection.execute(
            "SELECT * FROM cases WHERE id = ? AND doctor_id = ?", (case_id, doctor)
        ).fetchone()
    if case is None:
        raise HTTPException(404, "Case not found")
    return case, True


def case_detail(connection, case, doctor=False):
    job = latest(connection, case["id"])
    review = connection.execute(
        "SELECT draft, published FROM reviews WHERE case_id = ?", (case["id"],)
    ).fetchone()
    state = job["state"] if job else "pending"
    review_json = review["draft" if doctor else "published"] if review else None
    data = {
        "id": case["id"], **json.loads(case["intake"]), "submittedAt": case["created_at"],
        "aiState": {"pending": "대기", "processing": "분석 중", "completed": "완료", "failed": "실패"}[state],
        "reviewState": "검토 대기",
    }
    if review_json:
        data.update(json.loads(review_json))
    if doctor:
        data["analysis"] = json.loads(job["result"]) if job and job["result"] else None
        data["photoIndices"] = [row[0] for row in connection.execute(
            "SELECT photo_index FROM photos WHERE case_id = ? ORDER BY photo_index", (case["id"],)
        )]
    return data


@router.get("")
def list_cases(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
               doctorId: str | None = None):
    doctor = doctor_identity(credentials)
    if doctor is None or (doctorId is not None and doctor != doctorId):
        raise HTTPException(403, "Assigned doctor access required")
    with closing(connect()) as connection:
        rows = connection.execute("SELECT * FROM cases WHERE doctor_id = ? ORDER BY rowid DESC", (doctor,))
        return [case_detail(connection, row, doctor=True) for row in rows]


@router.get("/{case_id}")
def get_case(case_id: str, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    case, doctor = case_for_view(case_id, credentials)
    with closing(connect()) as connection:
        return case_detail(connection, case, doctor)


@router.patch("/{case_id}/review")
def save_review(case_id: str, review: Review,
                credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if doctor_identity(credentials) is None:
        raise HTTPException(403, "Assigned doctor access required")
    case, _ = case_for_view(case_id, credentials)
    draft = review.model_dump_json()
    published = draft if review.reviewState == "결과 전달 완료" else None
    with closing(connect()) as connection, connection:
        connection.execute("""
            INSERT INTO reviews (case_id, draft, published) VALUES (?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET draft = excluded.draft,
                published = COALESCE(excluded.published, reviews.published)
        """, (case["id"], draft, published))
        return case_detail(connection, case, doctor=True)


@router.post("/{case_id}/analyze")
def analyze(case: Annotated[object, Depends(patient_case)], response: Response, retry: bool = False):
    job, created = enqueue(case["id"], retry)
    if job is None:
        raise HTTPException(422, "A close-up photo is required")
    response.status_code = 202 if created else 200
    return {"jobId": job["id"], "state": job["state"]}


@router.get("/{case_id}/photos/{index}")
def get_photo(case_id: str, index: Literal["0", "1", "2"],
              credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    case, _ = case_for_view(case_id, credentials)
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT media_type FROM photos WHERE case_id = ? AND photo_index = ?", (case["id"], int(index))
        ).fetchone()
    path = photo_root() / case["id"] / index
    if row is None or not path.is_file():
        raise HTTPException(404, "Photo not found")
    return FileResponse(path, media_type=row["media_type"], headers={"Cache-Control": "private, no-store"})
