"""Freeze hashes of local build and verification inputs without reading secrets.

Model weights are checked separately by backend/support/model_guard.py.
This snapshot records source and recipe bytes, not registry publication proof.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

UI_APPS = ("patient-frontend", "doctor-frontend")
UI_FILES = (
    "package.json", "package-lock.json", "index.html", "tsconfig.json",
    "tsconfig.app.json", "tsconfig.node.json", "vite.config.ts",
)
REQUIRED_FILES = (
    "main.py",
    "frontend/patient-frontend/playwright.release.config.ts",
    *(f"frontend/{app}/{name}" for app in UI_APPS for name in UI_FILES),
)
INPUT_TREES = (
    "app", "ensemble", "ci/release",
    *(f"frontend/{app}/{folder}" for app in UI_APPS for folder in ("src", "public")),
    "frontend/patient-frontend/tests/workflow",
)
HELPER_TREE = "ci/ui_workflow"
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "dist-e2e",
    "test-results", "playwright-results", "playwright-report", "coverage",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", "results", "temp",
    ".aws", ".codex", ".agents", "credentials", "secrets",
})
EXCLUDED_NAMES = frozenset({
    ".env", ".npmrc", ".pypirc", "credentials", "credentials.json",
    "secrets.json", "secrets.toml", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})
EXCLUDED_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".log", ".tmp", ".bak",
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore",
})
HEX64 = re.compile(r"[0-9a-f]{64}")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _excluded(path: Path) -> bool:
    name = path.name.lower()
    return (name in EXCLUDED_DIRECTORIES or name in EXCLUDED_NAMES
            or name.startswith(".env.") or path.suffix.lower() in EXCLUDED_SUFFIXES)


def _physical(path: Path, root: Path) -> None:
    for item in (path, *path.parents):
        if _is_link(item):
            raise ValueError("Input contains a symbolic link or junction: " + str(path))
        if item == root:
            break
    if not path.resolve(strict=True).is_relative_to(root):
        raise ValueError("Input escaped the source root: " + str(path))


def _tree_files(path: Path, root: Path, python_only=False):
    _physical(path, root)
    if not path.is_dir():
        raise ValueError("Required input directory is missing: " + str(path))
    pending = [path]
    while pending:
        folder = pending.pop()
        for item in sorted(folder.iterdir()):
            # Never open excluded local state or credential files.
            if _excluded(item):
                continue
            _physical(item, root)
            if item.is_dir():
                pending.append(item)
            elif item.is_file():
                if not python_only or item.suffix == ".py":
                    yield item
            else:
                raise ValueError("Input is not a regular file: " + str(item))


def _file_hash(path: Path) -> str:
    before = path.stat()
    with path.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("Input changed while being read: " + str(path))
    return value


def snapshot_inputs(repo) -> dict[str, str]:
    """Return relative POSIX paths and SHA-256 hashes for selected source files.

    Includes application inputs, UI assets/configuration/locks, release recipes,
    workflow Python helpers and the browser workflow tests/pages. Generated
    files and common credential filenames are omitted without opening them.
    """
    root = Path(repo).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository must be a directory")
    selected = set()
    for relative in REQUIRED_FILES:
        path = root / relative
        _physical(path, root)
        if not path.is_file():
            raise ValueError("Required input file is missing: " + relative)
        selected.add(path)
    for relative in INPUT_TREES:
        selected.update(_tree_files(root / relative, root))
    selected.update(_tree_files(root / HELPER_TREE, root, python_only=True))
    return {
        path.relative_to(root).as_posix(): _file_hash(path)
        for path in sorted(selected)
    }


def assert_inputs_unchanged(repo, expected) -> None:
    """Fail if any selected input was added, removed or changed after freezing."""
    if (not isinstance(expected, dict) or not expected
            or any(not isinstance(name, str) or not isinstance(value, str)
                   or HEX64.fullmatch(value) is None
                   for name, value in expected.items())):
        raise ValueError("Expected a nonempty source hash snapshot")
    try:
        actual = snapshot_inputs(repo)
    except (OSError, ValueError) as exc:
        raise ValueError("Unable to recheck frozen inputs: " + str(exc)) from exc
    added = sorted(actual.keys() - expected.keys())
    removed = sorted(expected.keys() - actual.keys())
    changed = sorted(name for name in actual.keys() & expected.keys()
                     if actual[name] != expected[name])
    if added or removed or changed:
        details = []
        for label, names in (("added", added), ("removed", removed), ("changed", changed)):
            if names:
                shown = ", ".join(names[:12])
                details.append(f"{label}: {shown}" + (" ..." if len(names) > 12 else ""))
        raise ValueError("Build or verification inputs changed after freezing; " + "; ".join(details))
