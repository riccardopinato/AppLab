#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import smart_test_plan
import impact_engine
from pathlib import Path, PurePosixPath

ALLOWED_EVIDENCE_SUFFIXES = {".yaml", ".yml", ".json"}
MAX_FLOW_BYTES = 1_048_576
MAX_EVIDENCE_BYTES = 10_485_760
VALID_CHECK_STATES = {"PASS", "FAIL", "NOT_RUN", "N/A"}
DEFAULT_CERTIFICATION_POLICY = {
    "schema_version": 1,
    "requires_real_device": False,
    "expected_signing_certificate_sha256": "",
    "max_apk_bytes": 600 * 1024 * 1024,
}

def run_text(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""

def android_build_tool(name: str) -> str:
    direct = shutil.which(name)
    if direct:
        return direct
    sdk = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
    if sdk:
        candidates = sorted((Path(sdk) / "build-tools").glob(f"*/{name}"), reverse=True)
        if candidates:
            return str(candidates[0])
    return ""

def apk_identity(apk: Path) -> dict[str, str]:
    result = {"package_id": "", "version_name": "", "version_code": ""}
    aapt = android_build_tool("aapt")
    if aapt:
        output = run_text([aapt, "dump", "badging", str(apk)])
        line = next((x for x in output.splitlines() if x.startswith("package:")), "")
        for key, pattern in {
            "package_id": r"name='([^']*)'",
            "version_name": r"versionName='([^']*)'",
            "version_code": r"versionCode='([^']*)'",
        }.items():
            match = re.search(pattern, line)
            if match:
                result[key] = match.group(1).strip()
    apkanalyzer = shutil.which("apkanalyzer")
    if apkanalyzer:
        for key, parts in {
            "package_id": ["manifest", "application-id"],
            "version_name": ["manifest", "version-name"],
            "version_code": ["manifest", "version-code"],
        }.items():
            if not result[key]:
                result[key] = run_text([apkanalyzer, *parts, str(apk)]).strip()
    return result

def apk_signing(apk: Path) -> dict[str, str]:
    result = {"certificate_sha256": "", "subject": ""}
    apksigner = android_build_tool("apksigner")
    if not apksigner:
        return result
    output = run_text([apksigner, "verify", "--print-certs", str(apk)])
    subject = re.search(r"Signer #1 certificate DN:\s*(.+)", output)
    digest = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9A-Fa-f:]+)", output)
    if subject:
        result["subject"] = subject.group(1).strip()
    if digest:
        result["certificate_sha256"] = re.sub(r"[^0-9a-f]", "", digest.group(1).lower())
    return result

def detect_build_variant(build_command: str, apk: Path) -> str:
    value = f"{build_command} {apk.name}".lower()
    if "release" in value:
        return "release"
    if "debug" in value:
        return "debug"
    return "unknown"

def load_certification_policy(repo_root: Path, working: PurePosixPath) -> dict[str, Any]:
    policy = dict(DEFAULT_CERTIFICATION_POLICY)
    candidates = [repo_root / ".maestro" / "applab-certification.json"]
    if working != PurePosixPath("."):
        candidates.append(repo_root / Path(working) / ".maestro" / "applab-certification.json")
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError(f"Invalid certification policy: {path}")
        for key in (
            "requires_real_device",
            "expected_signing_certificate_sha256",
            "max_apk_bytes",
        ):
            if key in payload:
                policy[key] = payload[key]
    if not isinstance(policy["requires_real_device"], bool):
        raise ValueError("requires_real_device must be boolean")
    fingerprint = str(policy["expected_signing_certificate_sha256"]).strip().lower()
    fingerprint = re.sub(r"[^0-9a-f]", "", fingerprint)
    if fingerprint and len(fingerprint) != 64:
        raise ValueError("expected_signing_certificate_sha256 must be a SHA-256 digest")
    policy["expected_signing_certificate_sha256"] = fingerprint
    max_bytes = int(policy["max_apk_bytes"])
    if max_bytes <= 0:
        raise ValueError("max_apk_bytes must be positive")
    policy["max_apk_bytes"] = max_bytes
    return policy

