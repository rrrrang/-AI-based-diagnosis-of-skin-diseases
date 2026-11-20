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
GRADCAM_CHECKS = (
    "gradcam_overlay_available", "gradcam_authenticated_png", "gradcam_png_decoded",
    "gradcam_unauthenticated_blocked", "gradcam_patient_blocked", "gradcam_visible_in_doctor_ui",
)
DOCTOR_MODEL_UI_CHECKS = (
    "ensemble_decision_visible_in_doctor_ui", "three_model_rows_match_api",
)


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


def _verify_gradcam_document(document, name, *, focused):
    checked = document["checked"]
    required = GRADCAM_CHECKS + (("gradcam_unassigned_doctor_blocked",) if focused else ())
    if any(checked.get(key) is not True for key in required):
        raise ValueError(f"Grad-CAM storage/access/UI evidence is missing: {name}")
    image = document.get("gradcam")
    if not isinstance(image, dict):
        raise ValueError(f"Grad-CAM PNG evidence is missing: {name}")
    if (image.get("http_status") != 200 or image.get("content_type") != "image/png"
            or image.get("anonymous_status") != 401 or image.get("patient_status") != 403
            or (focused and image.get("unassigned_doctor_status") != 404)):
        raise ValueError(f"Grad-CAM content or authorization evidence is invalid: {name}")
    for key in ("byte_length", "width", "height", "ui_natural_width", "ui_natural_height"):
        minimum = 8 if key == "byte_length" else 0
        if type(image.get(key)) is not int or image[key] <= minimum:
            raise ValueError(f"Grad-CAM decoded PNG dimensions or bytes are invalid: {name}")
    if image["width"] != image["ui_natural_width"] or image["height"] != image["ui_natural_height"]:
        raise ValueError(f"Grad-CAM displayed image differs from the authenticated PNG: {name}")


def _verify_evidence(results, identity, *, focused):
    results = Path(results).resolve(strict=True)
    expected = identity["expected_model_versions"]
    for count in (2, 3):
        prefix = "gradcam" if focused else "workflow"
        path = results / f"{prefix}-{count}-photos.json"
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Workflow evidence must not be redirected")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError(f"Successful model evidence is missing: {path.name}") from None
        if (not isinstance(document, dict) or document.get("status") != "passed"
                or type(document.get("photo_count")) is not int or document["photo_count"] != count):
            raise ValueError(f"Successful photo-count evidence is missing: {path.name}")
        scope = "gradcam-only" if focused else "full-workflow"
        if document.get("verification_scope") != scope:
            raise ValueError(f"Workflow evidence scope must be {scope}: {path.name}")
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
        _verify_gradcam_document(document, path.name, focused=focused)
        if not focused and any(checked.get(key) is not True for key in DOCTOR_MODEL_UI_CHECKS):
            raise ValueError(f"Doctor ensemble/model UI evidence is missing: {path.name}")


def verify_workflow_model_evidence(results, identity):
    """Require both full flows to prove locked models and saved, authorized PNGs."""
    _verify_evidence(results, identity, focused=False)
    return {"checkpoint_hashes_matched": True, "yolo_six_class_evidence_verified": True,
            "gradcam_storage_access_ui_verified": True,
            "ensemble_decision_visible_in_doctor_ui": True, "three_model_rows_match_api": True,
            "workflow_photo_counts": [2, 3]}


def verify_gradcam_evidence(results, identity):
    """Diagnostic-only evidence must never substitute for the full workflow gate."""
    _verify_evidence(results, identity, focused=True)
    return {"verification_scope": "gradcam-only", "checkpoint_hashes_matched": True,
            "yolo_six_class_evidence_verified": True, "gradcam_storage_access_ui_verified": True,
            "gradcam_unassigned_doctor_blocked": True, "gradcam_photo_counts": [2, 3]}
