import json
import time
import uuid
from contextlib import closing

from fastapi import HTTPException

from app.db import connect

LEASE_SECONDS = 60
MAX_CLAIMS = 3


def init_jobs(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, photo_index INTEGER NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            lease TEXT, expires REAL, started_at REAL, finished_at REAL,
            result TEXT, error TEXT,
            FOREIGN KEY (case_id, photo_index) REFERENCES photos(case_id, photo_index)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS active_analysis
            ON analysis_jobs(case_id) WHERE state IN ('pending', 'processing');
        CREATE TABLE IF NOT EXISTS analysis_workers (id TEXT PRIMARY KEY, expires REAL NOT NULL);
    """)


def latest(connection, case_id):
    return connection.execute(
        "SELECT * FROM analysis_jobs WHERE case_id = ? ORDER BY rowid DESC LIMIT 1",
        (case_id,),
    ).fetchone()


def enqueue(case_id, retry=False):
    with closing(connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = latest(connection, case_id)
        if previous and (previous["state"] != "failed" or not retry):
            return previous, False
        photo = connection.execute(
            "SELECT photo_index FROM photos WHERE case_id = ? AND photo_index IN (1, 2) ORDER BY photo_index LIMIT 1",
            (case_id,),
        ).fetchone()
        if photo is None:
            return None, False
        if connection.execute("SELECT 1 FROM analysis_workers WHERE expires > ? LIMIT 1",
                              (time.time(),)).fetchone() is None:
            raise HTTPException(503, "Analysis worker is unavailable")
        connection.execute(
            "INSERT INTO analysis_jobs(id, case_id, photo_index, state) VALUES (?, ?, ?, 'pending')",
            (uuid.uuid4().hex, case_id, photo["photo_index"]),
        )
        return latest(connection, case_id), True


def heartbeat(worker_id):
    with closing(connect()) as connection, connection:
        now = time.time()
        connection.execute("DELETE FROM analysis_workers WHERE expires <= ?", (now,))
        connection.execute("INSERT OR REPLACE INTO analysis_workers VALUES (?, ?)",
                           (worker_id, now + LEASE_SECONDS))


def claim():
    with closing(connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        now = time.time()
        connection.execute("""
            UPDATE analysis_jobs SET state = CASE WHEN attempts >= ? THEN 'failed' ELSE 'pending' END,
                finished_at = CASE WHEN attempts >= ? THEN ? END,
                error = CASE WHEN attempts >= ? THEN 'worker_lease_expired' END,
                lease = NULL, expires = NULL
            WHERE state = 'processing' AND expires <= ?
        """, (MAX_CLAIMS, MAX_CLAIMS, now, MAX_CLAIMS, now))
        row = connection.execute(
            "SELECT id FROM analysis_jobs WHERE state = 'pending' ORDER BY rowid LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return connection.execute("""
            UPDATE analysis_jobs SET state = 'processing', lease = ?, expires = ?,
                started_at = ?, attempts = attempts + 1 WHERE id = ? RETURNING *
        """, (uuid.uuid4().hex, now + LEASE_SECONDS, now, row["id"])).fetchone()


def renew(job):
    with closing(connect()) as connection, connection:
        now = time.time()
        return connection.execute("""
            UPDATE analysis_jobs SET expires = ?
            WHERE id = ? AND lease = ? AND expires > ?
        """, (now + LEASE_SECONDS, job["id"], job["lease"], now)).rowcount == 1


def finish(job, *, result=None, error=None):
    with closing(connect()) as connection, connection:
        now = time.time()
        return connection.execute("""
            UPDATE analysis_jobs SET state = ?, result = ?, error = ?, finished_at = ?,
                lease = NULL, expires = NULL WHERE id = ? AND lease = ? AND expires > ?
        """, ("failed" if error else "completed", json.dumps(result) if result is not None else None,
              error, now, job["id"], job["lease"], now)).rowcount == 1
