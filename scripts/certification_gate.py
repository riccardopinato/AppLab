#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APPLAB_VERSION = "0.8.1"
MAX_CERTIFIED_APK_BYTES = 600 * 1024 * 1024

STRICT_GATES: tuple[tuple[str, str], ...] = (
    ("maestro", "Maestro acceptance"),
    ("visual_qa", "Visual QA"),
    ("visual_regression", "Visual regression"),
    ("visual_journey", "Visual journey"),
    ("system_lab", "System UI"),
    ("network_lab", "Network/offline"),
    ("persistence_lab", "Persistence/restart"),
    ("configuration_lab", "Configuration/lifecycle"),
    ("resource_pressure_lab", "Resource pressure/process death"),
    ("background_lab", "Background/Doze recovery"),
    ("storage_lab", "Storage/data integrity"),
    ("upgrade_lab", "Upgrade/migration"),
    ("performance_lab", "Performance"),
)

FAIL_STATES = {"FAIL", "ERROR"}
BLOCK_STATES = {"WARN", "SKIPPED", "NO_BASELINE", "NOT_RUN", "UNKNOWN", ""}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def github_output(name: str, value: str) -> None:
    target = os.getenv("GITHUB_OUTPUT", "").strip()
    if not target:
        return
    with Path(target).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def classify_gate(
    key: str,
    label: str,
    value: object,
    failures: list[dict[str, str]],
    blockers: list[dict[str, str]],
) -> None:
    normalized = str(value or "").strip().upper()
    if normalized == "PASS":
        return
    finding = {
        "gate": key,
        "label": label,
        "observed": normalized or "MISSING",
    }
    if normalized in FAIL_STATES:
        failures.append(finding)
    else:
        blockers.append(finding)


