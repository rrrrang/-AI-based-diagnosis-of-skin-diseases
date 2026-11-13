from contextlib import closing

from fastapi import APIRouter

from app.db import connect

router = APIRouter()


@router.get("/api/doctors")
def doctors():
    with closing(connect()) as connection:
        return [dict(row) for row in connection.execute("SELECT id, name, hospital FROM doctors ORDER BY id")]
