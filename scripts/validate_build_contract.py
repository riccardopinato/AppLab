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
import resource_pressure_lab
import background_lab
import storage_lab
import upgrade_lab
import smart_test_plan

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

def validate(root: Path, expected_repository: str, expected_sha: str, expected_engine: str, expected_analysis_mode: str = "full") -> dict:
    root = root.resolve()
    contract_path = root / "contract.json"
    apk = root / "app.apk"
    evidence = root / "target-evidence"
    analysis_plan_path = root / "analysis-plan.json"
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
    for field in (
        "package_id",
        "version_name",
        "version_code",
        "build_variant",
        "signing_cert_sha256",
        "signing_subject",
    ):
        value = expected_apk.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"APK {field} must be a string")
    signing_digest = expected_apk.get("signing_cert_sha256", "")
    if signing_digest and not re.fullmatch(r"[0-9a-f]{64}", signing_digest):
        raise ValueError("APK signing_cert_sha256 is invalid")

    quality = payload.get("quality_evidence")
    if not isinstance(quality, dict):
        raise ValueError("quality_evidence is missing from build contract")
    expected_quality_keys = {"analyze", "lint", "unit_tests", "build"}
    if set(quality) != expected_quality_keys:
        raise ValueError("quality_evidence keys mismatch")
    valid_quality_states = {"PASS", "FAIL", "NOT_RUN", "N/A"}
    for key, value in quality.items():
        if value not in valid_quality_states:
            raise ValueError(f"Invalid quality evidence state for {key}: {value!r}")

    working = safe_relative(str(payload.get("working_directory", ".")))
    flow_raw = str(payload.get("maestro_flow", "")).strip()
    flow = safe_relative(flow_raw) if flow_raw else None
    package_id = str(payload.get("package_id", "")).strip()
    analysis_mode = str(payload.get("analysis_mode", "full")).strip().lower()
    baseline_sha = str(payload.get("analysis_baseline_sha", "")).strip().lower()
    if baseline_sha and not re.fullmatch(r"[0-9a-f]{40}", baseline_sha):
        raise ValueError("Invalid analysis baseline SHA")
    if analysis_mode not in {"fast", "full", "certification"}:
        raise ValueError("Invalid analysis mode in build contract")
    if expected_analysis_mode and analysis_mode != expected_analysis_mode:
        raise ValueError("Build contract analysis mode mismatch")
    if payload.get("analysis_plan") != "analysis-plan.json":
        raise ValueError("Missing trusted analysis plan reference")
    if not analysis_plan_path.is_file() or analysis_plan_path.is_symlink():
        raise ValueError("analysis-plan.json is missing or invalid")
    analysis_plan = smart_test_plan.validate_plan(
        json.loads(analysis_plan_path.read_text(encoding="utf-8"))
    )
    if str(analysis_plan.get("baseline_sha", "")).strip().lower() != baseline_sha:
        raise ValueError("Analysis plan baseline SHA mismatch")
    if package_id and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", package_id):
        raise ValueError("Invalid package id in build contract")

    certification_policy = payload.get("certification_policy")
    if not isinstance(certification_policy, dict) or certification_policy.get("schema_version") != 1:
        raise ValueError("Invalid certification_policy in build contract")
    if not isinstance(certification_policy.get("requires_real_device"), bool):
        raise ValueError("requires_real_device must be boolean")
    expected_signer = str(certification_policy.get("expected_signing_certificate_sha256", "")).strip().lower()
    if expected_signer and not re.fullmatch(r"[0-9a-f]{64}", expected_signer):
        raise ValueError("Invalid expected signing certificate digest")
    if int(certification_policy.get("max_apk_bytes", 0) or 0) <= 0:
        raise ValueError("Invalid certification max_apk_bytes")
    if float(certification_policy.get("max_apk_growth_percent", -1)) < 0:
        raise ValueError("Invalid certification max_apk_growth_percent")

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
            elif path.name == "applab-resource.json":
                try:
                    resource_pressure_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab resource-pressure policy: {relative}: {exc}"
                    ) from exc
            elif path.name == "applab-background.json":
                try:
                    background_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab background policy: {relative}: {exc}"
                    ) from exc
            elif path.name == "applab-storage.json":
                try:
                    storage_lab.load_config(path)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"Invalid AppLab storage policy: {relative}: {exc}"
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
        "analysis_mode": analysis_mode,
        "analysis_baseline_sha": baseline_sha,
        "analysis_plan_file": str(analysis_plan_path),
        "quality_evidence_json": json.dumps(quality, separators=(",", ":")),
        "certification_policy_json": json.dumps(certification_policy, separators=(",", ":")),
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
        (root / "target-evidence/.maestro/applab-resource.json").write_text(
            '{"schema_version":1,"required":false,"trim_levels":["RUNNING_LOW"],"process_death_cycles":1}',
            encoding="utf-8",
        )
        (root / "target-evidence/.maestro/applab-background.json").write_text(
            '{"schema_version":1,"required":false,"background_cycles":1,"force_doze":true,"app_standby":true}',
            encoding="utf-8",
        )
        (root / "target-evidence/.maestro/applab-storage.json").write_text(
            '{"schema_version":1,"required":false,"max_files":50,"minimum_free_mb":64}',
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
            "analysis_mode": "fast",
            "analysis_baseline_sha": "b" * 40,
            "analysis_plan": "analysis-plan.json",
            "certification_policy": {
                "schema_version":1,
                "requires_real_device":False,
                "expected_signing_certificate_sha256":"",
                "max_apk_bytes":629145600,
                "max_apk_growth_percent":35.0
            },
            "apk": {
                "path":"app.apk","size_bytes":3,"sha256":sha256(root/"app.apk"),
                "package_id":"com.example.app","version_name":"1.0","version_code":"1",
                "build_variant":"debug","signing_cert_sha256":"","signing_subject":""
            },
            "quality_evidence": {
                "analyze":"PASS","lint":"N/A","unit_tests":"PASS","build":"PASS"
            },
        }
        (root / "analysis-plan.json").write_text(
            json.dumps(smart_test_plan.classify(["lib/home.dart"], "fast", "b" * 40)),
            encoding="utf-8",
        )
        (root / "contract.json").write_text(json.dumps(payload), encoding="utf-8")
        result = validate(root, "owner/repo", "a"*40, "flutter", "fast")
        assert result["package_id"] == "com.example.app"
        assert result["analysis_mode"] == "fast"
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
    parser.add_argument("--expected-analysis-mode", choices=("fast","full","certification"), default="full")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.root:
        raise SystemExit("--root is required")
    result = validate(Path(args.root), args.expected_repository, args.expected_sha, args.expected_engine, args.expected_analysis_mode)
    emit_github_output(args.github_output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
