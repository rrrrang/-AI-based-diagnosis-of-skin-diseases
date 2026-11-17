import os
import sqlite3
from contextlib import closing
from pathlib import Path


DOCTORS = [
    ("d1", "김서연", "서울아산병원"),
    ("d2", "박지훈", "삼성서울병원"),
    ("d3", "이다은", "세브란스병원"),
]


def connect():
    path = Path(os.environ.get("SKINAI_DB_PATH", "data/backend.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    from app.accounts import init_accounts
    from app.jobs import init_jobs

    with closing(connect()) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS doctors (id TEXT PRIMARY KEY, name TEXT NOT NULL, hospital TEXT NOT NULL)"
        )
        # 가상 의사 3명 (환자·의사 화면과 같은 값). 이미 만든 DB도 켤 때 이 값으로 맞춘다.
        connection.executemany(
            "INSERT INTO doctors VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, hospital = excluded.hospital",
            DOCTORS,
        )
        connection.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                doctor_id TEXT NOT NULL REFERENCES doctors(id),
                token_hash TEXT NOT NULL,
                intake TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                case_id TEXT NOT NULL REFERENCES cases(id),
                photo_index INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                PRIMARY KEY (case_id, photo_index)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                case_id TEXT PRIMARY KEY REFERENCES cases(id),
                draft TEXT NOT NULL,
                published TEXT
            )
        """)
        init_jobs(connection)
        init_accounts(connection)
