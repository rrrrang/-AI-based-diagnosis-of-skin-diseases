"""Run real UI/API/three-model checks in a separate, temporary Docker environment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys


class WindowsJob:
    """A private job kills only this command's descendants if the runner exits."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t),
                        ("max_ws", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        import ctypes
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run_process(command, *, cwd, env=None, timeout=300):
    """Bound subprocess lifetime, including npm/Playwright preview descendants."""
    command = list(map(str, command))
    job = WindowsJob() if os.name == "nt" else None
    process = None
    try:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if job else 0,
                                   start_new_session=not bool(job))
        if job:
            try:
                job.assign(process)
            except BaseException:
                # Fail closed if the agent disallows nested jobs. Never run untracked.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                raise
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            try:
                if job:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                stdout, _ = process.communicate(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                if job:
                    job.close()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                stdout, _ = process.communicate(timeout=15)
            if isinstance(exc, subprocess.TimeoutExpired):
                raise subprocess.TimeoutExpired(command, timeout, output=stdout) from None
            raise
        return subprocess.CompletedProcess(command, process.returncode, stdout)
    finally:
        if job:
            job.close()
        elif process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def write_state(output, project):
    state = {"schema": 1, "owner": "skinai-ui-workflow", "output": str(output.resolve()),
             "compose_project": project, "services": ["api", "worker"],
             "compose_sha256": hashlib.sha256((output / "compose.json").read_bytes()).hexdigest()}
    temporary = output / "state.json.tmp"
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(output / "state.json")


def load_owned_state(output):
    """Validate local metadata before any Docker action or credential deletion."""
    output = output.resolve()
    for name in ["state.json", "compose.json", ".env.test", "results"]:
        child = output / name
        if child.resolve() != child or child.is_symlink() or child.is_junction():
            raise RuntimeError(f"Refusing redirected cleanup path: {name}")
    state = json.loads((output / "state.json").read_text(encoding="utf-8"))
    project = state.get("compose_project", "")
    if (state.get("schema") != 1 or state.get("owner") != "skinai-ui-workflow"
            or state.get("output") != str(output) or state.get("services") != ["api", "worker"]
            or not re.fullmatch(r"skinai-ui-workflow-[0-9a-f]{8}", project)):
        raise RuntimeError("Refusing cleanup: run ownership metadata does not match")
    raw = (output / "compose.json").read_bytes()
    compose = json.loads(raw)
    if (hashlib.sha256(raw).hexdigest() != state.get("compose_sha256")
            or set(compose) != {"name", "services"} or compose.get("name") != project
            or set(compose.get("services", {})) != {"api", "worker"}
            or any("container_name" in service for service in compose["services"].values())
            or compose["services"]["api"].get("env_file") != [{"path": ".env.test", "required": False}]):
        raise RuntimeError("Refusing cleanup: compose file differs from the owned run")
    return state


def compose_command(docker, output, state):
    return [str(docker), "compose", "--project-name", state["compose_project"],
            "--project-directory", str(output), "-f", str(output / "compose.json")]


def sanitize_text(body, tokens=()):
    for token in tokens:
        if token:
            body = body.replace(token, "[REDACTED]")
    body = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", body)
    body = re.sub(r'''(?i)(\b(?:access_?token|refresh_?token|patient_?token|doctor_?token)[\\"'\s]*[:=][\\"'\s]*)([A-Za-z0-9._~+/=-]+)''',
                  r"\1[REDACTED]", body)
    # Case access tokens and the ephemeral doctor token use token_urlsafe(32).
    # Catch bare assertion values too, including JSON-escaped failure messages.
    return re.sub(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])", "[REDACTED]", body)


def redact_artifacts(output, tokens=()):
    private_env = output / ".env.test"
    tokens = list(tokens)
    if private_env.exists():
        for line in private_env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SKINAI_DEMO_DOCTOR_TOKENS="):
                tokens.extend(value for value in json.loads(line.split("=", 1)[1]).values()
                              if isinstance(value, str) and value)
    results = output / "results"
    for artifact in results.rglob("*"):
        if artifact.is_file() and artifact.suffix in {".json", ".log", ".txt", ".md"}:
            if artifact.is_symlink() or not artifact.resolve().is_relative_to(results):
                raise RuntimeError("Refusing redirected report during credential redaction")
            original = artifact.read_text(encoding="utf-8", errors="replace")
            body = sanitize_text(original, tokens)
            if body != original:
                artifact.write_text(body, encoding="utf-8")


