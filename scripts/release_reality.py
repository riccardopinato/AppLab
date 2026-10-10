#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_VERSION = "4.4.0"
SCHEMA_VERSION = 1

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_VERIFIED = "NOT_VERIFIED"
NOT_APPLICABLE = "N/A"
ALLOWED_STATES = {PASS, FAIL, BLOCKED, NOT_VERIFIED, NOT_APPLICABLE}

LEVELS: tuple[tuple[str, str], ...] = (
    ("IMPLEMENTED", "Implemented"),
    ("STATICALLY_CHECKED", "Statically checked"),
    ("TESTED", "Tested"),
    ("CI_GREEN", "CI green"),
    ("ARTIFACT_BUILT", "Artifact built"),
    ("TRUSTED_RUNTIME_VERIFIED", "Trusted runtime verified"),
    ("PHYSICAL_DEVICE_VERIFIED", "Physical device verified"),
    ("DISTRIBUTION_VERIFIED", "Distribution verified"),
    ("STORE_READY", "Store ready"),
    ("PRODUCTION_RELEASED", "Production released"),
)

FAIL_STATES = {"FAIL", "ERROR", "NOT_CERTIFIED", "FAILED", "FAILURE"}
PASS_STATES = {"PASS", "SUCCESS", "CERTIFIED"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return read_json(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized(value: object) -> str:
    return str(value or "").strip().upper()


def stage(
    key: str,
    state: str,
    reason: str,
    evidence: list[str] | None = None,
    *,
    applicable: bool = True,
) -> dict[str, Any]:
    if state not in ALLOWED_STATES:
        raise ValueError(f"Unsupported release-reality state: {state}")
    label = dict(LEVELS)[key]
    return {
        "key": key,
        "label": label,
        "applicable": applicable,
        "state": state,
        "reason": reason,
        "evidence": evidence or [],
    }


def quality_state(quality: dict[str, Any], key: str) -> str:
    return normalized(quality.get(key))


def check_quality_stage(
    key: str,
    label: str,
    quality: dict[str, Any],
) -> dict[str, Any]:
    observed = quality_state(quality, key)
    if observed == PASS:
        return {
            "state": PASS,
            "reason": f"{label} passed in the bound build contract.",
            "evidence": [f"build-contract.json#quality_evidence.{key}"],
        }
    if observed in FAIL_STATES:
        return {
            "state": FAIL,
            "reason": f"{label} failed in the bound build contract.",
            "evidence": [f"build-contract.json#quality_evidence.{key}"],
        }
    return {
        "state": NOT_VERIFIED,
        "reason": f"{label} has no PASS evidence for this artifact.",
        "evidence": [f"build-contract.json#quality_evidence.{key}"],
    }


def artifact_identity(
    contract: dict[str, Any],
    artifact_path: Path | None,
) -> tuple[dict[str, Any], str, str]:
    apk = contract.get("apk")
    if not isinstance(apk, dict):
        apk = {}

    expected_sha = str(apk.get("sha256", "")).strip().lower()
    expected_size = int(apk.get("size_bytes", 0) or 0)
    actual_sha = ""
    actual_size = 0
    artifact_exists = bool(artifact_path and artifact_path.is_file())

    if artifact_exists and artifact_path is not None:
        actual_sha = sha256_file(artifact_path)
        actual_size = artifact_path.stat().st_size

    same_bytes = bool(
        artifact_exists
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha)
        and actual_sha == expected_sha
        and expected_size > 0
        and actual_size == expected_size
    )

    identity = {
        "path": str(apk.get("path", "app.apk")),
        "package_id": str(apk.get("package_id", "") or contract.get("package_id", "")).strip(),
        "version_name": str(apk.get("version_name", "")).strip(),
        "version_code": str(apk.get("version_code", "")).strip(),
        "build_variant": str(apk.get("build_variant", "")).strip().lower(),
        "size_bytes": expected_size,
        "sha256": expected_sha,
        "actual_size_bytes": actual_size,
        "actual_sha256": actual_sha,
        "signing_cert_sha256": str(apk.get("signing_cert_sha256", "")).strip().lower(),
        "signing_subject": str(apk.get("signing_subject", "")).strip(),
        "same_bytes_verified": same_bytes,
    }

    if not artifact_exists:
        return identity, BLOCKED, "The exact APK bytes are unavailable to Release Reality."
    if not expected_sha or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        return identity, BLOCKED, "The build contract does not contain a valid APK SHA-256."
    if actual_sha != expected_sha:
        return identity, FAIL, "The available APK bytes do not match the build-contract SHA-256."
    if expected_size <= 0 or actual_size != expected_size:
        return identity, FAIL, "The available APK size does not match the build contract."
    required_identity = {
        "package_id": identity["package_id"],
        "version_name": identity["version_name"],
        "version_code": identity["version_code"],
        "signing_cert_sha256": identity["signing_cert_sha256"],
    }
    missing = [name for name, value in required_identity.items() if not value]
    if missing:
        return identity, BLOCKED, (
            "Artifact identity is incomplete: " + ", ".join(sorted(missing))
        )
    if not re.fullmatch(r"[0-9a-f]{64}", identity["signing_cert_sha256"]):
        return identity, BLOCKED, "Artifact signing certificate is not a valid SHA-256 digest."
    return identity, PASS, "Exact APK bytes and canonical artifact identity are bound."


def certification_summary(report_dir: Path, analysis_mode: str) -> dict[str, Any]:
    payload = optional_json(report_dir / "certification.json")
    if not payload:
        return {
            "attempted": analysis_mode == "certification",
            "status": BLOCKED if analysis_mode == "certification" else NOT_VERIFIED,
            "certified": False,
            "failures": [],
            "blockers": (
                [{"gate": "certification_output", "observed": "MISSING"}]
                if analysis_mode == "certification"
                else []
            ),
        }
    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    status = normalized(payload.get("status")) or NOT_VERIFIED
    return {
        "attempted": True,
        "status": status,
        "certified": status == "CERTIFIED",
        "failures": failures,
        "blockers": blockers,
    }


def release_id(
    repository: str,
    resolved_sha: str,
    artifact_sha: str,
    package_id: str,
    version_code: str,
) -> str:
    raw = "\n".join(
        [repository, resolved_sha, artifact_sha, package_id, version_code]
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_release_reality(
    report_dir: Path,
    artifact_path: Path | None,
    *,
    workflow_run_id: str,
    trusted_applab_sha: str,
    runtime_outcome: str,
) -> dict[str, Any]:
    contract = optional_json(report_dir / "build-contract.json")
    result = optional_json(report_dir / "result.json")

    repository = str(contract.get("repository", "") or result.get("repository", "")).strip()
    resolved_sha = str(
        contract.get("resolved_sha", "") or result.get("resolved_sha", "")
    ).strip().lower()
    engine = str(contract.get("engine", "") or result.get("engine", "")).strip()
    ref = str(result.get("ref", "")).strip()
    analysis_mode = str(
        result.get("analysis_mode", "") or contract.get("analysis_mode", "")
    ).strip().lower()
    pipeline_status = normalized(result.get("pipeline_status"))
    runtime_result = normalized(result.get("result"))
    runtime_outcome = normalized(runtime_outcome)
    workflow_run_id = str(workflow_run_id or result.get("workflow_run_id", "")).strip()
    trusted_applab_sha = str(
        trusted_applab_sha or contract.get("trusted_applab_sha", "")
    ).strip().lower()

    quality = contract.get("quality_evidence")
    if not isinstance(quality, dict):
        quality = {}

    artifact, artifact_state, artifact_reason = artifact_identity(contract, artifact_path)

    source_valid = bool(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        and re.fullmatch(r"[0-9a-f]{40}", resolved_sha)
        and engine in {"flutter", "native_android"}
    )
    levels: list[dict[str, Any]] = []
    levels.append(
        stage(
            "IMPLEMENTED",
            PASS if source_valid else BLOCKED,
            (
                "Repository, immutable source SHA and supported engine are bound."
                if source_valid
                else "Repository/source/engine binding is incomplete."
            ),
            ["build-contract.json", "result.json"],
        )
    )

    static_key = "analyze" if engine == "flutter" else "lint"
    static_label = "Flutter static analysis" if engine == "flutter" else "Android lint"
    static_check = check_quality_stage(static_key, static_label, quality)
    levels.append(
        stage(
            "STATICALLY_CHECKED",
            static_check["state"],
            static_check["reason"],
            static_check["evidence"],
        )
    )

    tests = check_quality_stage("unit_tests", "Unit tests", quality)
    levels.append(
        stage("TESTED", tests["state"], tests["reason"], tests["evidence"])
    )

    required_quality = [static_key, "unit_tests", "build"]
    required_states = [quality_state(quality, key) for key in required_quality]
    if any(value in FAIL_STATES for value in required_states):
        ci_state = FAIL
        ci_reason = "At least one required CI/build-quality check failed."
    elif all(value == PASS for value in required_states):
        ci_state = PASS
        ci_reason = (
            "Required static/test/build checks passed in the sealed build contract. "
            "Runtime and certification outcomes are tracked separately."
        )
    else:
        ci_state = NOT_VERIFIED
        ci_reason = "Complete PASS evidence for the required CI/build-quality checks is missing."
    levels.append(
        stage(
            "CI_GREEN",
            ci_state,
            ci_reason,
            ["build-contract.json#quality_evidence"],
        )
    )

    levels.append(
        stage(
            "ARTIFACT_BUILT",
            artifact_state,
            artifact_reason,
            ["build-contract.json#apk", "app.apk"],
        )
    )

    if artifact_state != PASS:
        runtime_state = BLOCKED
        runtime_reason = (
            "Trusted runtime cannot establish release reality because the exact artifact "
            "identity is not proven."
        )
    elif runtime_result in FAIL_STATES or runtime_outcome in {"FAIL", "FAILURE"}:
        runtime_state = FAIL
        runtime_reason = "Trusted runtime verification failed for the bound APK."
    elif runtime_result == PASS and runtime_outcome == "SUCCESS":
        runtime_state = PASS
        runtime_reason = "Trusted runtime PASS is bound to the exact APK bytes."
    else:
        runtime_state = NOT_VERIFIED
        runtime_reason = "Trusted runtime PASS is not available for the bound APK."
    levels.append(
        stage(
            "TRUSTED_RUNTIME_VERIFIED",
            runtime_state,
            runtime_reason,
            ["result.json", "build-contract.json#apk"],
        )
    )

    policy = contract.get("certification_policy")
    if not isinstance(policy, dict):
        policy = {}
    requires_real_device = bool(policy.get("requires_real_device", False))
    if requires_real_device:
        physical_state = BLOCKED
        physical_reason = (
            "This release requires physical-device evidence, but v4.4 has no bound "
            "Physical Evidence Hub record yet."
        )
        physical_applicable = True
    else:
        physical_state = NOT_APPLICABLE
        physical_reason = (
            "The current certification policy does not require physical-device evidence."
        )
        physical_applicable = False
    levels.append(
        stage(
            "PHYSICAL_DEVICE_VERIFIED",
            physical_state,
            physical_reason,
            ["build-contract.json#certification_policy.requires_real_device"],
            applicable=physical_applicable,
        )
    )

    levels.append(
        stage(
            "DISTRIBUTION_VERIFIED",
            NOT_VERIFIED,
            "No trusted distribution/install-channel evidence is bound to this APK.",
            [],
        )
    )
    levels.append(
        stage(
            "STORE_READY",
            NOT_VERIFIED,
            "No trusted store-readiness evidence is bound to this APK.",
            [],
        )
    )
    levels.append(
        stage(
            "PRODUCTION_RELEASED",
            NOT_VERIFIED,
            "No trusted production-release evidence is bound to this APK.",
            [],
        )
    )

    current_level = "NONE"
    for row in levels:
        if not row["applicable"] or row["state"] == NOT_APPLICABLE:
            continue
        if row["state"] == PASS:
            current_level = row["key"]
            continue
        break

    highest_pass = "NONE"
    for row in levels:
        if row["state"] == PASS:
            highest_pass = row["key"]

    next_gate: dict[str, Any] | None = None
    for row in levels:
        if not row["applicable"] or row["state"] == NOT_APPLICABLE:
            continue
        if row["state"] != PASS:
            next_gate = {
                "key": row["key"],
                "state": row["state"],
                "reason": row["reason"],
            }
            break

    unresolved = [
        {
            "stage": row["key"],
            "state": row["state"],
            "reason": row["reason"],
        }
        for row in levels
        if row["applicable"] and row["state"] in {FAIL, BLOCKED, NOT_VERIFIED}
    ]

    certification = certification_summary(report_dir, analysis_mode)
    certification_blockers: list[dict[str, Any]] = []
    for kind in ("failures", "blockers"):
        for item in certification.get(kind, []):
            if isinstance(item, dict):
                certification_blockers.append(
                    {
                        "type": "FAILURE" if kind == "failures" else "BLOCKER",
                        **item,
                    }
                )

    identity_complete = bool(
        repository
        and resolved_sha
        and artifact.get("sha256")
        and artifact.get("package_id")
        and artifact.get("version_name")
        and artifact.get("version_code")
        and artifact.get("signing_cert_sha256")
        and workflow_run_id
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_id": release_id(
            repository,
            resolved_sha,
            str(artifact.get("sha256", "")),
            str(artifact.get("package_id", "")),
            str(artifact.get("version_code", "")),
        ),
        "source": {
            "repository": repository,
            "ref": ref,
            "resolved_sha": resolved_sha,
            "engine": engine,
        },
        "artifact": artifact,
        "workflow": {
            "workflow_run_id": workflow_run_id,
            "trusted_applab_sha": trusted_applab_sha,
            "analysis_mode": analysis_mode,
            "pipeline_status": pipeline_status or "UNKNOWN",
            "runtime_step_outcome": runtime_outcome or "UNKNOWN",
        },
        "identity_complete": identity_complete,
        "current_level": current_level,
        "highest_observed_pass": highest_pass,
        "levels": levels,
        "next_gate": next_gate,
        "unresolved_stages": unresolved,
        "certification": certification,
        "certification_blockers": certification_blockers,
        "same_artifact_semantics": {
            "artifact_sha256_is_release_identity": True,
            "same_bytes_verified": bool(artifact.get("same_bytes_verified")),
            "rebuilt_bytes_require_new_evidence": True,
            "note": (
                "A rebuild with different APK bytes is a new artifact even when source, "
                "package and version labels are unchanged."
            ),
        },
        "guardrails": {
            "no_numeric_product_score": True,
            "green_build_is_not_distribution_proof": True,
            "emulator_is_not_physical_device": True,
            "certification_is_not_store_distribution": True,
            "post_runtime_levels_require_separate_trusted_evidence": True,
        },
    }
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    artifact = payload["artifact"]
    source = payload["source"]
    workflow = payload["workflow"]
    lines = [
        "# AppLab Release Reality",
        "",
        f"- Release ID: `{payload['release_id']}`",
        f"- Source: `{source.get('repository','')}@{source.get('resolved_sha','')}`",
        f"- Package: `{artifact.get('package_id','') or 'UNKNOWN'}`",
        f"- Version: `{artifact.get('version_name','') or '?'} ({artifact.get('version_code','') or '?'})`",
        f"- APK SHA-256: `{artifact.get('sha256','') or 'UNKNOWN'}`",
        f"- Signing SHA-256: `{artifact.get('signing_cert_sha256','') or 'UNKNOWN'}`",
        f"- Workflow run: `{workflow.get('workflow_run_id','') or 'UNKNOWN'}`",
        f"- Current contiguous level: **{payload['current_level']}**",
        "",
        "## Release ladder",
        "",
        "| Stage | State | Reason |",
        "| --- | --- | --- |",
    ]
    for row in payload["levels"]:
        reason = str(row["reason"]).replace("|", "\\|")
        lines.append(f"| {row['key']} | {row['state']} | {reason} |")

    lines.extend(["", "## Next gate", ""])
    next_gate = payload.get("next_gate")
    if next_gate:
        lines.append(
            f"- **{next_gate['key']}** — {next_gate['state']}: {next_gate['reason']}"
        )
    else:
        lines.append("- No unresolved applicable stage.")

    certification = payload.get("certification") or {}
    lines.extend(
        [
            "",
            "## Certification",
            "",
            f"- Attempted: **{'YES' if certification.get('attempted') else 'NO'}**",
            f"- Status: **{certification.get('status', NOT_VERIFIED)}**",
        ]
    )
    blockers = payload.get("certification_blockers") or []
    if blockers:
        lines.append("- Exact blockers/failures:")
        for item in blockers:
            label = item.get("label") or item.get("gate") or "unknown"
            observed = item.get("observed") or item.get("reason") or "UNKNOWN"
            lines.append(f"  - {item.get('type','BLOCKER')}: {label} — {observed}")

    lines.extend(
        [
            "",
            "## Authority boundary",
            "",
            "- Artifact identity is byte-bound by APK SHA-256.",
            "- Trusted runtime PASS does not imply physical-device verification.",
            "- Certification does not imply distribution, store readiness or production release.",
            "- Rebuilt APK bytes require new evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report_dir: Path, payload: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "release-reality.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "release-reality.md").write_text(
        render_markdown(payload),
        encoding="utf-8",
    )


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        report = root / "report"
        report.mkdir()
        apk = root / "app.apk"
        apk.write_bytes(b"release-apk-v1")
        digest = sha256_file(apk)
        contract = {
            "repository": "owner/demo",
            "resolved_sha": "a" * 40,
            "engine": "flutter",
            "analysis_mode": "full",
            "package_id": "com.example.demo",
            "quality_evidence": {
                "analyze": "PASS",
                "unit_tests": "PASS",
                "build": "PASS",
                "lint": "N/A",
            },
            "certification_policy": {"requires_real_device": False},
            "apk": {
                "path": "app.apk",
                "size_bytes": apk.stat().st_size,
                "sha256": digest,
                "package_id": "com.example.demo",
                "version_name": "1.2.3",
                "version_code": "12",
                "build_variant": "release",
                "signing_cert_sha256": "b" * 64,
                "signing_subject": "CN=Release",
            },
        }
        result = {
            "repository": "owner/demo",
            "resolved_sha": "a" * 40,
            "engine": "flutter",
            "ref": "main",
            "analysis_mode": "full",
            "pipeline_status": "success",
            "workflow_run_id": "123",
            "package_id": "com.example.demo",
            "result": "PASS",
        }
        (report / "build-contract.json").write_text(json.dumps(contract), encoding="utf-8")
        (report / "result.json").write_text(json.dumps(result), encoding="utf-8")

        reality = build_release_reality(
            report,
            apk,
            workflow_run_id="123",
            trusted_applab_sha="c" * 40,
            runtime_outcome="success",
        )
        states = {row["key"]: row["state"] for row in reality["levels"]}
        assert reality["current_level"] == "TRUSTED_RUNTIME_VERIFIED"
        assert states["IMPLEMENTED"] == PASS
        assert states["STATICALLY_CHECKED"] == PASS
        assert states["TESTED"] == PASS
        assert states["CI_GREEN"] == PASS
        assert states["ARTIFACT_BUILT"] == PASS
        assert states["TRUSTED_RUNTIME_VERIFIED"] == PASS
        assert states["PHYSICAL_DEVICE_VERIFIED"] == NOT_APPLICABLE
        assert states["DISTRIBUTION_VERIFIED"] == NOT_VERIFIED
        assert reality["artifact"]["same_bytes_verified"] is True

        contract["analysis_mode"] = "certification"
        contract["certification_policy"]["requires_real_device"] = True
        result["analysis_mode"] = "certification"
        (report / "build-contract.json").write_text(json.dumps(contract), encoding="utf-8")
        (report / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (report / "certification.json").write_text(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "failures": [],
                    "blockers": [
                        {
                            "gate": "real_device",
                            "label": "Required physical-device evidence",
                            "observed": "NOT_TESTED",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        reality = build_release_reality(
            report,
            apk,
            workflow_run_id="123",
            trusted_applab_sha="c" * 40,
            runtime_outcome="success",
        )
        states = {row["key"]: row["state"] for row in reality["levels"]}
        assert states["PHYSICAL_DEVICE_VERIFIED"] == BLOCKED
        assert reality["certification"]["status"] == "BLOCKED"
        assert reality["certification_blockers"][0]["gate"] == "real_device"
        assert states["CI_GREEN"] == PASS

        apk.write_bytes(b"rebuilt-different-bytes")
        reality = build_release_reality(
            report,
            apk,
            workflow_run_id="123",
            trusted_applab_sha="c" * 40,
            runtime_outcome="success",
        )
        states = {row["key"]: row["state"] for row in reality["levels"]}
        assert states["ARTIFACT_BUILT"] == FAIL
        assert states["TRUSTED_RUNTIME_VERIFIED"] == BLOCKED
        assert reality["artifact"]["same_bytes_verified"] is False

        write_outputs(report, reality)
        assert (report / "release-reality.json").is_file()
        assert "Release ladder" in (report / "release-reality.md").read_text(encoding="utf-8")

    print("AppLab v4.4 Release Reality self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir")
    parser.add_argument("--artifact")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--trusted-applab-sha", default="")
    parser.add_argument("--runtime-outcome", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.report_dir:
        raise SystemExit("--report-dir is required")

    report_dir = Path(args.report_dir)
    artifact = Path(args.artifact) if args.artifact else None
    payload = build_release_reality(
        report_dir,
        artifact,
        workflow_run_id=args.workflow_run_id,
        trusted_applab_sha=args.trusted_applab_sha,
        runtime_outcome=args.runtime_outcome,
    )
    write_outputs(report_dir, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
