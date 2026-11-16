"""Read explicit, completed Jenkins build evidence without reading credentials.

This helper is for the current local Windows Jenkins controller. It reads only
jobs/<fixed job>/builds/<positive number>/{build.xml,log}; it never discovers a
last successful build, triggers Jenkins, or reads controller security files.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

JOBS = {
    "ui": "SkinAI-UI-CI",
    "backend": "SkinAI-Backend-CI",
    "workflow": "SkinAI-Workflow-CI",
}
BRANCH = "refs/remotes/origin/ci/photo-intake-contract"
REPOSITORY = "https://github.com/rrrrang/-AI-based-diagnosis-of-skin-diseases"
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
LAST_BUILD_REFERENCE = re.compile(
    r"\.\./buildsByBranchName/entry(?:\[([1-9][0-9]*)\])?/hudson\.plugins\.git\.util\.Build"
)
CHECKOUT_LINE = re.compile(r"^Checking out Revision ([0-9a-f]{40}) \(([^\r\n)]+)\)$")


def positive_build_number(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ValueError("Build numbers must be explicit positive integers")
    number = int(value)
    if number > 2_147_483_647:
        raise ValueError("Build number is outside Jenkins integer range")
    return number


def _read_evidence_file(home: Path, path: Path, maximum: int) -> bytes:
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Refusing redirected Jenkins evidence path")
        if item == home:
            break
    if not path.resolve(strict=True).is_relative_to(home):
        raise ValueError("Jenkins evidence escaped the selected controller directory")
    before = path.stat()
    if not path.is_file() or before.st_size > maximum:
        raise ValueError("Jenkins evidence file is missing or exceeds the read limit")
    data = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("Jenkins evidence changed while being read")
    return data


def _revision_sha(build) -> str:
    marked = build.findtext("marked/sha1")
    if not marked or not COMMIT_RE.fullmatch(marked):
        raise ValueError("Missing exact SCM marked revision")
    revision = build.find("revision")
    if revision is None:
        raise ValueError("Missing actual SCM revision")
    if revision.get("reference") == "../marked":
        actual = marked
    else:
        sha = revision.find("sha1")
        if sha is None:
            raise ValueError("Unsupported actual SCM revision representation")
        actual = marked if sha.get("reference") == "../../marked/sha1" else sha.text
    if actual != marked:
        raise ValueError("Actual SCM revision does not match the marked revision")
    return marked


def verify_build_xml(raw: bytes, number: int, commit: str) -> None:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Unsupported XML declaration in Jenkins evidence")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Invalid Jenkins build metadata") from exc
    if root.tag != "flow-build":
        raise ValueError("Expected a Jenkins Pipeline build")
    if root.findtext("completed") != "true" or root.findtext("building") == "true":
        raise ValueError("Jenkins build has not finished")
    if root.findtext("result") != "SUCCESS":
        raise ValueError("Jenkins build did not finish SUCCESS")
    duration = root.findtext("duration") or ""
    if not duration.isdecimal() or int(duration) <= 0:
        raise ValueError("Jenkins build has no completed duration")
    data = root.findall("./actions/hudson.plugins.git.util.BuildData")
    if len(data) != 1:
        raise ValueError("Expected exactly one Git repository in this build")
    urls = [node.text for node in data[0].findall("./remoteUrls/string")]
    if len(urls) != 1 or urls[0] not in {REPOSITORY, REPOSITORY + ".git"}:
        raise ValueError("Jenkins checked an unexpected repository")
    entries = data[0].findall("./buildsByBranchName/entry")
    matches = [entry for entry in entries if entry.findtext("string") == BRANCH]
    if len(matches) != 1:
        raise ValueError("Expected one selected CI branch entry")
    build = matches[0].find("hudson.plugins.git.util.Build")
    if build is None or build.findtext("hudsonBuildNumber") != str(number):
        raise ValueError("SCM evidence belongs to a different build number")
    last = data[0].find("lastBuild")
    reference = LAST_BUILD_REFERENCE.fullmatch(last.get("reference", "")) if last is not None else None
    if reference is None:
        raise ValueError("Unsupported Jenkins last-build SCM representation")
    index = int(reference.group(1) or "1") - 1
    if index >= len(entries) or entries[index] is not matches[0]:
        raise ValueError("Selected CI branch is not the build's last SCM revision")
    if _revision_sha(build) != commit:
        raise ValueError("Jenkins SCM commit does not match the release commit")


def verify_build_log(raw: bytes, commit: str) -> None:
    lines = raw.decode("utf-8", errors="replace").splitlines()
    checkout_lines = [line.strip() for line in lines if "Checking out Revision " in line]
    if len(checkout_lines) != 1:
        raise ValueError("Expected exactly one checkout in the Jenkins console evidence")
    match = CHECKOUT_LINE.fullmatch(checkout_lines[0])
    if match is None or match.group(1) != commit or match.group(2) != BRANCH:
        raise ValueError("Console checkout revision or branch does not match the release")
    nonempty = [line.strip() for line in lines if line.strip()]
    if not nonempty or nonempty[-1] != "Finished: SUCCESS":
        raise ValueError("Jenkins console does not end with Finished: SUCCESS")


def collect_evidence(jenkins_home, commit, builds):
    if not isinstance(commit, str) or COMMIT_RE.fullmatch(commit) is None:
        raise ValueError("A full lowercase 40-character commit SHA is required")
    if not isinstance(builds, dict) or set(builds) != set(JOBS):
        raise ValueError("Provide explicit UI, backend and workflow build numbers")
    original_home = Path(jenkins_home).absolute()
    if original_home.is_symlink() or getattr(original_home, "is_junction", lambda: False)():
        raise ValueError("Refusing a redirected Jenkins home")
    home = original_home.resolve(strict=True)
    evidence, proof = {}, {}
    for key, job in JOBS.items():
        number = positive_build_number(builds[key])
        build_path = home / "jobs" / job / "builds" / str(number)
        xml = _read_evidence_file(home, build_path / "build.xml", 8 * 1024 * 1024)
        log = _read_evidence_file(home, build_path / "log", 64 * 1024 * 1024)
        verify_build_xml(xml, number, commit)
        verify_build_log(log, commit)
        # Re-read metadata to catch a transition between the XML and log reads.
        if xml != _read_evidence_file(home, build_path / "build.xml", 8 * 1024 * 1024):
            raise ValueError("Jenkins metadata changed while collecting evidence")
        evidence[key] = {"job": job, "build": number, "result": "SUCCESS", "commit": commit}
        proof[key] = {
            "build_xml_sha256": hashlib.sha256(xml).hexdigest(),
            "console_log_sha256": hashlib.sha256(log).hexdigest(),
        }
    audit = {
        "schema": "skinai.local-jenkins-evidence-audit/v1",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit, "branch": BRANCH, "files_sha256": proof,
        "scope": "Explicit completed builds; no latest-build inference or credentials read",
    }
    return evidence, audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jenkins-home", type=Path, default=Path("D:/JenkinsHome"))
    parser.add_argument("--ui-build", required=True)
    parser.add_argument("--backend-build", required=True)
    parser.add_argument("--workflow-build", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = args.output.absolute()
        audit_path = output.with_name(output.stem + ".audit.json")
        if output.exists() or audit_path.exists():
            raise ValueError("Use a new evidence output path; existing evidence is not overwritten")
        evidence, audit = collect_evidence(args.jenkins_home, args.commit, {
            "ui": args.ui_build, "backend": args.backend_build, "workflow": args.workflow_build,
        })
        output.parent.mkdir(parents=True, exist_ok=True)
        # Publication code separately checks these records against its exact source.
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print("CI evidence rejected: " + str(exc), file=sys.stderr)
        return 1
    print("CI_EVIDENCE_VERIFIED: UI, backend and workflow SUCCESS at " + args.commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())