"""Require this process's post-load heartbeat, never a sibling worker's."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import time


def is_ready(db_path, state_path=Path("/tmp/skinai_worker_state.json"), now=None):
    now = time.time() if now is None else now
    try:
        state = Path(state_path).read_text(encoding="utf-8")
        state = json.loads(state)
        worker_id = state["worker_id"]
        if not isinstance(worker_id, str) or not re.fullmatch("[0-9a-f]{32}", worker_id):
            return False
        if not isinstance(state["started_at"], (float, int)) or not 0 < state["started_at"] <= now:
            return False
        # mode=ro ensures a missing DB never gets created by the health probe.
        uri = Path(db_path).absolute().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as database:
            row = database.execute(
                "SELECT 1 FROM analysis_workers WHERE id = ? AND expires > ? LIMIT 1",
                (worker_id, now),
            ).fetchone()
        return row is not None
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if is_ready(os.environ["SKINAI_DB_PATH"]) else 1)
