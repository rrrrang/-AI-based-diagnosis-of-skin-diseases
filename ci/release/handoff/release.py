"""Validate the four-service publication handoff, not CD readiness.

This is a metadata contract. The publisher must independently observe the three
Jenkins results, packaged-image tests, public repositories and registry content.
Parsing this JSON does not perform those remote checks or authorize deployment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SCHEMA = "skinai.release/v2"
SOURCE_REPOSITORY = "https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases"
SOURCE_BRANCH = "main"
PLATFORM = "linux/amd64"
REPOSITORIES = {
    "api": "docker.io/rlarns982/skinai-api",
    "worker": "docker.io/rlarns982/skinai-worker",
    "patient-ui": "docker.io/rlarns982/skinai-patient-ui",
    "doctor-ui": "docker.io/rlarns982/skinai-doctor-ui",
}
CI_JOBS = {
    "ui": "SkinAI-UI-CI",
    "backend": "SkinAI-Backend-CI",
    "workflow": "SkinAI-Workflow-CI",
}
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
REQUIRED = frozenset({
    "schema", "release_id", "source", "platform", "services", "ci",
    "verification", "evidence_sha256", "deployment",
})
SERVICE_FIELDS = frozenset({
    "repository", "tag", "digest", "image", "platform_digest", "config_digest",
    "local_image_id", "visibility",
})
VERIFICATION = {
    "status": "passed",
    "packaged_workflow": "passed",
    "cleanup": "passed",
    "source_inputs_unchanged": True,
    "registry": "verified",
}
DEPLOYMENT = {
    "status": "not-configured",
    "auth": "demo-token",
    "medical_accuracy_evaluated": False,
}


def _fail(where, message):
    raise ValueError(f"{where}: {message}")


def _object(value, where, fields):
    if not isinstance(value, dict):
        _fail(where, "must be an object")
    if any(not isinstance(key, str) for key in value):
        _fail(where, "keys must be strings")
    missing = set(fields) - value.keys()
    unknown = value.keys() - set(fields)
    if missing:
        _fail(where, "missing fields: " + ", ".join(sorted(missing)))
    if unknown:
        _fail(where, "unsupported fields: " + ", ".join(sorted(unknown)))
    return value


def _equal(value, expected, where):
    if type(value) is not type(expected) or value != expected:
        _fail(where, f"must equal {expected!r}")


def _hex(value, pattern, where):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail(where, "invalid lowercase commit or SHA-256 identifier")


def validate_release(data):
    """Return None for contract-compliant publication metadata; never mutate it.

    A valid handoff binds all images and CI evidence to one committed revision.
    Digest syntax alone cannot prove that image bytes exist in a registry, match
    the tested local image, or were uploaded successfully. The publisher owns
    those observations. This contract deliberately retains CD as not configured.
    """
    _object(data, "release", REQUIRED)
    _equal(data["schema"], SCHEMA, "schema")
    _equal(data["platform"], PLATFORM, "platform")

    source = _object(data["source"], "source", {
        "repository", "branch", "commit", "working_tree_dirty",
    })
    _equal(source["repository"], SOURCE_REPOSITORY, "source.repository")
    _equal(source["branch"], SOURCE_BRANCH, "source.branch")
    _equal(source["working_tree_dirty"], False, "source.working_tree_dirty")
    _hex(source["commit"], HEX40, "source.commit")

    ci = _object(data["ci"], "ci", CI_JOBS)
    for role, job in CI_JOBS.items():
        item = _object(ci[role], f"ci.{role}", {"job", "build", "result", "commit"})
        _equal(item["job"], job, f"ci.{role}.job")
        if type(item["build"]) is not int or item["build"] <= 0:
            _fail(f"ci.{role}.build", "must be a positive integer")
        _equal(item["result"], "SUCCESS", f"ci.{role}.result")
        _equal(item["commit"], source["commit"], f"ci.{role}.commit")

    release_id = f"sha-{source['commit'][:12]}-workflow-{ci['workflow']['build']}"
    _equal(data["release_id"], release_id, "release_id")
    services = _object(data["services"], "services", REPOSITORIES)
    for name, repository in REPOSITORIES.items():
        where = f"services.{name}"
        service = _object(services[name], where, SERVICE_FIELDS)
        _equal(service["repository"], repository, where + ".repository")
        _equal(service["tag"], release_id, where + ".tag")
        _equal(service["visibility"], "public", where + ".visibility")
        for field in ("digest", "platform_digest", "config_digest", "local_image_id"):
            _hex(service[field], DIGEST, where + "." + field)
        _equal(service["image"], repository + "@" + service["digest"], where + ".image")
        # For a single-platform manifest digest may equal platform_digest. Local
        # IDs also vary by Docker image store. Equality or inequality between
        # these fields is not a substitute for the publisher's byte checks.

    verification = _object(data["verification"], "verification", VERIFICATION)
    for name, expected in VERIFICATION.items():
        _equal(verification[name], expected, "verification." + name)
    evidence = _object(data["evidence_sha256"], "evidence_sha256", {
        "candidate", "preview_summary", "model_manifest",
    })
    for name, value in evidence.items():
        _hex(value, HEX64, "evidence_sha256." + name)
    deployment = _object(data["deployment"], "deployment", DEPLOYMENT)
    for name, expected in DEPLOYMENT.items():
        _equal(deployment[name], expected, "deployment." + name)


def _unique_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON field: {key}")
        value[key] = child
    return value


def load_release(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      object_pairs_hook=_unique_object)
    validate_release(data)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    args = parser.parse_args(argv)
    try:
        data = load_release(args.release)
    except (OSError, ValueError) as exc:
        print(f"Invalid publication handoff: {exc}", file=sys.stderr)
        return 1
    print(f"Valid publication metadata: {data['release_id']}. CD configuration remains pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())