def evaluate(
    result: dict[str, Any],
    contract: dict[str, Any],
    source_apk: Path,
    *,
    api_level: str,
    emulator_profile: str,
    target: str,
    arch: str,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    blockers: list[dict[str, str]] = []

    runtime_result = str(result.get("result", "")).strip().upper()
    if runtime_result != "PASS":
        failures.append(
            {
                "gate": "trusted_runtime",
                "label": "Trusted runtime verdict",
                "observed": runtime_result or "MISSING",
            }
        )

    result_mode = str(result.get("analysis_mode", "")).strip().lower()
    contract_mode = str(contract.get("analysis_mode", "")).strip().lower()
    if result_mode != "certification":
        blockers.append(
            {
                "gate": "analysis_mode",
                "label": "Runtime analysis mode",
                "observed": result_mode or "MISSING",
            }
        )
    if contract_mode != "certification":
        blockers.append(
            {
                "gate": "contract_mode",
                "label": "Build contract analysis mode",
                "observed": contract_mode or "MISSING",
            }
        )

    repository = str(contract.get("repository", "")).strip()
    resolved_sha = str(contract.get("resolved_sha", "")).strip().lower()
    engine = str(contract.get("engine", "")).strip()
    if not repository:
        blockers.append({"gate": "source_repository", "label": "Source repository", "observed": "MISSING"})
    if not re.fullmatch(r"[0-9a-f]{40}", resolved_sha):
        blockers.append({"gate": "source_commit", "label": "Resolved source commit", "observed": resolved_sha or "MISSING"})
    if engine not in {"flutter", "native_android"}:
        blockers.append({"gate": "source_engine", "label": "Build engine", "observed": engine or "MISSING"})

    quality = contract.get("quality_evidence")
    if not isinstance(quality, dict):
        quality = {}
    required_quality = (
        ("analyze", "Static analysis"),
        ("unit_tests", "Unit tests"),
        ("build", "APK build"),
    ) if engine == "flutter" else (
        ("lint", "Android lint"),
        ("unit_tests", "Unit tests"),
        ("build", "APK build"),
    )
    for key, label in required_quality:
        observed = str(quality.get(key, "")).strip().upper()
        if observed == "PASS":
            continue
        finding = {"gate": f"build_{key}", "label": label, "observed": observed or "MISSING"}
        if observed in FAIL_STATES:
            failures.append(finding)
        else:
            blockers.append(finding)

    for key, label in STRICT_GATES:
        classify_gate(key, label, result.get(key), failures, blockers)

    apk_contract = contract.get("apk")
    if not isinstance(apk_contract, dict):
        apk_contract = {}
    policy = contract.get("certification_policy")
    if not isinstance(policy, dict):
        policy = {}
        blockers.append({"gate": "certification_policy", "label": "Certification policy", "observed": "MISSING"})

    expected_hash = str(apk_contract.get("sha256", "")).strip().lower()
    apk_size = int(apk_contract.get("size_bytes", 0) or 0)
    package_id = str(apk_contract.get("package_id", "") or contract.get("package_id", "")).strip()
    version_name = str(apk_contract.get("version_name", "")).strip()
    version_code = str(apk_contract.get("version_code", "")).strip()
    build_variant = str(apk_contract.get("build_variant", "")).strip().lower()
    signing_cert = str(apk_contract.get("signing_cert_sha256", "")).strip().lower()
    signing_subject = str(apk_contract.get("signing_subject", "")).strip()
    expected_signer = str(policy.get("expected_signing_certificate_sha256", "")).strip().lower()
    requires_real_device = bool(policy.get("requires_real_device", False))
    max_apk_bytes = int(policy.get("max_apk_bytes", MAX_CERTIFIED_APK_BYTES) or MAX_CERTIFIED_APK_BYTES)
    if not package_id:
        blockers.append({"gate": "apk_package", "label": "APK package id", "observed": "MISSING"})
    if not version_name:
        blockers.append({"gate": "apk_version_name", "label": "APK version name", "observed": "MISSING"})
    if not version_code:
        blockers.append({"gate": "apk_version_code", "label": "APK version code", "observed": "MISSING"})

    if build_variant == "debug":
        failures.append({"gate": "release_variant", "label": "Production build variant", "observed": "DEBUG"})
    elif build_variant != "release":
        blockers.append({"gate": "release_variant", "label": "Production build variant", "observed": build_variant.upper() or "MISSING"})

    if not signing_cert:
        blockers.append({"gate": "apk_signing", "label": "APK signing certificate", "observed": "MISSING"})
    if "android debug" in signing_subject.lower():
        failures.append({"gate": "apk_signing", "label": "APK signing certificate", "observed": "ANDROID_DEBUG_CERTIFICATE"})
    if expected_signer and signing_cert and signing_cert != expected_signer:
        failures.append({"gate": "apk_signing_identity", "label": "Expected release signing certificate", "observed": "CERTIFICATE_MISMATCH"})

    if apk_size <= 0:
        blockers.append({"gate": "apk_size", "label": "APK size audit", "observed": "MISSING"})
    elif apk_size > max_apk_bytes:
        failures.append({"gate": "apk_size", "label": "APK size audit", "observed": f"{apk_size}_BYTES_EXCEEDS_{max_apk_bytes}"})

    if requires_real_device:
        blockers.append({
            "gate": "real_device",
            "label": "Required physical-device evidence",
            "observed": "NOT_TESTED",
        })

    actual_hash = ""
    if not source_apk.is_file():
        blockers.append(
            {
                "gate": "apk_integrity",
                "label": "Tested APK bytes",
                "observed": "MISSING",
            }
        )
    else:
        actual_hash = sha256(source_apk)
        if not expected_hash:
            blockers.append(
                {
                    "gate": "apk_integrity",
                    "label": "Build contract APK hash",
                    "observed": "MISSING",
                }
            )
        elif expected_hash != actual_hash:
            failures.append(
                {
                    "gate": "apk_integrity",
                    "label": "Build contract APK hash",
                    "observed": "HASH_MISMATCH",
                }
            )

    if failures:
        status = "NOT_CERTIFIED"
    elif blockers:
        status = "BLOCKED"
    else:
        status = "CERTIFIED"

    controls = {key: str(result.get(key, "") or "MISSING").upper() for key, _ in STRICT_GATES}
    controls["interaction_crawl"] = str(result.get("interaction_crawl", "") or "MISSING").upper()
    controls["trusted_runtime"] = runtime_result or "MISSING"

    return {
        "schema_version": 1,
        "applab_version": APPLAB_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "certified": status == "CERTIFIED",
        "analysis_mode": result_mode or "unknown",
        "runtime_result": runtime_result or "MISSING",
        "failures": failures,
        "blockers": blockers,
        "source": {
            "repository": repository,
            "resolved_sha": resolved_sha,
            "engine": engine,
        },
        "build_quality": {
            "checks": quality,
            "required": [key for key, _ in required_quality],
        },
        "apk": {
            "package_id": package_id,
            "version_name": version_name,
            "version_code": version_code,
            "size_bytes": apk_size,
            "max_certified_size_bytes": max_apk_bytes,
            "size_audit": "PASS" if 0 < apk_size <= max_apk_bytes else "FAIL",
            "build_variant": build_variant or "unknown",
            "signing_cert_sha256": signing_cert,
            "signing_subject": signing_subject,
            "expected_signing_cert_sha256": expected_signer,
            "sha256": actual_hash,
            "expected_sha256": expected_hash,
        },
        "applab_controls": controls,
        "real_device": {
            "status": "NOT_TESTED",
            "required": requires_real_device,
            "reason": (
                "Physical-device evidence is required by project certification policy."
                if requires_real_device
                else "Hosted CI certification uses the controlled Android emulator lane; physical-device evidence is recorded separately when required."
            ),
        },
        "apk_sha256": actual_hash,
        "expected_apk_sha256": expected_hash,
        "matrix": [
            {
                "lane": "primary",
                "api_level": str(api_level),
                "emulator_profile": emulator_profile,
                "target": target,
                "arch": arch,
                "status": (
                    "PASS"
                    if status == "CERTIFIED"
                    else "FAIL"
                    if status == "NOT_CERTIFIED"
                    else "BLOCKED"
                ),
            }
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lane = report["matrix"][0]
    lines = [
        "# AppLab Production Certification",
        "",
        f"- Status: **{report['status']}**",
        f"- AppLab: {report['applab_version']}",
        f"- Analysis mode: {report['analysis_mode']}",
        f"- Runtime result: {report['runtime_result']}",
        (
            "- Certified runtime: "
            f"API {lane['api_level']} / {lane['emulator_profile']} / "
            f"{lane['target']} / {lane['arch']}"
        ),
        f"- Repository: {report.get('source', {}).get('repository') or 'unknown'}",
        f"- Commit: {report.get('source', {}).get('resolved_sha') or 'unknown'}",
        f"- Engine: {report.get('source', {}).get('engine') or 'unknown'}",
        f"- APK: {report.get('apk', {}).get('package_id') or 'unknown'} "
        f"{report.get('apk', {}).get('version_name') or '?'} "
        f"({report.get('apk', {}).get('version_code') or '?'})",
        f"- APK size: {report.get('apk', {}).get('size_bytes') or 0} bytes "
        f"[{report.get('apk', {}).get('size_audit') or 'UNKNOWN'}]",
        f"- Build variant: {report.get('apk', {}).get('build_variant') or 'unknown'}",
        f"- Signing certificate: {report.get('apk', {}).get('signing_cert_sha256') or 'unavailable'}",
        f"- APK SHA-256: {report.get('apk_sha256') or 'unavailable'}",
        f"- Real device: {report.get('real_device', {}).get('status', 'UNKNOWN')}",
        "",
        "## Build quality",
        "",
    ]
    for key, value in report.get("build_quality", {}).get("checks", {}).items():
        required = "required" if key in report.get("build_quality", {}).get("required", []) else "supporting"
        lines.append(f"- {key}: **{value}** ({required})")
    lines.extend(["", "## AppLab controls", ""])
    for key, value in report.get("applab_controls", {}).items():
        lines.append(f"- {key}: **{value}**")
    lines.append("")

    if report["failures"]:
        lines.extend(["## Failures", ""])
        for item in report["failures"]:
            lines.append(
                f"- **{item['label']}**: {item['observed']} "
                f"(`{item['gate']}`)"
            )
        lines.append("")

    if report["blockers"]:
        lines.extend(["## Blockers", ""])
        for item in report["blockers"]:
            lines.append(
                f"- **{item['label']}**: {item['observed']} "
                f"(`{item['gate']}`)"
            )
        lines.append("")

    if report["status"] == "CERTIFIED":
        lines.extend(
            [
                "All mandatory production-certification gates passed.",
                "The release APK may be published only from these verified bytes.",
                "",
            ]
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def apply_to_result(
    result_path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any]
    if result_path.is_file():
        try:
            result = load_json(result_path)
        except (OSError, json.JSONDecodeError, ValueError):
            result = {}
    else:
        result = {}

    if not result:
        result = {
            "schema_version": 1,
            "applab_version": APPLAB_VERSION,
            "analysis_mode": "certification",
            "result": "FAIL",
            "reason": "Certification ran without a trusted runtime result.",
            "evidence": {},
        }

    result["applab_version"] = APPLAB_VERSION
    result["certification_status"] = report["status"]
    result["certification"] = report
    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    evidence["certification_json"] = "certification.json"
    evidence["certification_summary"] = "certification.md"
    evidence["evidence_bundle_json"] = "evidence-bundle.json"
    evidence["evidence_bundle_summary"] = "evidence-bundle.md"
    result["evidence"] = evidence
    write_json(result_path, result)
    return result


def self_test() -> None:
    import tempfile

    pass_result = {
        "result": "PASS",
        "analysis_mode": "certification",
        **{key: "PASS" for key, _ in STRICT_GATES},
    }
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        apk = root / "app.apk"
        apk.write_bytes(b"certified-apk")
        contract = {
            "analysis_mode": "certification",
            "repository": "owner/repo",
            "resolved_sha": "a" * 40,
            "engine": "flutter",
            "quality_evidence": {
                "analyze": "PASS",
                "lint": "N/A",
                "unit_tests": "PASS",
                "build": "PASS",
            },
            "certification_policy": {
                "schema_version": 1,
                "requires_real_device": False,
                "expected_signing_certificate_sha256": "",
                "max_apk_bytes": MAX_CERTIFIED_APK_BYTES,
            },
            "apk": {
                "sha256": sha256(apk),
                "size_bytes": apk.stat().st_size,
                "package_id": "com.example.app",
                "version_name": "1.0.0",
                "version_code": "1",
                "build_variant": "release",
                "signing_cert_sha256": "1" * 64,
                "signing_subject": "CN=Production,O=Example",
            },
        }

        certified = evaluate(
            pass_result,
            contract,
            apk,
            api_level="35",
            emulator_profile="pixel_7_pro",
            target="google_apis",
            arch="x86_64",
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["certified"] is True

        warned = dict(pass_result)
        warned["network_lab"] = "WARN"
        blocked = evaluate(
            warned,
            contract,
            apk,
            api_level="35",
            emulator_profile="pixel_7_pro",
            target="google_apis",
            arch="x86_64",
        )
        assert blocked["status"] == "BLOCKED"

        failed = dict(pass_result)
        failed["storage_lab"] = "FAIL"
        rejected = evaluate(
            failed,
            contract,
            apk,
            api_level="35",
            emulator_profile="pixel_7_pro",
            target="google_apis",
            arch="x86_64",
        )
        assert rejected["status"] == "NOT_CERTIFIED"

        wrong_mode = dict(pass_result)
        wrong_mode["analysis_mode"] = "full"
        blocked_mode = evaluate(
            wrong_mode,
            contract,
            apk,
            api_level="35",
            emulator_profile="pixel_7_pro",
            target="google_apis",
            arch="x86_64",
        )
        assert blocked_mode["status"] == "BLOCKED"

        debug_contract = {
            **contract,
            "apk": {**contract["apk"], "build_variant": "debug"},
        }
        debug_rejected = evaluate(
            pass_result, debug_contract, apk,
            api_level="35", emulator_profile="pixel_7_pro",
            target="google_apis", arch="x86_64",
        )
        assert debug_rejected["status"] == "NOT_CERTIFIED"

        debug_signer_contract = {
            **contract,
            "apk": {**contract["apk"], "signing_subject": "CN=Android Debug,O=Android,C=US"},
        }
        signer_rejected = evaluate(
            pass_result, debug_signer_contract, apk,
            api_level="35", emulator_profile="pixel_7_pro",
            target="google_apis", arch="x86_64",
        )
        assert signer_rejected["status"] == "NOT_CERTIFIED"

        hardware_contract = {
            **contract,
            "certification_policy": {**contract["certification_policy"], "requires_real_device": True},
        }
        hardware_blocked = evaluate(
            pass_result, hardware_contract, apk,
            api_level="35", emulator_profile="pixel_7_pro",
            target="google_apis", arch="x86_64",
        )
        assert hardware_blocked["status"] == "BLOCKED"

        bad_contract = {
            **contract,
            "apk": {**contract["apk"], "sha256": "0" * 64},
        }
        mismatch = evaluate(
            pass_result,
            bad_contract,
            apk,
            api_level="35",
            emulator_profile="pixel_7_pro",
            target="google_apis",
            arch="x86_64",
        )
        assert mismatch["status"] == "NOT_CERTIFIED"

    print("AppLab Production Certification Gate self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir")
    parser.add_argument("--contract-root")
    parser.add_argument("--api-level", default="35")
    parser.add_argument("--emulator-profile", default="pixel_7_pro")
    parser.add_argument("--target", default="google_apis")
    parser.add_argument("--arch", default="x86_64")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.report_dir or not args.contract_root:
        raise SystemExit("--report-dir and --contract-root are required")

    report_dir = Path(args.report_dir)
    contract_root = Path(args.contract_root)
    report_dir.mkdir(parents=True, exist_ok=True)

    result_path = report_dir / "result.json"
    contract_path = contract_root / "contract.json"
    source_apk = contract_root / "app.apk"

    if result_path.is_file():
        try:
            result = load_json(result_path)
        except (OSError, json.JSONDecodeError, ValueError):
            result = {}
    else:
        result = {}

    if contract_path.is_file():
        try:
            contract = load_json(contract_path)
        except (OSError, json.JSONDecodeError, ValueError):
            contract = {}
    else:
        contract = {}

    if not result:
        result = {
            "result": "MISSING",
            "analysis_mode": "certification",
            **{key: "MISSING" for key, _ in STRICT_GATES},
        }
    if not contract:
        contract = {
            "analysis_mode": "certification",
            "apk": {},
        }

    report = evaluate(
        result,
        contract,
        source_apk,
        api_level=args.api_level,
        emulator_profile=args.emulator_profile,
        target=args.target,
        arch=args.arch,
    )

    write_json(report_dir / "certification.json", report)
    write_markdown(report_dir / "certification.md", report)
    write_json(report_dir / "evidence-bundle.json", report)
    write_markdown(report_dir / "evidence-bundle.md", report)
    apply_to_result(result_path, report)

    github_output("status", report["status"])
    github_output("certified", "true" if report["certified"] else "false")

    print(f"AppLab Production Certification: {report['status']}")
    return 0 if report["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
