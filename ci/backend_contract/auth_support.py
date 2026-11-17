"""Authentication boundary for tests of the current case-token API.

These helpers do not log in, log out, create accounts, or read application
credentials. Demo doctor tokens belong only to isolated test servers. When
the real authentication contract arrives, add its implementation here and
update intake/ownership expectations explicitly; do not fall back silently.
"""
from collections.abc import Mapping
import json
from pathlib import Path
import re
import secrets


DOCTOR_TOKENS_ENV = "SKINAI_DEMO_DOCTOR_TOKENS"
_TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
_DOCTOR_ID = re.compile(r"[A-Za-z0-9_-]+")


def _token(value):
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError("A nonempty valid test access token is required")
    return value


def bearer_headers(token):
    """None means an intentionally unauthenticated request; invalid is an error."""
    return {} if token is None else {"Authorization": "Bearer " + _token(token)}


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
