"""Deploy a generated service Compose file and retain the last verified release."""

import argparse
import shutil
import subprocess
from pathlib import Path


def deploy(candidate, smoke, run=subprocess.run):
    previous = candidate.with_name("last-good.json")
    pending = candidate.with_name("last-good.pending")
    docker = ["docker", "compose"]

    def compose(path, *args):
        run([*docker, "-f", str(path), *args], check=True, timeout=900)

    compose(candidate, "config", "--quiet")
    if previous.exists():
        compose(previous, "config", "--quiet")
    compose(candidate, "pull")
    shutil.copyfile(candidate, pending)
    try:
        compose(candidate, "up", "-d", "--wait", "--wait-timeout", "180")
        run(smoke, check=True, timeout=1000)
        pending.replace(previous)
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt):
        if previous.exists():
            print("Restoring last verified release", flush=True)
            compose(previous, "up", "-d", "--wait", "--wait-timeout", "180")
        else:
            print("Stopping failed initial deployment; retaining volumes", flush=True)
            compose(candidate, "down")
        raise
    finally:
        pending.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose", type=Path)
    parser.add_argument("smoke", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.smoke:
        parser.error("Provide the smoke-test command after the Compose file")
    deploy(args.compose.resolve(strict=True), args.smoke)


if __name__ == "__main__":
    main()
