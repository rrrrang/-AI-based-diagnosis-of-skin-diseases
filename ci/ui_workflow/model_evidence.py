"""Bind real workflow results to the reviewed three-model lock, not image tags.

Used by the mounted workflow and the packaged-image preview. It reads only the
committed model lock/guard and synthetic workflow reports, never runtime secrets.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import types


LOCK_PATH = "ci/release/backend/model-lock.json"
GUARD_PATH = "ci/release/backend/support/model_guard.py"
MODEL_NAMES = frozenset(("mobilenet", "resnet50", "yolo"))


def load_model_identity(repo):
    """Use this checkout's own pinned guard to validate its committed lock."""
    repo = Path(repo).resolve(strict=True)
    lock, guard = repo / LOCK_PATH, repo / GUARD_PATH
    for path in (lock, guard):
        for item in (path, *path.parents):
            if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
                raise ValueError("Model verification input must not be redirected")
            if item == repo:
                break
    lock_raw, guard_raw = lock.read_bytes(), guard.read_bytes()
    # Execute the exact reviewed guard bytes whose hash is recorded below. The
    # guard uses only the standard library and does not deserialize any weights.
    module = types.ModuleType("skinai_workflow_model_guard")
    module.__file__ = str(guard)
    exec(compile(guard_raw, str(guard), "exec"), module.__dict__)
    document = module.load_lock(lock)
    if lock.read_bytes() != lock_raw or guard.read_bytes() != guard_raw:
        raise ValueError("Model verification inputs changed during validation")
    expected = {}
    for entry in document["files"]:
        if Path(entry["path"]).suffix.lower() not in {".pt", ".pth"}:
            continue
        model = entry["model"]
        if model in expected:
            raise ValueError("Model lock must contain one checkpoint for each model")
        expected[model] = entry["sha256"]
    if set(expected) != MODEL_NAMES:
        raise ValueError("Model lock must identify all three checkpoint hashes")
    return {
        "model_lock_sha256": hashlib.sha256(lock_raw).hexdigest(),
        "model_guard_sha256": hashlib.sha256(guard_raw).hexdigest(),
        "expected_model_versions": expected,
    }


def verify_workflow_model_evidence(results, identity):
    """Require both photo-count runs to prove the exact locked models executed."""
    results = Path(results).resolve(strict=True)
    expected = identity["expected_model_versions"]
    for count in (2, 3):
        path = results / f"workflow-{count}-photos.json"
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Workflow evidence must not be redirected")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError(f"Successful model evidence is missing: {path.name}") from None
        if (not isinstance(document, dict) or document.get("status") != "passed"
                or type(document.get("photo_count")) is not int or document["photo_count"] != count):
            raise ValueError(f"Successful photo-count evidence is missing: {path.name}")
        versions = document.get("model_versions")
        if not isinstance(versions, dict) or versions != expected:
            raise ValueError(f"Executed checkpoint hashes differ from the committed lock: {path.name}")
        keys = document.get("model_keys")
        if not isinstance(keys, list) or len(keys) != 3 or set(keys) != MODEL_NAMES:
            raise ValueError(f"Three-model evidence is incomplete: {path.name}")
        checked = document.get("checked")
        if (not isinstance(checked, dict) or checked.get("three_real_model_results") is not True
                or checked.get("yolo_six_class_response_checked") is not True):
            raise ValueError(f"Six-class YOLO response evidence is missing: {path.name}")
    return {"checkpoint_hashes_matched": True, "yolo_six_class_evidence_verified": True,
            "workflow_photo_counts": [2, 3]}
