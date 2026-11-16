"""Deploy a generated service Compose file and retain the last verified release."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from zipfile import ZipFile


def source_commit(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    commit = config.get("x-skinai-source-commit") if isinstance(config, dict) else None
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError(f"Invalid source commit in {path.name}")
    return commit


def prepare_smoke(commit, stack, evidence):
    workspace = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    archive = workspace / "source.zip"
    if subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], check=False).returncode:
        subprocess.run(["git", "fetch", "origin", commit], check=True, timeout=120)
    subprocess.run(["git", "archive", "--format=zip", "-o", str(archive), commit,
                    "frontend/patient-frontend"], check=True, timeout=120)
    with ZipFile(archive) as source:
        source.extractall(workspace)
    frontend = workspace / "frontend" / "patient-frontend"
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is not available on the deployment agent")
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True, timeout=600)

    def smoke(phase):
        output = evidence / phase
        output.mkdir(parents=True, exist_ok=True)
        (output / "source-commit.txt").write_text(commit + "\n", encoding="ascii")
        subprocess.run(
            ["node", "node_modules/playwright/cli.js", "test", "--config", "playwright.release.config.ts"],
            cwd=frontend, env={**os.environ, "SKINAI_E2E_OUTPUT": str(output)},
            check=True, timeout=1000,
        )

    return smoke


def deploy(candidate, prepare, run=subprocess.run):
    with ExitStack() as stack:
        deploy_with_checks(candidate, prepare, stack, run)


def deploy_with_checks(candidate, prepare, stack, run):
    previous = candidate.with_name("last-good.json")
    pending = candidate.with_name("last-good.pending")
    docker = ["docker", "compose"]

    def compose(path, *args):
        run([*docker, "-f", str(path), *args], check=True, timeout=900)

    compose(candidate, "config", "--quiet")
    if previous.exists():
        compose(previous, "config", "--quiet")
    compose(candidate, "pull")
    verify_candidate = prepare(source_commit(candidate), stack)
    verify_previous = prepare(source_commit(previous), stack) if previous.exists() else None
    shutil.copyfile(candidate, pending)
    try:
        compose(candidate, "up", "-d", "--wait", "--wait-timeout", "180")
        verify_candidate("candidate")
        pending.replace(previous)
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt):
        if verify_previous is not None:
            print("Restoring last verified release", flush=True)
            compose(previous, "up", "-d", "--wait", "--wait-timeout", "180")
            verify_previous("rollback")
            print("Rollback smoke test passed", flush=True)
        else:
            print("Stopping failed initial deployment; retaining volumes", flush=True)
            compose(candidate, "down")
        raise
    finally:
        pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    deploy(args.compose.resolve(strict=True), lambda commit, stack: prepare_smoke(commit, stack, evidence))


if __name__ == "__main__":
    main()
