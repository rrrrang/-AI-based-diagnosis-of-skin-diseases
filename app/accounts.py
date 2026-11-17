"""아이디·비밀번호 계정과 로그인 세션.

- 비밀번호는 원문을 저장하지 않고 PBKDF2-SHA256 해시로만 저장한다.
- 로그인하면 임의의 세션 토큰을 발급하고, DB에는 그 토큰의 해시만 남긴다.
- 의사 계정은 코드에 비밀번호를 적지 않고 서버 설정값 SKINAI_DOCTOR_ACCOUNTS로 만든다.
  예: {"d1": {"loginId": "doctor1", "password": "..."}}
"""
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

PASSWORD_ITERATIONS = 210_000
SESSION_SECONDS = 12 * 60 * 60  # 로그인 유지 12시간
MAX_FAILED_LOGINS = 5
LOCK_SECONDS = 5 * 60  # 5번 틀리면 5분 잠금


def hash_password(password, iterations=None):
    iterations = iterations or PASSWORD_ITERATIONS
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password, stored):
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(candidate, digest)


# 없는 아이디로 로그인할 때도 비슷한 시간이 걸리게 해서, 아이디가 있는지 없는지 알 수 없게 한다
_DUMMY_HASH = hash_password(secrets.token_hex(8), iterations=1000)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def init_accounts(connection):
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            login_id TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('patient', 'doctor')),
            name TEXT NOT NULL,
            doctor_id TEXT UNIQUE REFERENCES doctors(id),
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            expires_at REAL NOT NULL
        );
    """)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(cases)")}
    if "patient_user_id" not in columns:  # 예전에 만든 DB도 그대로 쓸 수 있게 칸만 추가
        connection.execute("ALTER TABLE cases ADD COLUMN patient_user_id TEXT REFERENCES users(id)")
    seed_doctor_accounts(connection)


def seed_doctor_accounts(connection):
    configured = json.loads(os.environ.get("SKINAI_DOCTOR_ACCOUNTS", "{}"))
    for doctor_id, account in configured.items():
        login_id, password = account["loginId"], account["password"]
        doctor = connection.execute("SELECT name FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        if doctor is None or not login_id or not password:
            raise ValueError(f"SKINAI_DOCTOR_ACCOUNTS has an invalid entry for {doctor_id}")
        existing = connection.execute("SELECT id FROM users WHERE doctor_id = ?", (doctor_id,)).fetchone()
        if existing:
            connection.execute("UPDATE users SET login_id = ?, password_hash = ? WHERE id = ?",
                               (login_id, hash_password(password), existing["id"]))
        else:
            connection.execute(
                "INSERT INTO users (id, login_id, password_hash, role, name, doctor_id) "
                "VALUES (?, ?, ?, 'doctor', ?, ?)",
                ("USER-" + uuid.uuid4().hex, login_id, hash_password(password), doctor["name"], doctor_id),
            )


def create_session(connection, user_id):
    token = secrets.token_urlsafe(32)
    expires = time.time() + SESSION_SECONDS
    connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
    connection.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token_hash(token), user_id, expires))
    return token, expires


def session_user(connection, token):
    """로그인 세션 토큰이면 사용자 정보를, 아니면 None을 돌려준다."""
    if not token:
        return None
    return connection.execute("""
        SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ? AND sessions.expires_at > ?
    """, (token_hash(token), time.time())).fetchone()
