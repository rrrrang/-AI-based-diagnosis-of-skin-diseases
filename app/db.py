import os
import sqlite3
from contextlib import closing
from pathlib import Path


def connect():
    path = Path(os.environ.get("SKINAI_DB_PATH", "data/backend.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with closing(connect()) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS doctors (id TEXT PRIMARY KEY, name TEXT NOT NULL, hospital TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT OR IGNORE INTO doctors VALUES (?, ?, ?)",
            [(f"d{i}", f"시연 의사 {i}", "시연 병원") for i in range(1, 4)],
        )
