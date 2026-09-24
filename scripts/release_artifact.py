#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

APPLAB_VERSION = "0.7.1"
MARKER_START = "<!-- applab-release:start -->"
MARKER_END = "<!-- applab-release:end -->"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size} B"


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-") or "project"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def github_output(name: str, value: str) -> None:
    target = os.getenv("GITHUB_OUTPUT", "").strip()
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def run_text(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def apk_identity(apk: Path) -> dict[str, str]:
    result = {"package_id": "", "version_name": "", "version_code": ""}
    aapt = shutil.which("aapt")
    if not aapt:
        sdk = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
        if sdk:
            candidates = sorted((Path(sdk) / "build-tools").glob("*/aapt"), reverse=True)
            if candidates:
                aapt = str(candidates[0])
    if aapt:
        output = run_text([aapt, "dump", "badging", str(apk)])
        package_line = next((line for line in output.splitlines() if line.startswith("package:")), "")
        for key, pattern in {
            "package_id": r"name='([^']*)'",
            "version_name": r"versionName='([^']*)'",
            "version_code": r"versionCode='([^']*)'",
        }.items():
            match = re.search(pattern, package_line)
            if match:
                result[key] = match.group(1).strip()

    apkanalyzer = shutil.which("apkanalyzer")
    if apkanalyzer:
        commands = {
            "package_id": ["manifest", "application-id"],
            "version_name": ["manifest", "version-name"],
            "version_code": ["manifest", "version-code"],
        }
        for key, parts in commands.items():
            if not result[key]:
                result[key] = run_text([apkanalyzer, *parts, str(apk)]).strip()
    return result


def commit_summary(repository: str, sha: str) -> str:
    api = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    request = urllib.request.Request(
        f"{api}/repos/{repository}/commits/{sha}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "AppLab-v0.7.1"},
    )
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        message = str(payload.get("commit", {}).get("message", "")).strip()
        first_line = next((line.strip() for line in message.splitlines() if line.strip()), "")
        if first_line:
            return first_line[:240]
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        pass
    return f"Verified commit {sha[:8]}"


def release_block(release: dict[str, Any]) -> str:
    apk = release.get("apk", {})
    lines = [
        MARKER_START,
        "## Verified installable APK",
        "",
        f"- Version: {apk.get('version_name') or 'unknown'}",
        f"- Version code: {apk.get('version_code') or 'unknown'}",
        f"- Package: {apk.get('package_id') or 'unknown'}",
        f"- Size: {apk.get('size_human') or 'unknown'}",
        f"- SHA-256: {apk.get('sha256') or 'unknown'}",
        f"- Change: {release.get('changelog_summary') or 'Verified AppLab commit'}",
    ]
    if release.get("artifact_url"):
        lines.append(f"- Download: {release['artifact_url']}")
    lines.extend([MARKER_END, ""])
    return "\n".join(lines)


def update_summary(path: Path, release: dict[str, Any]) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else "# AppLab report\n"
    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n?", re.DOTALL)
    current = pattern.sub("", current).rstrip()
    path.write_text(current + "\n\n" + release_block(release), encoding="utf-8")


def prepare(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir)
    contract_root = Path(args.contract_root)
    output_dir = Path(args.output_dir)
    result_path = report_dir / "result.json"
    contract_path = contract_root / "contract.json"
    source_apk = contract_root / "app.apk"

    result = load_json(result_path)
    if result.get("result") != "PASS":
        github_output("publish", "false")
        print("Release skipped: trusted AppLab verdict is not PASS.")
        return 0

    contract = load_json(contract_path)
    expected = str(contract.get("apk", {}).get("sha256", "")).lower()
    actual = sha256(source_apk)
    if not expected or expected != actual:
        raise ValueError("Verified APK hash differs from build contract")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    short_sha = args.resolved_sha[:8]
    artifact_name = f"applab-release-{slug(args.history_key)}-{short_sha}"
    apk_name = f"{slug(args.history_key)}-{short_sha}.apk"
    release_apk = output_dir / apk_name
    shutil.copy2(source_apk, release_apk)

    identity = apk_identity(release_apk)
    package_id = (
        identity["package_id"]
        or str(contract.get("package_id", "")).strip()
        or str(result.get("package_id", "")).strip()
    )
    size = release_apk.stat().st_size
    release = {
        "schema_version": 1,
        "applab_version": APPLAB_VERSION,
        "repository": args.repository,
        "resolved_sha": args.resolved_sha,
        "history_key": args.history_key,
        "verified_result": "PASS",
        "workflow_run_id": args.run_id,
        "workflow_run_url": args.run_url,
        "artifact_name": artifact_name,
        "artifact_id": "",
        "artifact_url": "",
        "changelog_summary": (
            args.changelog_summary.strip()
            or commit_summary(args.repository, args.resolved_sha)
        ),
        "apk": {
            "filename": apk_name,
            "package_id": package_id,
            "version_name": identity["version_name"],
            "version_code": identity["version_code"],
            "size_bytes": size,
            "size_human": human_size(size),
            "sha256": actual,
        },
    }
    write_json(output_dir / "release.json", release)
    (output_dir / "README.md").write_text(
        "# AppLab Verified APK\n\n"
        "This APK is byte-for-byte the artifact that passed the trusted AppLab emulator gate.\n\n"
        + release_block(release),
        encoding="utf-8",
    )

    result["release"] = release
    write_json(result_path, result)
    update_summary(report_dir / "summary.md", release)

    github_output("publish", "true")
    github_output("artifact_name", artifact_name)
    github_output("apk_filename", apk_name)
    print(f"Prepared {artifact_name}: {human_size(size)} · {actual}")
    return 0


def bind(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir)
    result_path = report_dir / "result.json"
    result = load_json(result_path)
    release = result.get("release")
    if not isinstance(release, dict):
        raise ValueError("release metadata missing from result.json")
    release["artifact_id"] = args.artifact_id.strip()
    release["artifact_url"] = args.artifact_url.strip()
    result["release"] = release
    write_json(result_path, result)
    update_summary(report_dir / "summary.md", release)
    print(f"Release URL bound: {release['artifact_url']}")
    return 0


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        report = root / "report"
        contract = root / "contract"
        output = root / "release"
        report.mkdir()
        contract.mkdir()
        apk = contract / "app.apk"
        apk.write_bytes(b"verified-apk")
        digest = sha256(apk)
        write_json(contract / "contract.json", {"apk": {"sha256": digest}, "package_id": "com.example"})
        write_json(report / "result.json", {"result": "PASS", "pipeline_status": "success", "package_id": "com.example"})
        (report / "summary.md").write_text("# AppLab report\n", encoding="utf-8")
        prepare(argparse.Namespace(
            report_dir=str(report),
            contract_root=str(contract),
            output_dir=str(output),
            repository="owner/repo",
            resolved_sha="a" * 40,
            history_key="watch-test",
            run_id="1",
            run_url="https://github.com/owner/AppLab/actions/runs/1",
            changelog_summary="Test release",
        ))
        payload = load_json(report / "result.json")
        assert payload["release"]["apk"]["sha256"] == digest
        assert (output / payload["release"]["apk"]["filename"]).is_file()
        bind(argparse.Namespace(
            report_dir=str(report),
            artifact_id="123",
            artifact_url="https://github.com/owner/AppLab/actions/runs/1/artifacts/123",
        ))
        payload = load_json(report / "result.json")
        assert payload["release"]["artifact_id"] == "123"
        assert payload["release"]["artifact_url"].endswith("/artifacts/123")
    print("AppLab release artifact self-test PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("prepare")
    p.add_argument("--report-dir", required=True)
    p.add_argument("--contract-root", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--repository", required=True)
    p.add_argument("--resolved-sha", required=True)
    p.add_argument("--history-key", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--run-url", required=True)
    p.add_argument("--changelog-summary", default="")

    b = sub.add_parser("bind")
    b.add_argument("--report-dir", required=True)
    b.add_argument("--artifact-id", required=True)
    b.add_argument("--artifact-url", required=True)

    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.command == "prepare":
        return prepare(args)
    if args.command == "bind":
        return bind(args)
    parser.error("choose prepare or bind")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
