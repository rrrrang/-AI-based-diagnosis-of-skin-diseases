"""Validate local SkinAI preview evidence; never authorize a release or deployment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import sys

SCHEMA = "skinai.local-candidate/v2"
SERVICES = frozenset({"api", "worker", "patient-ui", "doctor-ui"})
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
LOCAL_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
FORBIDDEN_SERVICE_KEYS = frozenset(
    {"release_id", "repository", "registry_digest", "digest"}
)
REQUIRED = frozenset({
    "schema", "draft_only", "deployable", "target", "platform", "source",
    "packaging", "services", "model_bundle_manifest_sha256",
})
OPTIONAL = frozenset({"candidate_id", "ci", "verification", "limitations"})


def _fail(where: str, message: str) -> None:
    raise ValueError(f"{where}: {message}")


def _object(value, where: str, required, optional=()) -> dict:
    if not isinstance(value, dict):
        _fail(where, "must be an object")
    keys = set(value)
    if any(not isinstance(key, str) for key in keys):
        _fail(where, "keys must be strings")
    missing = set(required) - keys
    unknown = keys - set(required) - set(optional)
    if missing:
        _fail(where, "missing fields: " + ", ".join(sorted(missing)))
    if unknown:
        _fail(where, "unsupported fields: " + ", ".join(sorted(unknown)))
    return value


def _text(value, where: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _fail(where, "must be a nonempty string")


def _hex(value, pattern, where: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail(where, "invalid lowercase SHA-256 or commit identifier")


def _scan_service(value, where: str) -> None:
    # A local Docker ID can share the shape of a remote manifest digest.
    # It does not prove registry publication; keep those claims separate.
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_SERVICE_KEYS:
                _fail(where, f"release field {key!r} is forbidden")
            _scan_service(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_service(child, f"{where}[{index}]")
    elif isinstance(value, str) and "@sha256" in value.lower():
        _fail(where, "registry digest references are forbidden in a local candidate")


def validate_candidate(data) -> None:
    """Return None for a valid DRAFT, otherwise raise ValueError.

    This validates metadata only. The caller must separately inspect local
    Docker images and verify all file hashes. A passing candidate remains
    nondeployable, even when its local verification status is 'passed'.
    """
    _object(data, "candidate", REQUIRED, OPTIONAL)
    constants = {
        "schema": SCHEMA,
        "draft_only": True,
        "deployable": False,
        "target": "local-preview",
        "platform": "linux/amd64",
    }
    for key, expected in constants.items():
        actual = data[key]
        if type(actual) is not type(expected) or actual != expected:
            _fail(key, f"must equal {expected!r}")
    if "candidate_id" in data:
        _text(data["candidate_id"], "candidate_id")

    source = _object(data["source"], "source", {"commit", "working_tree_dirty"})
    _hex(source["commit"], HEX40, "source.commit")
    if type(source["working_tree_dirty"]) is not bool:
        _fail("source.working_tree_dirty", "must be a boolean")

    packaging = _object(data["packaging"], "packaging", {"status", "files_sha256"})
    if packaging["status"] not in ("uncommitted-draft", "committed-draft"):
        _fail("packaging.status", "must be uncommitted-draft or committed-draft")
    files = packaging["files_sha256"]
    if not isinstance(files, dict) or not files:
        _fail("packaging.files_sha256", "must be a nonempty object")
    for filename, digest in files.items():
        _text(filename, "packaging.files_sha256 path")
        path = PurePosixPath(filename)
        if (path.is_absolute() or "\\" in filename or ":" in filename
                or any(part in ("", ".", "..") for part in filename.split("/"))):
            _fail("packaging.files_sha256", "paths must be normalized relative paths")
        _hex(digest, HEX64, f"packaging.files_sha256[{filename}]")

    _scan_service(data["services"], "services")
    services = _object(data["services"], "services", SERVICES)
    for name, service in services.items():
        where = f"services.{name}"
        _object(service, where, {"local_image_id"}, {"local_tag"})
        _hex(service["local_image_id"], LOCAL_IMAGE_ID, where + ".local_image_id")
        if "local_tag" in service:
            _text(service["local_tag"], where + ".local_tag")

    _hex(data["model_bundle_manifest_sha256"], HEX64,
         "model_bundle_manifest_sha256")

    if "ci" in data:
        ci = _object(data["ci"], "ci", {"purpose", "source_commit", "builds"})
        if ci["purpose"] != "historical-source-evidence":
            _fail("ci.purpose", "must be historical-source-evidence")
        _hex(ci["source_commit"], HEX40, "ci.source_commit")
        if ci["source_commit"] != source["commit"]:
            _fail("ci.source_commit", "must match source.commit")
        builds = _object(ci["builds"], "ci.builds", {"ui", "backend", "workflow"})
        for name, number in builds.items():
            if type(number) is not int or number <= 0:
                _fail(f"ci.builds.{name}", "must be a positive integer")

    if "verification" in data:
        verification = _object(data["verification"], "verification", {"status"})
        if verification["status"] not in ("pending", "passed", "failed"):
            _fail("verification.status", "must be pending, passed or failed")

    if "limitations" in data:
        limitations = data["limitations"]
        if not isinstance(limitations, list):
            _fail("limitations", "must be a list of nonempty strings")
        for index, limitation in enumerate(limitations):
            _text(limitation, f"limitations[{index}]")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.candidate.read_text(encoding="utf-8-sig"),
                          object_pairs_hook=_unique_object)
        validate_candidate(data)
    except (OSError, ValueError) as exc:
        print(f"Invalid local candidate: {exc}", file=sys.stderr)
        return 1
    print("Valid local DRAFT metadata. Publication and CD deployment are not authorized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
