"""Build and test an isolated Docker API; never publish or deploy it."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from uuid import uuid4

PACKAGE = Path(__file__).resolve().parent
OWNER = "SkinAI-Backend-CI"
OWNER_LABEL = "com.skinai.ci.owner"
RUN_LABEL = "com.skinai.ci.run"


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


class Docker:
    def __init__(self, executable):
        self.executable = executable

    def call(self, *arguments, log=None, timeout=60):
        command = [self.executable, "--context", "desktop-linux", *arguments]
        if log is not None:
            with log.open("w", encoding="utf-8") as output:
                result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                        timeout=timeout, check=False)
            text = log.read_text(encoding="utf-8", errors="replace")
        else:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=timeout, check=False)
            text = result.stdout
        if result.returncode:
            raise RuntimeError(f"Docker {arguments[0]} failed (exit {result.returncode})"
                               + (f"; see {log.name}" if log else ""))
        return text.strip()


def read_state(output):
    state = json.loads((output / "state.json").read_text(encoding="utf-8"))
    nonce = state.get("nonce", "")
    if (state.get("owner") != OWNER or not re.fullmatch(r"[a-f0-9]{32}", nonce)
            or state.get("container") != "skinai-backend-ci-" + nonce
            or state.get("image") != "skinai-backend-ci:" + nonce):
        raise ValueError("Unexpected cleanup state; no Docker resources will be removed")
    return state


def check_labels(docker, kind, name, state):
    labels = json.loads(docker.call(kind, "inspect", "--format", "{{json .Config.Labels}}", name))
    if not isinstance(labels, dict) or labels.get(OWNER_LABEL) != OWNER or labels.get(RUN_LABEL) != state["nonce"]:
        raise ValueError("Ownership labels do not match; refusing to remove " + name)


def cleanup(output, docker):
    state = read_state(output)
    problems = []
    try:
        present = docker.call("container", "ls", "--all", "--filter",
                              "name=^/" + state["container"] + "$", "--format", "{{.Names}}")
        if present:
            if present != state["container"]:
                raise ValueError("Unexpected container selection")
            check_labels(docker, "container", state["container"], state)
            # Logs contain only synthetic requests. Never archive inspect/env output.
            try:
                docker.call("container", "logs", state["container"], log=output / "container.log")
            finally:
                docker.call("container", "rm", "--force", state["container"])
    except Exception as error:
        problems.append(f"container: {type(error).__name__}: {error}")
    try:
        present = docker.call("image", "ls", "--filter", "reference=" + state["image"],
                              "--format", "{{.Repository}}:{{.Tag}}")
        if present:
            if present != state["image"]:
                raise ValueError("Unexpected image selection")
            check_labels(docker, "image", state["image"], state)
            docker.call("image", "rm", state["image"])
    except Exception as error:
        problems.append(f"image: {type(error).__name__}: {error}")
    try:
        (output / "doctor-test.env").unlink(missing_ok=True)
    except OSError as error:
        problems.append(f"test credentials: {type(error).__name__}")
    result = {"status": "FAIL" if problems else "PASS", "problems": problems,
              "container": state["container"], "image": state["image"],
              "finished_at": datetime.now(timezone.utc).isoformat()}
    write_json(output / "cleanup.json", result)
    print("DOCKER_CLEANUP=" + result["status"], flush=True)
    return not problems


def wait_ready(docker, container):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = docker.call("container", "inspect", "--format",
                             "{{.State.Status}} {{.State.Health.Status}}", container, timeout=10)
        if status == "running healthy":
            bindings = json.loads(docker.call("container", "inspect", "--format",
                                              "{{json .NetworkSettings.Ports}}", container))
            values = bindings.get("8000/tcp", [])
            if (len(values) != 1 or values[0].get("HostIp") != "127.0.0.1"
                    or not re.fullmatch(r"[0-9]+", values[0].get("HostPort", ""))):
                raise ValueError("Expected one localhost-only test port")
            port = int(values[0]["HostPort"])
            if not 1024 <= port <= 65535:
                raise ValueError("Unexpected test port")
            return f"http://127.0.0.1:{port}"
        if status.startswith(("exited", "dead")) or status.endswith(" unhealthy"):
            raise RuntimeError("Test container did not become healthy: " + status)
        time.sleep(1)
    raise TimeoutError("Test container readiness timed out")


def check_test_result(code, output):
    counts = re.findall(r"^Ran (\d+) tests? in", output, re.MULTILINE)
    tests = int(counts[-1]) if counts else 0
    # A zero exit code with no tests/skipped tests is not a successful check.
    passed = code == 0 and tests == 8 and bool(re.search(r"^OK\s*$", output, re.MULTILINE))
    return tests, passed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    docker = Docker(args.docker)
    output = args.output_root.resolve()
    if args.cleanup:
        if not (output / "state.json").is_file():
            print("No Docker state to clean")
            return 0
        return 0 if cleanup(output, docker) else 1
    if args.source_root is None:
        parser.error("--source-root is required for a new test run")
    source = args.source_root.resolve()
    for path in (source / "main.py", source / "app/routers/cases.py",
                 PACKAGE / "Dockerfile", PACKAGE / "requirements-ci.txt", PACKAGE / "test_container_http.py"):
        if not path.is_file():
            parser.error("Missing required file: " + str(path))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", args.run_id):
        parser.error("Unexpected run ID")
    # Each run gets a fresh output directory and random Docker resource names.
    output.mkdir(parents=True, exist_ok=False)
    nonce = uuid4().hex
    state = {"owner": OWNER, "nonce": nonce, "run_id": args.run_id,
             "container": "skinai-backend-ci-" + nonce, "image": "skinai-backend-ci:" + nonce}
    write_json(output / "state.json", state)  # Record before any Docker mutation.
    report = {"status": "FAIL", "run_id": args.run_id, "source_root": str(source),
              "scope": "Docker API, synthetic photos, no real model inference",
              "stage": "Docker readiness", "tests_run": 0, "test_exit_code": None,
              "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        if docker.call("info", "--format", "{{.OSType}}") != "linux":
            raise RuntimeError("Docker Desktop must be running Linux containers")
        report["stage"] = "image build"
        print("Building an isolated backend image", flush=True)
        docker.call("build", "--platform", "linux/amd64", "--progress=plain",
                    "--build-context", "backend=" + str(source),
                    "--file", str(PACKAGE / "Dockerfile"),
                    "--label", OWNER_LABEL + "=" + OWNER, "--label", RUN_LABEL + "=" + nonce,
                    "--tag", state["image"], str(PACKAGE), log=output / "build.log", timeout=900)
        check_labels(docker, "image", state["image"], state)
        report["stage"] = "container readiness"
        env_file = output / "doctor-test.env"
        tokens = {key: secrets.token_hex(24) for key in ("d1", "d2")}
        env_file.write_text("SKINAI_DEMO_DOCTOR_TOKENS=" + json.dumps(tokens) + "\n", encoding="utf-8")
        docker.call("container", "create", "--name", state["container"],
                    "--label", OWNER_LABEL + "=" + OWNER, "--label", RUN_LABEL + "=" + nonce,
                    "--publish", "127.0.0.1::8000", "--env-file", str(env_file),
                    state["image"], log=output / "create.log")
        docker.call("container", "start", state["container"])
        base_url = wait_ready(docker, state["container"])
        report["base_url"] = base_url
        report["stage"] = "HTTP tests"
        print("Testing only the new container at " + base_url, flush=True)
        command = [sys.executable, "-B", "-X", "utf8", str(PACKAGE / "test_container_http.py"),
                   "--base-url", base_url, "--env-file", str(env_file)]
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        with (output / "tests.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                                    timeout=180, check=False)
        text = (output / "tests.log").read_text(encoding="utf-8", errors="replace")
        print(text, end="", flush=True)
        count, passed = check_test_result(result.returncode, text)
        report.update(tests_run=count, test_exit_code=result.returncode)
        if not passed:
            raise RuntimeError("Require all eight HTTP tests to pass with no skips")
        report["status"] = "PASS"
        report["stage"] = "complete"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], flush=True)
    finally:
        try:
            clean = cleanup(output, docker)
        except Exception as error:
            clean = False
            report["cleanup_error"] = f"{type(error).__name__}: {error}"
        report["cleanup"] = "PASS" if clean else "FAIL"
        if not clean:
            report["status"] = "FAIL"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(output / "summary.json", report)
        print("DOCKER_CHECK_RESULT=" + report["status"], flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
