#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

import visual_policy
import system_lab
import network_lab
import persistence_lab
import configuration_lab
import upgrade_lab

ALLOWED_SUFFIXES = {".yaml", ".yml", ".json"}
MAX_APK_BYTES = 600 * 1024 * 1024
MAX_FLOW_BYTES = 1_048_576
MAX_EVIDENCE_BYTES = 10_485_760
DISALLOWED_MAESTRO = re.compile(r"(?mi)^\s*-?\s*(runScript|evalScript)\s*:")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def safe_relative(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw or ".")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe path in build contract: {raw!r}")
    return path

def validate(root: Path, expected_repository: str, expected_sha: str, expected_engine: str) -> dict:
    root = root.resolve()
    contract_path = root / "contract.json"
    apk = root / "app.apk"
    evidence = root / "target-evidence"
    if not contract_path.is_file() or contract_path.is_symlink():
        raise ValueError("contract.json is missing or invalid")
    if not apk.is_file() or apk.is_symlink():
        raise ValueError("app.apk is missing or invalid")

    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported build contract schema")
    if payload.get("repository") != expected_repository:
        raise ValueError("Build contract repository mismatch")
    if payload.get("resolved_sha") != expected_sha:
        raise ValueError("Build contract SHA mismatch")
    if payload.get("engine") != expected_engine:
        raise ValueError("Build contract engine mismatch")

    apk_size = apk.stat().st_size
    if apk_size <= 0 or apk_size > MAX_APK_BYTES:
        raise ValueError(f"APK size is outside trusted limits: {apk_size}")
    expected_apk = payload.get("apk", {})
    if expected_apk.get("path") != "app.apk":
        raise ValueError("Unexpected APK path in contract")
    if int(expected_apk.get("size_bytes", -1)) != apk_size:
        raise ValueError("APK size does not match contract")
    if expected_apk.get("sha256") != sha256(apk):
        raise ValueError("APK SHA-256 does not match contract")

    working = safe_relative(str(payload.get("working_directory", ".")))
    flow_raw = str(payload.get("maestro_flow", "")).strip()
    flow = safe_relative(flow_raw) if flow_raw else None
    package_id = str(payload.get("package_id", "")).strip()
    if package_id and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", package_id):
        raise ValueError("Invalid package id in build contract")

    total = 0
    if evidence.exists():
        for path in sorted(evidence.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Symlink is forbidden in target evidence: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(evidence)
            if ".." in relative.parts:
                raise ValueError("Unsafe target evidence path")
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                raise ValueError(f"Unsupported target evidence file: {relative}")
            size = path.stat().st_size
            if size > MAX_FLOW_BYTES:
                raise ValueError(f"Target evidence file too large: {relative}")
            total += size
            if total > MAX_EVIDENCE_BYTES:
                raise ValueError("Target evidence exceeds trusted size limit")
            if path.suffix.lower() in {".yaml", ".yml"}:
                text = path.read_text(encoding="utf-8", errors="strict")
                if DISALLOWED_MAESTRO.search(text):
                    raise ValueError(f"Executable Maestro script command is forbidden: {relative}")
            elif path.name == "applab-visual.json":
                try:
                    visual_policy.validate_config(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab visual policy: {relative}: {exc}"
                    ) from exc
            elif path.name == "applab-system.json":
                try:
                    system_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab system policy: {relative}: {exc}"
                    ) from exc
            elif path.name == "applab-network.json":
                try:
                    network_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab network policy: {relative}: {exc}"
                    ) from exc
            elif path.name == "applab-persistence.json":
                try:
                    persistence_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab persistence policy: {relative}: {exc}"
                    ) from exc
            elif path.name == "applab-configuration.json":
                try:
                    configuration_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab configuration policy: {relative}: {exc}"
                    ) from exc
            elif path.name == "applab-upgrade.json":
                try:
                    upgrade_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab upgrade policy: {relative}: {exc}"
                    ) from exc

    if flow:
        flow_path = evidence / Path(flow)
        if not flow_path.is_file():
            raise ValueError("Configured Maestro flow is missing from trusted contract")

    return {
        "apk_file": str(apk),
        "target_root": str(evidence),
        "project_root": str(evidence / Path(working)),
        "maestro_flow": str(evidence / Path(flow)) if flow else "",
        "package_id": package_id,
        "working_directory": str(working),
        "evidence_bytes": total,
    }

def emit_github_output(path: str, values: dict) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "target-evidence/.maestro").mkdir(parents=True)
        (root / "app.apk").write_bytes(b"APK")
        flow = root / "target-evidence/.maestro/smoke.yaml"
        flow.write_text("appId: example\n---\n- assertVisible: Home\n", encoding="utf-8")
        (root / "target-evidence/.maestro/applab-network.json").write_text(
            '{"schema_version":1,"required":false,"offline_seconds":1.0}',
            encoding="utf-8",
        )
        (root / "target-evidence/.maestro/applab-persistence.json").write_text(
            '{"schema_version":1,"required":false,"restart_cycles":2}',
            encoding="utf-8",
        )
        (root / "target-evidence/.maestro/applab-configuration.json").write_text(
            '{"schema_version":1,"required":false,"rotation_cycles":1,"background_cycles":1}',
            encoding="utf-8",
        )
        (root / "target-evidence/.maestro/applab-upgrade.json").write_text(
            '{"schema_version":1,"required":false,"settle_seconds":1.0}',
            encoding="utf-8",
        )
        payload = {
            "schema_version": 1, "repository": "owner/repo", "resolved_sha": "a"*40,
            "engine": "flutter", "working_directory": ".", "package_id": "com.example.app",
            "maestro_flow": ".maestro/smoke.yaml",
            "apk": {"path":"app.apk","size_bytes":3,"sha256":sha256(root/"app.apk")},
        }
        (root / "contract.json").write_text(json.dumps(payload), encoding="utf-8")
        result = validate(root, "owner/repo", "a"*40, "flutter")
        assert result["package_id"] == "com.example.app"
        flow.write_text("appId: x\n---\n- runScript: evil.js\n", encoding="utf-8")
        try:
            validate(root, "owner/repo", "a"*40, "flutter")
        except ValueError:
            pass
        else:
            raise AssertionError("runScript must be rejected")
    print("AppLab trusted build contract validator self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    parser.add_argument("--expected-repository", default="")
    parser.add_argument("--expected-sha", default="")
    parser.add_argument("--expected-engine", choices=("flutter","native_android"), default="flutter")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.root:
        raise SystemExit("--root is required")
    result = validate(Path(args.root), args.expected_repository, args.expected_sha, args.expected_engine)
    emit_github_output(args.github_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
