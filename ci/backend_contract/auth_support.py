"""Explicit login sessions and legacy case credentials for isolated CI tests.

Login errors never fall back to demo credentials. The legacy helpers below
remain available only for tests explicitly covering the old case-token API.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import secrets


DOCTOR_TOKENS_ENV = "SKINAI_DEMO_DOCTOR_TOKENS"
DOCTOR_ACCOUNTS_ENV = "SKINAI_DOCTOR_ACCOUNTS"
_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
_DOCTOR_ID = re.compile(r"[A-Za-z0-9_-]+")


def _token(value):
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError("A nonempty valid test access token is required")
    return value


def bearer_headers(token):
    """None means an intentionally unauthenticated request; invalid is an error."""
    return {} if token is None else {"Authorization": "Bearer " + _token(token)}


@dataclass(frozen=True)
class LoginSession:
    """Keep session tokens out of test object representations and failures."""
    role: str
    login_id: str
    doctor_id: str | None
    expires_at: float
    _access_token: str = field(repr=False)

    def headers(self):
        return bearer_headers(self._access_token)


def _session(response, role, doctor_id=None):
    if response.status_code != 200:
        raise ValueError(f"{role} login failed (HTTP {response.status_code})")
    try:
        body = response.json()
        expires = body.get("expiresAt")
        if (not isinstance(body.get("loginId"), str) or not body["loginId"]
                or body.get("role") != role
                or (role == "patient" and body.get("doctorId") is not None)
                or (role == "doctor" and body.get("doctorId") != doctor_id)
                or isinstance(expires, bool) or not isinstance(expires, (int, float))
                or not math.isfinite(expires) or expires <= 0):
            raise ValueError("Invalid login session")
        return LoginSession(role, body["loginId"], body.get("doctorId"), float(expires),
                            _token(body.get("accessToken")))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Login response did not match the required session format") from None


def login_patient(client, *, phone, name, create=False):
    """Use create=True only for first visit; reservation lookup is create=False."""
    return _session(client.post("/api/auth/patient", json={
        "phone": phone, "name": name, "create": create,
    }), "patient")


def login_doctor(client, *, login_id, password, doctor_id="d1"):
    return _session(client.post("/api/auth/login", json={
        "loginId": login_id, "password": password,
    }), "doctor", doctor_id)


def logout_session(client, session):
    """Revoke a login session, never a legacy case-specific credential."""
    response = client.post("/api/auth/logout", headers=session.headers())
    if response.status_code != 204:
        raise ValueError(f"Logout failed (HTTP {response.status_code})")


def patient_token(intake):
    """Extract the current case credential without including it in errors."""
    if not isinstance(intake, Mapping):
        raise ValueError("Expected a case intake response containing an access token")
    return _token(intake.get("accessToken"))


def patient_headers(intake):
    return bearer_headers(patient_token(intake))


def _doctor_tokens(tokens, required=()):
    if not isinstance(tokens, Mapping) or not tokens:
        raise ValueError("Expected a nonempty mapping of test doctor tokens")
    if any(not isinstance(key, str) or _DOCTOR_ID.fullmatch(key) is None for key in tokens):
        raise ValueError("Invalid test doctor identity")
    if any(key not in tokens for key in required):
        raise ValueError("Required test doctor identities are missing")
    values = [_token(value) for value in tokens.values()]
    if len(set(values)) != len(values):
        raise ValueError("Test doctor tokens must be distinct")
    return dict(tokens)


def new_doctor_tokens(identities=("d1", "d2")):
    """Generate temporary credentials, not permanent login accounts."""
    identities = tuple(identities)
    if (not identities or any(not isinstance(key, str) or _DOCTOR_ID.fullmatch(key) is None
                              for key in identities)
            or len(set(identities)) != len(identities)):
        raise ValueError("Provide distinct test doctor identities")
    return _doctor_tokens({key: secrets.token_urlsafe(32) for key in identities})


def doctor_environment(tokens):
    """Return only the explicit test-server auth setting, without changing env."""
    return {DOCTOR_TOKENS_ENV: json.dumps(_doctor_tokens(tokens))}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate test doctor identity")
        result[key] = value
    return result


def load_doctor_tokens(env_file, required=("d1", "d2")):
    """Read an explicitly supplied temporary test env file; never an ambient file."""
    try:
        lines = Path(env_file).read_text(encoding="utf-8-sig").splitlines()
        values = [line.partition("=")[2] for line in lines
                  if line.startswith(DOCTOR_TOKENS_ENV + "=")]
        if len(values) != 1:
            raise ValueError("Expected one test doctor token setting")
        tokens = json.loads(values[0], object_pairs_hook=_unique_object)
        return _doctor_tokens(tokens, required)
    except (OSError, UnicodeError, ValueError, TypeError):
        # Suppress JSON/path exception chains so credentials cannot reach logs.
        raise ValueError("Read failed: provide an explicit env file with distinct test doctor tokens") from None