def cleanup_run(output, docker, run=None):
    """Remove only this run's exact Compose resources; safe to repeat after abort."""
    output = output.resolve()
    if not output.exists():
        return {"test_containers_cleaned": True, "cleanup_skipped": "run folder absent"}
    if not (output / "state.json").exists():
        if any((output / name).exists() for name in ["compose.json", ".env.test"]):
            raise RuntimeError("Refusing cleanup without state.json ownership metadata")
        return {"test_containers_cleaned": True, "cleanup_skipped": "run not initialized"}
    state = load_owned_state(output)
    project = state["compose_project"]
    redact_artifacts(output)

    def invoke(command, **kwargs):
        if run:
            return run(command, **kwargs)
        result = run_process(command, cwd=output, timeout=kwargs.get("timeout", 60))
        if result.returncode:
            raise RuntimeError(f"Cleanup command failed ({result.returncode}): {sanitize_text(result.stdout[-2000:])}")
        return result.stdout

    def ids(kind):
        command = ([docker, "ps", "-a", "-q", "--no-trunc"] if kind == "container"
                   else [docker, "network", "ls", "-q", "--no-trunc"])
        values = invoke(command + ["--filter", f"label=com.docker.compose.project={project}"], timeout=30).split()
        if any(not re.fullmatch(r"[0-9a-f]{12,64}", value) for value in values):
            raise RuntimeError("Refusing unexpected Docker resource identifier")
        return values

    for kind in ["container", "network"]:
        resources = ids(kind)
        if not resources:
            continue
        inspected = json.loads(invoke([docker, kind, "inspect", *resources], timeout=30))
        if {item.get("Id") for item in inspected} != set(resources):
            raise RuntimeError("Docker inspection did not match the requested resources")
        for item in inspected:
            labels = item.get("Config", {}).get("Labels", {}) if kind == "container" else item.get("Labels", {})
            labels = labels or {}
            name = item.get("Name", "").lstrip("/")
            if labels.get("com.docker.compose.project") != project:
                raise RuntimeError("Refusing cleanup of a different Compose project")
            if kind == "container":
                service = labels.get("com.docker.compose.service")
                config_file = labels.get("com.docker.compose.project.config_files", "")
                if (service not in state["services"] or name != f"{project}-{service}-1"
                        or labels.get("com.docker.compose.oneoff", "false").lower() != "false"
                        or Path(config_file).resolve() != output / "compose.json"):
                    raise RuntimeError("Refusing cleanup of an unexpected container or source file")
            elif name != f"{project}_default" or labels.get("com.docker.compose.network") != "default":
                raise RuntimeError("Refusing cleanup of an unexpected network")
    invoke(compose_command(docker, output, state) + ["down", "--timeout", "20"], log="cleanup.log", timeout=90)
    if ids("container") or ids("network"):
        raise RuntimeError("Owned Docker resources remain after cleanup")
    # Compose env_file is optional so this deletion does not break repeat cleanup.
    (output / ".env.test").unlink(missing_ok=True)
    return {"test_containers_cleaned": True, "compose_project": project}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--cleanup", action="store_true", help="Clean only an existing run's owned resources")
    parser.add_argument("--models", type=Path)
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New run folder; must not exist")
    parser.add_argument("--docker", required=True)
    parser.add_argument("--node-dir", type=Path)
    parser.add_argument("--browsers", type=Path)
    parser.add_argument("--image", default="skinai-backend-ensemble:20261113")
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    if args.cleanup:
        try:
            print(json.dumps(cleanup_run(output, args.docker), indent=2), flush=True)
            return 0
        except (Exception, KeyboardInterrupt) as exc:
            print(sanitize_text(f"CLEANUP FAILED: {exc}"), flush=True)
            return 1
    for required in ["models", "sample", "node_dir", "browsers"]:
        if getattr(args, required) is None:
            parser.error(f"--{required.replace('_', '-')} is required unless --cleanup is used")
    for path in [repo / "main.py", args.sample, args.models, args.node_dir / "npm.cmd",
                 repo / "frontend/patient-frontend/playwright.workflow.config.ts"]:
        if not path.exists():
            parser.error(f"Required path not found: {path}")
    for port in [18165, 18166, 18167]:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                parser.error(f"Port {port} is already in use; existing server left untouched")
    if output.exists():
        parser.error("Use a new output directory to avoid reusing test data")
    output.mkdir(parents=True)
    results = output / "results"
    results.mkdir()
    for sub in ["data/db", "data/photos"]:
        (output / sub).mkdir(parents=True)
    doctor_token = secrets.token_urlsafe(32)
    private_env = output / ".env.test"
    env = os.environ.copy()
    env.update({"PATH": str(args.node_dir) + os.pathsep + env.get("PATH", ""),
                "CI": "true", "VITE_SKINAI_API": "true", "SKINAI_API_TARGET": "http://127.0.0.1:18165",
                "PLAYWRIGHT_BROWSERS_PATH": str(args.browsers), "PYTHONUTF8": "1",
                "SKINAI_E2E_DOCTOR_TOKEN": doctor_token, "SKINAI_E2E_SAMPLE": str(args.sample.resolve()),
                "SKINAI_E2E_OUTPUT": str(results)})
    report = {"status": "FAILED", "image": args.image, "started_at": datetime.now(timezone.utc).isoformat(),
              "sample_sha256": hashlib.sha256(args.sample.read_bytes()).hexdigest(),
              "scope": "Real API, 3-model execution and UI workflow; not clinical accuracy"}

    def run(command, *, cwd=repo, log="commands.log", timeout=300):
        print("RUN:", " ".join(map(str, command)), flush=True)
        timed_out = False
        try:
            result = run_process(command, cwd=cwd, env=env, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            result = subprocess.CompletedProcess(command, 1, exc.output or "")
        safe_text = sanitize_text(result.stdout, [doctor_token])
        with (results / log).open("a", encoding="utf-8") as handle:
            handle.write("$ " + " ".join(map(str, command)) + "\n" + safe_text + "\n")
        print(safe_text[-10000:], flush=True)
        if timed_out:
            raise RuntimeError(f"Command timed out after {timeout}s; owned process tree stopped; see {log}")
        if result.returncode:
            raise RuntimeError(f"Command failed ({result.returncode}); see {log}")
        return result.stdout

    def existing_containers():
        result = run_process([args.docker, "ps", "-a", "--no-trunc", "--format", "{{.ID}} {{.State}}"], cwd=repo, timeout=30)
        if result.returncode:
            raise RuntimeError("Could not capture existing Docker containers")
        raw = result.stdout
        return dict(line.split(maxsplit=1) for line in raw.splitlines() if line.strip())

    compose = [args.docker, "compose", "-f", str(output / "compose.json")]
    started = False
    before = {}
    try:
        report["image_id"] = run([args.docker, "image", "inspect", args.image, "--format", "{{.Id}}"]).strip()
        before = existing_containers()
        mounts = [f"{(repo / 'app').as_posix()}:/srv/app:ro",
                  f"{(repo / 'ensemble').as_posix()}:/srv/ensemble:ro",
                  f"{(repo / 'main.py').as_posix()}:/srv/main.py:ro"]
        shared = {"image": args.image, "environment": {"SKINAI_DB_PATH": "/data/db/backend.sqlite3", "SKINAI_PHOTO_DIR": "/data/photos"},
                  "read_only": True, "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                  "tmpfs": ["/tmp:rw,nosuid,nodev,size=134217728,mode=1777"]}
        api = {**shared, "env_file": [{"path": ".env.test", "required": False}], "ports": ["127.0.0.1:18165:8000"],
               "volumes": mounts + ["./data/db:/data/db", "./data/photos:/data/photos"],
               "mem_limit": "512m", "cpus": 1,
               "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"],
                               "interval": "5s", "timeout": "4s", "retries": 12}}
        worker = {**shared, "command": ["python", "/srv/support/worker_entry.py", "--mobilenet-root", "/models/mobilenet",
                          "--resnet-root", "/models/resnet50", "--yolo-root", "/models/yolo", "--thresholds", "/srv/ensemble/thresholds.example.json"],
                  "depends_on": {"api": {"condition": "service_healthy"}},
                  "volumes": mounts + ["./data/db:/data/db", "./data/photos:/data/photos:ro", f"{args.models.resolve().as_posix()}:/models:ro"],
                  "mem_limit": "4g", "cpus": 2, "pids_limit": 128, "network_mode": "none",
                  "healthcheck": {"test": ["CMD", "python", "/srv/support/worker_health.py"], "interval": "5s", "timeout": "4s", "start_period": "45s", "retries": 12}}
        project = "skinai-ui-workflow-" + secrets.token_hex(4)
        (output / "compose.json").write_text(json.dumps({"name": project, "services": {"api": api, "worker": worker}}, indent=2), encoding="utf-8")
        write_state(output, project)
        private_env.write_text("SKINAI_DEMO_DOCTOR_TOKENS=" + json.dumps({"d1": doctor_token}) + "\n", encoding="utf-8")
        compose = compose_command(args.docker, output, load_owned_state(output))
        report["compose_project"] = project
        report["source_commit"] = run(["git", "rev-parse", "HEAD"]).strip()
        report["source_changes"] = run(["git", "status", "--short"]).splitlines()
        source_paths = [repo / "main.py", Path(__file__).resolve()]
        for folder in ["app", "ensemble", "frontend/patient-frontend/src", "frontend/doctor-frontend/src",
                       "frontend/patient-frontend/tests/workflow"]:
            source_paths.extend(p for p in (repo / folder).rglob("*") if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".json"})
        report["source_sha256"] = {str(p.relative_to(repo)).replace(chr(92), "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}

        for service in ["patient", "doctor"]:
            run([args.node_dir / "npm.cmd", "ci", "--no-audit", "--no-fund"],
                cwd=repo / f"frontend/{service}-frontend", log=f"{service}-install.log", timeout=300)
        started = True
        run(compose + ["up", "-d", "--wait", "--wait-timeout", "180"], timeout=240)
        for service in ["patient", "doctor"]:
            run([args.node_dir / "npm.cmd", "run", "build", "--", "--outDir", "dist-e2e"],
                cwd=repo / f"frontend/{service}-frontend", log=f"{service}-build.log", timeout=180)
        run([args.node_dir / "npm.cmd", "exec", "--", "playwright", "test", "--config", "playwright.workflow.config.ts"],
            cwd=repo / "frontend/patient-frontend", log="workflow.log", timeout=1000)
        for count in [2, 3]:
            evidence = results / f"workflow-{count}-photos.json"
            if not evidence.exists() or json.loads(evidence.read_text(encoding="utf-8")).get("status") != "passed":
                raise RuntimeError(f"Passing workflow evidence missing: {evidence.name}")
        report["status"] = "PASSED"
    except (Exception, KeyboardInterrupt) as exc:
        report["error"] = sanitize_text(str(exc), [doctor_token])
        print("FAILED:", report["error"], flush=True)
    finally:
        if started:
            try:
                run(compose + ["logs", "--no-color", "worker"], log="worker.log", timeout=30)
            except Exception as exc:
                report["log_error"] = str(exc)
            try:
                report.update(cleanup_run(output, args.docker, run))
            except Exception as exc:
                report["status"] = "FAILED"
                report["cleanup_error"] = str(exc)
            try:
                remaining = existing_containers()
                report["existing_containers_unchanged"] = all(remaining.get(key) == value for key, value in before.items())
                report["existing_container_count"] = len(before)
                if not report["existing_containers_unchanged"]:
                    report["status"] = "FAILED"
            except Exception as exc:
                report["status"] = "FAILED"
                report["preservation_error"] = str(exc)
        # Include patient tokens/headers emitted by Playwright request failure diagnostics.
        redact_artifacts(output, [doctor_token])
        if not started and (output / "state.json").exists():
            try:
                report.update(cleanup_run(output, args.docker, run))
            except Exception as exc:
                report["status"] = "FAILED"
                report["cleanup_error"] = str(exc)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        summary = sanitize_text(json.dumps(report, ensure_ascii=False, indent=2), [doctor_token])
        (results / "summary.json").write_text(summary, encoding="utf-8")
        print(summary, flush=True)
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    from port_lock import run_locked
    sys.exit(run_locked(main))
