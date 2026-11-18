"""Validate the pinned, closed model bundle before importing model code.

The lock is a reviewed build input. Editing both bundle files and their JSON
checksums is insufficient: the raw lock bytes must match TRUSTED_LOCK_SHA256.
No network calls or deserialization libraries are used here.
"""
import argparse
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath

TRUSTED_LOCK_SHA256 = "6a385c64f0980a19cea5f41f013dc082169db745e66ce901a67407a085da1467"
DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "model-lock.json"
MODELS = frozenset(("mobilenet", "resnet50", "yolo"))


def safe_relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Model path must be a nonempty relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Model path contains an unsafe component")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or path.parts[0] not in MODELS:
        raise ValueError("Model path is outside the three approved model roots")
    if any(ord(char) < 32 for char in value):
        raise ValueError("Model path contains a control character")
    return path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in model lock")
        result[key] = value
    return result


def validate_document(document):
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "repository", "source_commits", "files"
    }:
        raise ValueError("Unexpected model lock schema")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("Unsupported model lock version")
    commits = document["source_commits"]
    if not isinstance(commits, dict) or set(commits) != MODELS:
        raise ValueError("Model lock must identify all three source commits")
    if any(not isinstance(value, str) or not re.fullmatch("[0-9a-f]{40}", value)
           for value in commits.values()):
        raise ValueError("Invalid source commit")
    entries = document["files"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("Empty model bundle")
    seen = set()
    present_models = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "model", "path", "sha256", "bytes", "source_commit", "source_url"
        }:
            raise ValueError("Unexpected model file schema")
        relative = safe_relative_path(entry["path"])
        if entry["path"] in seen:
            raise ValueError("Duplicate path in model lock")
        seen.add(entry["path"])
        model = entry["model"]
        if model not in MODELS or relative.parts[0] != model:
            raise ValueError("Model name and file path disagree")
        present_models.add(model)
        if entry["source_commit"] != commits[model]:
            raise ValueError("Model file source commit disagrees with lock")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise ValueError("Invalid model file size")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(
            "[0-9a-f]{64}", entry["sha256"]
        ):
            raise ValueError("Invalid model file checksum")
        if not isinstance(entry["source_url"], str) or not entry["source_url"].startswith("https://"):
            raise ValueError("Invalid source provenance URL")
    if present_models != MODELS:
        raise ValueError("Model bundle does not contain all three models")
    return document


def load_lock(lock_path=DEFAULT_LOCK):
    raw = Path(lock_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != TRUSTED_LOCK_SHA256:
        raise ValueError("Model lock does not match the pinned trusted checksum")
    return validate_document(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))


def _is_link(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def verify_bundle(models_root, lock_path=DEFAULT_LOCK):
    document = load_lock(lock_path)
    root = Path(models_root).absolute()
    if _is_link(root) or not root.is_dir():
        raise ValueError("Model root must be an existing physical directory")
    expected = {entry["path"] for entry in document["files"]}
    actual = set()
    # Refuse unexpected code as well as symlinks, including directory links.
    for path in root.rglob("*"):
        if _is_link(path):
            raise ValueError("Model bundle contains a symbolic link or junction")
        mode = path.stat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("Model bundle contains a non-regular file")
        actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError("Model bundle file set mismatch: missing=" + repr(missing) + ", extra=" + repr(extra))
    for entry in document["files"]:
        relative = safe_relative_path(entry["path"])
        path = root.joinpath(*relative.parts)
        # Every component must remain physical and below the approved root.
        for parent in (path, *path.parents):
            if _is_link(parent):
                raise ValueError("Model path contains a symbolic link or junction")
            if parent == root:
                break
        if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
            raise ValueError("Model file escaped the bundle root")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if path.stat().st_size != entry["bytes"] or digest != entry["sha256"]:
            raise ValueError("Model bundle checksum or size mismatch: " + entry["path"])
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=Path("/models"))
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    args = parser.parse_args()
    document = verify_bundle(args.models_root, args.lock)
    print("MODEL_BUNDLE_VERIFIED: mobilenet, resnet50, yolo (" +
          str(len(document["files"])) + " pinned files)", flush=True)


if __name__ == "__main__":
    main()
