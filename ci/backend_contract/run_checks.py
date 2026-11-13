"""Backend contract checks only: no Docker builds, publishing or deployment."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

PACKAGE = Path(__file__).resolve().parent
CI_ROOT = PACKAGE.parents[1]
MIN_TESTS = {"backend": 17, "policy": 1, "http": 20}
REQUIRED_SOURCE = ("main.py", "requirements-backend.txt", "app/routers/cases.py",
                   "tests/test_backend.py", "tests/test_analysis_queue.py", "tests/test_photo_contract.py", "ensemble/test_policy.py")


def check_result(name, code, output, http_report=None):
    """Exit zero alone is not evidence that the mandatory checks ran."""
    counts = re.findall(r"^Ran (\d+) tests? in", output, re.MULTILINE)
    count = int(counts[-1]) if counts else 0
    errors = []
    if code != 0:
        errors.append(f"Process exit code: {code}")
    if count < MIN_TESTS[name]:
        errors.append(f"Expected at least {MIN_TESTS[name]} tests; ran {count}")
    if not re.search(r"^OK\s*$", output, re.MULTILINE):
        errors.append("A complete OK result without skips or expected failures is required")
    if name == "http":
        if not isinstance(http_report, dict):
            errors.append("Missing HTTP verification report")
        else:
            expected = http_report.get("expected_tests", [])
            executed = http_report.get("executed_tests", [])
            if (len(expected) < MIN_TESTS[name] or len(set(expected)) != len(expected)
                    or len(set(executed)) != len(executed) or not set(expected).issubset(executed)):
                errors.append("Mandatory HTTP checks were missing or duplicated")
            if http_report.get("status") != "PASS" or http_report.get("tests_run") != count:
                errors.append("HTTP report disagrees with successful execution")
            for key in ("failures", "errors", "skipped", "expected_failures", "unexpected_successes"):
                if http_report.get(key) != 0:
                    errors.append(f"HTTP {key} must be zero")
    return count, errors


def git_value(root, *arguments):
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=15)
        return result.stdout.strip() if result.returncode == 0 else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=CI_ROOT,
                        help="Backend checkout; may be separate from the CI branch")
    parser.add_argument("--output-root", type=Path, default=CI_ROOT / "verification/backend_ci")
    parser.add_argument("--port", type=int, default=0, help="0 selects a free local port")
    args = parser.parse_args()
    if args.port != 0 and not 1024 <= args.port <= 65535:
        parser.error("Use port 0, or 1024 through 65535")
    root = args.source_root.resolve()
    output = args.output_root.resolve() / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6])
    output.mkdir(parents=True)
    temp = output / "temp"
    temp.mkdir()
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
    # Never select a shared database or inherit another application's module path.
    for key in ("SKINAI_DB_PATH", "SKINAI_PHOTO_DIR", "SKINAI_DEMO_DOCTOR_TOKENS", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    commands = [
        ("backend", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]),
        ("policy", [sys.executable, "-B", "-m", "unittest", "ensemble.test_policy", "-v"]),
        ("http", [sys.executable, "-B", str(PACKAGE / "check_http.py"), "--source-root", str(root),
                  "--output", str(output / "http"), "--port", str(args.port)]),
    ]
    report = {"status": "FAIL", "scope": "Backend API; synthetic images and model outcomes",
              "steps": [], "started_at": datetime.now(timezone.utc).isoformat(),
              "python": sys.version, "source_root": str(root)}
    return_code = 1
    try:
        missing = [path for path in REQUIRED_SOURCE if not (root / path).is_file()]
        if missing:
            raise ValueError("Choose the backend checkout with --source-root. Missing: " + ", ".join(missing))
        report["source_commit"] = git_value(root, "rev-parse", "HEAD")
        report["source_tracked_changes"] = git_value(root, "diff", "--stat", "HEAD")
        report["ci_commit"] = git_value(CI_ROOT, "rev-parse", "HEAD")
        report["check_files_sha256"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(PACKAGE.glob("*.py"))
        }
        for name, command in commands:
            print(f"--- {name} ---", flush=True)
            result = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
            (output / f"{name}.log").write_text(result.stdout, encoding="utf-8")
            print(result.stdout, end="", flush=True)
            http_report = None
            if name == "http" and (output / "http/http-results.json").is_file():
                http_report = json.loads((output / "http/http-results.json").read_text(encoding="utf-8"))
            count, problems = check_result(name, result.returncode, result.stdout, http_report)
            report["steps"].append({"name": name, "exit_code": result.returncode,
                                    "tests_run": count, "log": f"{name}.log", "problems": problems})
            if problems:
                print(f"STOP: {name} failed. Remaining checks were not run.")
                for problem in problems:
                    print(problem)
                break
        else:
            report["status"] = "PASS"
            return_code = 0
    except Exception as error:
        report["execution_error"] = f"{type(error).__name__}: {error}"
        print(report["execution_error"], file=sys.stderr)
    finally:
        report["tests_run"] = sum(step["tests_run"] for step in report["steps"])
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"RESULT: {report['status']}")
        print("REPORT=" + str(output / "summary.json"))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