def normalize_check_state(value: str) -> str:
    state = value.strip().upper()
    if state not in VALID_CHECK_STATES:
        raise ValueError(f"Invalid build check state: {value!r}")
    return state

def safe_relative(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw or ".")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe relative path: {raw!r}")
    return path

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def copy_evidence_file(source: Path, destination: Path) -> int:
    if source.is_symlink():
        raise ValueError(f"Symlink is not allowed in build contract: {source}")
    if not source.is_file():
        return 0
    if source.suffix.lower() not in ALLOWED_EVIDENCE_SUFFIXES:
        return 0
    size = source.stat().st_size
    if size > MAX_FLOW_BYTES:
        raise ValueError(f"Journey evidence file is too large: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return size

def copy_maestro_tree(repo_root: Path, relative_root: PurePosixPath, output_root: Path) -> int:
    source_root = repo_root / Path(relative_root) / ".maestro"
    if not source_root.is_dir():
        return 0
    total = 0
    for source in sorted(source_root.rglob("*")):
        if source.is_symlink():
            raise ValueError(f"Symlink is not allowed in .maestro: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(repo_root)
        total += copy_evidence_file(source, output_root / relative)
        if total > MAX_EVIDENCE_BYTES:
            raise ValueError("Journey evidence exceeds contract size limit")
    return total

def package(args: argparse.Namespace) -> dict:
    repo_root = Path(args.repo_root).resolve()
    apk = Path(args.apk).resolve()
    output = Path(args.output).resolve()
    working = safe_relative(args.working_directory)
    flow = safe_relative(args.maestro_flow) if args.maestro_flow else None

    if not apk.is_file() or apk.stat().st_size <= 0:
        raise ValueError(f"APK missing or empty: {apk}")
    try:
        apk.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("APK must be inside target repository") from exc

    if output.exists():
        shutil.rmtree(output)
    evidence_root = output / "target-evidence"
    evidence_root.mkdir(parents=True)

    shutil.copy2(apk, output / "app.apk")

    total = copy_maestro_tree(repo_root, PurePosixPath("."), evidence_root)
    if working != PurePosixPath("."):
        total += copy_maestro_tree(repo_root, working, evidence_root)

    if flow:
        source = repo_root / Path(flow)
        total += copy_evidence_file(source, evidence_root / Path(flow))
        if not (evidence_root / Path(flow)).is_file():
            raise ValueError(f"Configured Maestro flow is unavailable or unsupported: {flow}")

    if total > MAX_EVIDENCE_BYTES:
        raise ValueError("Journey evidence exceeds contract size limit")

    packaged_apk = output / "app.apk"
    identity = apk_identity(packaged_apk)
    signing = apk_signing(packaged_apk)
    build_variant = detect_build_variant(args.build_command, apk)
    certification_policy = load_certification_policy(repo_root, working)
    quality_evidence = {
        "analyze": normalize_check_state(args.analyze_status),
        "lint": normalize_check_state(args.lint_status),
        "unit_tests": normalize_check_state(args.test_status),
        "build": normalize_check_state(args.build_status),
    }

    contract = {
        "schema_version": 1,
        "applab_version": "0.9.0",
        "repository": args.repository,
        "resolved_sha": args.resolved_sha,
        "engine": args.engine,
        "working_directory": str(working),
        "package_id": args.package_id.strip(),
        "maestro_flow": str(flow) if flow else "",
        "analysis_mode": args.analysis_mode,
        "analysis_baseline_sha": args.baseline_sha.strip().lower(),
        "analysis_plan": "analysis-plan.json",
        "certification_policy": certification_policy,
        "apk": {
            "path": "app.apk",
            "size_bytes": (output / "app.apk").stat().st_size,
            "sha256": sha256(output / "app.apk"),
            "package_id": identity["package_id"],
            "version_name": identity["version_name"],
            "version_code": identity["version_code"],
            "build_variant": build_variant,
            "signing_cert_sha256": signing["certificate_sha256"],
            "signing_subject": signing["subject"],
        },
        "quality_evidence": quality_evidence,
        "evidence_bytes": total,
    }
    if args.impact_plan:
        impact_path = Path(args.impact_plan).resolve()
        if not impact_path.is_file():
            raise ValueError(f"Impact plan missing: {impact_path}")
        impact = impact_engine.validate(json.loads(impact_path.read_text(encoding="utf-8")))
        if str(impact.get("baseline_sha", "")).strip().lower() != args.baseline_sha.strip().lower():
            raise ValueError("Impact plan baseline SHA mismatch")
        expected_head = str(impact.get("head_sha", "")).strip().lower()
        if expected_head and expected_head != args.resolved_sha.strip().lower():
            raise ValueError("Impact plan HEAD SHA mismatch")
        plan = {
            "schema_version": 1,
            "planner_version": "0.9.0",
            "mode": str(impact.get("effective_mode", args.analysis_mode)),
            "requested_mode": args.analysis_mode,
            "baseline_sha": args.baseline_sha.strip().lower(),
            "changed_files": [str(x.get("path", "")) for x in impact.get("changes", []) if x.get("path")],
            "selected_labs": dict(impact.get("selected_labs", {})),
            "reasons": dict(impact.get("lab_reasons", {})),
            "fallback_full": str(impact.get("effective_mode", "")) == "full" and args.analysis_mode == "fast",
            "adaptive_impact": {
                "lane": impact.get("lane"),
                "risk": impact.get("risk"),
                "confidence": impact.get("confidence"),
                "impacted_modules": impact.get("impacted_modules", []),
                "targeted": impact.get("targeted", {}),
                "shadow_full": impact.get("shadow_full", False),
                "calibration_from_lane": impact.get("calibration_from_lane", ""),
                "predicted_selected_labs": impact.get("predicted_selected_labs", {}),
                "predicted_lab_reasons": impact.get("predicted_lab_reasons", {}),
                "cache_domains": impact.get("cache_domains", []),
                "historical_failure_count": impact.get("historical_failure_count", 0),
                "diff_state": impact.get("diff_state", ""),
            },
        }
    else:
        plan = smart_test_plan.classify(
            smart_test_plan.git_changed_files(repo_root, args.baseline_sha),
            args.analysis_mode,
            args.baseline_sha,
        )
    smart_test_plan.validate_plan(plan)
    (output / "analysis-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    (output / "contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return contract

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "repo"
        root.mkdir()
        apk = root / "app.apk"
        apk.write_bytes(b"APK")
        flow = root / ".maestro" / "smoke.yaml"
        flow.parent.mkdir()
        flow.write_text("appId: example\n---\n- assertVisible: Home\n", encoding="utf-8")
        out = Path(raw) / "out"
        args = argparse.Namespace(
            repo_root=str(root), apk=str(apk), output=str(out),
            repository="owner/repo", resolved_sha="a"*40, engine="flutter",
            working_directory=".", package_id="com.example.app",
            maestro_flow=".maestro/smoke.yaml",
            analysis_mode="fast", baseline_sha="", impact_plan="",
            build_command="flutter build apk --debug",
            analyze_status="PASS", lint_status="N/A",
            test_status="PASS", build_status="PASS",
        )
        contract = package(args)
        assert contract["apk"]["sha256"] == sha256(out / "app.apk")
        assert (out / "target-evidence/.maestro/smoke.yaml").is_file()
        assert (out / "analysis-plan.json").is_file()
    print("AppLab build contract packager self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--apk")
    parser.add_argument("--output")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--engine", choices=("flutter", "native_android"), default="flutter")
    parser.add_argument("--working-directory", default=".")
    parser.add_argument("--package-id", default="")
    parser.add_argument("--maestro-flow", default="")
    parser.add_argument("--analysis-mode", choices=("fast", "full", "certification"), default="full")
    parser.add_argument("--baseline-sha", default="")
    parser.add_argument("--impact-plan", default="")
    parser.add_argument("--build-command", default="")
    parser.add_argument("--analyze-status", default="NOT_RUN")
    parser.add_argument("--lint-status", default="NOT_RUN")
    parser.add_argument("--test-status", default="NOT_RUN")
    parser.add_argument("--build-status", default="PASS")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.apk or not args.output:
        raise SystemExit("--repo-root, --apk and --output are required")
    contract = package(args)
    print(json.dumps(contract, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
