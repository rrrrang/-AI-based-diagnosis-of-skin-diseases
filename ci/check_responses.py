"""Check saved synthetic or staging JSON responses against the project's v1 contract."""

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def check_inference(data, job_id, model_version, preprocess_version, labels):
    """Validate a successful inference response. Labels come from the model handoff."""
    require(isinstance(data, dict), "Expected an inference object.")
    for key, expected in (
        ("job_id", job_id),
        ("model_version", model_version),
        ("preprocess_version", preprocess_version),
    ):
        require(has_text(expected) and data.get(key) == expected, f"{key} mismatch.")
    candidates = data.get("candidates")
    require(isinstance(candidates, list), "candidates must be a list.")
    if data.get("decision") == "HOLD":
        require(not candidates, "HOLD must have an empty candidates list.")
        require(data.get("hold_reason") in ("LOW_QUALITY", "UNSUPPORTED_INPUT", "LOW_CONFIDENCE"),
                "Unknown or missing hold_reason.")
        return

    require(data.get("decision") == "CANDIDATES", "Unknown decision.")
    require("hold_reason" not in data, "CANDIDATES cannot contain hold_reason.")
    require(bool(candidates), "CANDIDATES must have at least one candidate.")
    seen = set()
    previous = None
    for candidate in candidates:
        require(isinstance(candidate, dict), "Expected a candidate object.")
        label = candidate.get("class_id")
        require(has_text(label) and label in labels, "Unknown candidate label.")
        require(label not in seen, "Duplicate candidate label.")
        seen.add(label)
        score = candidate.get("score")
        require(type(score) in (float, int), "score must be a number.")
        require(not isinstance(score, float) or math.isfinite(score), "score must be finite.")
        require(previous is None or score <= previous, "Scores must be in descending order.")
        previous = score


def check_patient(data, case_id, status=200):
    """Check the public result endpoint, including two common error responses."""
    require(isinstance(data, dict), "Expected a patient result object.")
    if status in (403, 409):
        require(set(data) == {"error", "request_id"} and has_text(data["request_id"]),
                "Unexpected public error fields or missing request_id.")
        error = data["error"]
        require(isinstance(error, dict) and set(error) == {"code", "message"},
                "Unexpected error details.")
        expected_code = "FORBIDDEN" if status == 403 else "RESULT_NOT_READY"
        require(error["code"] == expected_code and has_text(error["message"]),
                "Unexpected public error code or missing message.")
        return

    require(status == 200, "Unsupported HTTP status.")
    required = {"case_id", "case_status", "confirmed_at", "final_text", "review_comment"}
    optional = {"visit_recommendation", "follow_up_instructions"}
    require(required <= data.keys() <= required | optional, "Unexpected or missing public fields.")
    require(has_text(case_id) and data["case_id"] == case_id, "case_id mismatch.")
    require(data["case_status"] == "confirmed", "Only a confirmed result can be public.")
    for key in {"final_text", "review_comment"} | (optional & data.keys()):
        require(has_text(data[key]), f"Expected non-empty text in {key}.")
    stamp = data["confirmed_at"]
    require(isinstance(stamp, str) and re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|\+00:00)", stamp),
        "confirmed_at must be a UTC timestamp.")
    try:
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid calendar date or time in confirmed_at.") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="kind", required=True)
    ai = sub.add_parser("inference", help="Check a 200 response from the inference service.")
    ai.add_argument("response", type=Path)
    ai.add_argument("--job-id", required=True)
    ai.add_argument("--model-version", required=True)
    ai.add_argument("--preprocess-version", required=True)
    ai.add_argument("--labels", nargs="+", required=True)
    patient = sub.add_parser("patient", help="Check a public patient result or error.")
    patient.add_argument("response", type=Path)
    patient.add_argument("--case-id", required=True)
    patient.add_argument("--status", type=int, choices=(200, 403, 409), default=200)
    args = parser.parse_args()
    try:
        with args.response.open(encoding="utf-8-sig") as source:
            data = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
        print("FAIL: Cannot read a valid UTF-8 JSON response.", file=sys.stderr)
        return 1
    try:
        if args.kind == "inference":
            check_inference(data, args.job_id, args.model_version, args.preprocess_version, args.labels)
        else:
            check_patient(data, args.case_id, args.status)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {args.kind} response matches the contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

