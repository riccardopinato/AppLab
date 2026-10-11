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

APPLAB_VERSION = "4.9.0"
SCHEMA_VERSION = 1
RECORD_TYPE = "AUTONOMOUS_RELEASE_ASSURANCE"
AUTHORITY = "APPLAB_RELEASE_ASSURANCE"

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_VERIFIED = "NOT_VERIFIED"
NOT_APPLICABLE = "N/A"
ALLOWED = {PASS, FAIL, BLOCKED, NOT_VERIFIED, NOT_APPLICABLE}

SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

RR = "release-reality.json"
GRAPH = "evidence-graph.json"
PLAN = "analysis-plan.json"
CERT = "certification.json"
CROSS = "cross-app-verification.json"
DIST = "distribution-evidence.json"


def read_json(path: Path, required: bool = False) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise ValueError(f"required evidence is missing: {path.name}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def norm_state(value: object, default: str = NOT_VERIFIED) -> str:
    text = clean(value).upper() or default
    aliases = {
        "SUCCESS": PASS,
        "CERTIFIED": PASS,
        "FAILED": FAIL,
        "FAILURE": FAIL,
        "ERROR": FAIL,
        "NOT_CERTIFIED": FAIL,
    }
    text = aliases.get(text, text)
    return text if text in ALLOWED else default


def rr_stage(reality: dict[str, Any], key: str) -> dict[str, Any] | None:
    rows = reality.get("levels") if isinstance(reality.get("levels"), list) else []
    for row in rows:
        if isinstance(row, dict) and clean(row.get("key")) == key:
            return row
    return None


def stage(key: str, title: str, required: bool, state: str, reason: str, evidence: list[str]) -> dict[str, Any]:
    if state not in ALLOWED:
        raise ValueError(f"unsupported assurance state: {state}")
    return {
        "key": key,
        "title": title,
        "required": required,
        "state": state,
        "reason": reason,
        "evidence": evidence,
    }


def identity(reality: dict[str, Any]) -> dict[str, str]:
    source = reality.get("source") if isinstance(reality.get("source"), dict) else {}
    artifact = reality.get("artifact") if isinstance(reality.get("artifact"), dict) else {}
    out = {
        "repository": clean(source.get("repository")),
        "resolved_sha": clean(source.get("resolved_sha")).lower(),
        "artifact_sha256": clean(artifact.get("sha256")).lower(),
        "package_id": clean(artifact.get("package_id")),
        "version_name": clean(artifact.get("version_name")),
        "version_code": clean(artifact.get("version_code")),
    }
    if not REPO_RE.fullmatch(out["repository"]):
        raise ValueError("release reality repository binding is invalid")
    if not SHA40_RE.fullmatch(out["resolved_sha"]):
        raise ValueError("release reality resolved_sha binding is invalid")
    if not SHA256_RE.fullmatch(out["artifact_sha256"]):
        raise ValueError("release reality artifact sha256 binding is invalid")
    if not all(out[k] for k in ("package_id", "version_name", "version_code")):
        raise ValueError("release reality artifact identity is incomplete")
    return out


def graph_state(graph: dict[str, Any], ident: dict[str, str]) -> tuple[str, str]:
    if not graph:
        return BLOCKED, "Evidence Graph is missing."
    current = graph.get("identity") if isinstance(graph.get("identity"), dict) else {}
    repo = clean(current.get("repository"))
    sha = clean(current.get("resolved_sha")).lower()
    pkg = clean(current.get("package_id"))
    if repo and repo != ident["repository"]:
        return FAIL, "Evidence Graph repository mismatch."
    if sha and sha != ident["resolved_sha"]:
        return FAIL, "Evidence Graph source SHA mismatch."
    if pkg and pkg != ident["package_id"]:
        return FAIL, "Evidence Graph package id mismatch."
    if not repo or not sha:
        return BLOCKED, "Evidence Graph identity is incomplete."
    return PASS, "Evidence Graph is bound to the same release revision."


def exact_identity(record: dict[str, Any], ident: dict[str, str]) -> bool:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    artifact = record.get("artifact") if isinstance(record.get("artifact"), dict) else {}
    observed = {
        "repository": clean(source.get("repository")),
        "resolved_sha": clean(source.get("resolved_sha")).lower(),
        "artifact_sha256": clean(artifact.get("sha256")).lower(),
        "package_id": clean(artifact.get("package_id")),
        "version_name": clean(artifact.get("version_name")),
        "version_code": clean(artifact.get("version_code")),
    }
    return all(observed.get(key) == expected for key, expected in ident.items())


def distribution_state(record: dict[str, Any], ident: dict[str, str]) -> tuple[bool, str, str]:
    if not record:
        return False, NOT_VERIFIED, "No trusted distribution evidence is attached."
    if not exact_identity(record, ident):
        return True, FAIL, "Distribution evidence identity does not match the release."
    verification = record.get("verification") if isinstance(record.get("verification"), dict) else {}
    if verification.get("trusted") is not True or verification.get("exact_artifact_match") is not True:
        return True, BLOCKED, "Distribution evidence is not trusted and exact-artifact-bound."
    result = norm_state(record.get("result"))
    if result == PASS:
        return True, PASS, "Trusted distribution evidence proves delivery/install for the exact artifact."
    if result == FAIL:
        return True, FAIL, "Trusted distribution evidence reports a failed delivery/install scenario."
    return True, BLOCKED, "Distribution evidence is present but does not prove PASS."


def cross_state(record: dict[str, Any], ident: dict[str, str]) -> tuple[bool, str, str]:
    if not record:
        return False, NOT_VERIFIED, "No cross-app pair evidence is attached."
    pair = record.get("pair_identity") if isinstance(record.get("pair_identity"), dict) else {}
    candidates = [
        pair.get("producer") if isinstance(pair.get("producer"), dict) else {},
        pair.get("consumer") if isinstance(pair.get("consumer"), dict) else {},
    ]
    found = any(
        clean(row.get("repository")) == ident["repository"]
        and clean(row.get("resolved_sha")).lower() == ident["resolved_sha"]
        and clean(row.get("artifact_sha256")).lower() == ident["artifact_sha256"]
        for row in candidates
    )
    if not found:
        return True, FAIL, "Cross-app evidence does not contain the bound artifact identity."
    round_trip = record.get("cross_app_round_trip") if isinstance(record.get("cross_app_round_trip"), dict) else {}
    result = norm_state(round_trip.get("state"))
    if result == PASS:
        return True, PASS, "Cross-app round-trip PASS is bound to this release artifact."
    if result == FAIL:
        return True, FAIL, "Cross-app round-trip failed."
    return True, BLOCKED, "Cross-app evidence is present but is not PASS."


def digest(ident: dict[str, str], rows: list[dict[str, Any]]) -> str:
    payload = {
        "identity": ident,
        "stages": [
            {"key": row["key"], "required": row["required"], "state": row["state"]}
            for row in rows
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_report(report_dir: Path) -> dict[str, Any]:
    reality = read_json(report_dir / RR, True)
    graph = read_json(report_dir / GRAPH)
    plan = read_json(report_dir / PLAN)
    certification = read_json(report_dir / CERT)
    cross = read_json(report_dir / CROSS)
    distribution = read_json(report_dir / DIST)

    ident = identity(reality)
    rows: list[dict[str, Any]] = []

    same_bytes = bool((reality.get("same_artifact_semantics") or {}).get("same_bytes_verified"))
    identity_complete = reality.get("identity_complete") is True
    source_state = PASS if same_bytes and identity_complete else BLOCKED
    rows.append(stage(
        "SOURCE_BUILD_BOUND",
        "Source + build identity",
        True,
        source_state,
        "Immutable source and exact APK bytes are bound." if source_state == PASS else "Release identity or exact APK-byte binding is incomplete.",
        [RR],
    ))

    build_states = []
    for key in ("STATICALLY_CHECKED", "TESTED", "CI_GREEN", "ARTIFACT_BUILT"):
        current = rr_stage(reality, key)
        build_states.append(norm_state(current.get("state")) if current else NOT_VERIFIED)
    build_state = FAIL if FAIL in build_states else PASS if all(x == PASS for x in build_states) else BLOCKED
    rows.append(stage(
        "STATIC_BUILD_ASSURANCE",
        "Static, test, CI and artifact",
        True,
        build_state,
        "Static/test/build evidence is complete." if build_state == PASS else "Static/test/build evidence is incomplete or failed.",
        [RR],
    ))

    runtime = rr_stage(reality, "TRUSTED_RUNTIME_VERIFIED")
    runtime_state = norm_state(runtime.get("state")) if runtime else NOT_VERIFIED
    rows.append(stage(
        "TRUSTED_RUNTIME",
        "Trusted runtime",
        True,
        runtime_state,
        clean(runtime.get("reason")) if runtime else "Trusted runtime evidence is missing.",
        [RR],
    ))

    gs, gr = graph_state(graph, ident)
    rows.append(stage("EVIDENCE_GRAPH", "Evidence Graph", True, gs, gr, [GRAPH] if graph else []))

    lane = clean(plan.get("lane")) or clean(plan.get("mode")).upper()
    confidence = clean(plan.get("confidence")).upper()
    plan_state = PASS if plan and lane else BLOCKED
    plan_reason = f"Risk-based plan recorded: {lane or 'UNKNOWN'}"
    if confidence:
        plan_reason += f" / confidence {confidence}"
    if plan.get("fallback_full") is True:
        plan_reason += " / conservative FULL fallback"
    rows.append(stage(
        "RISK_BASED_VALIDATION",
        "Risk-based validation",
        True,
        plan_state,
        plan_reason if plan else "Adaptive validation plan is missing.",
        [PLAN] if plan else [],
    ))

    physical = rr_stage(reality, "PHYSICAL_DEVICE_VERIFIED")
    physical_required = bool((reality.get("physical_evidence") or {}).get("required"))
    if physical_required:
        ps = norm_state(physical.get("state")) if physical else BLOCKED
        pr = clean(physical.get("reason")) if physical else "Required physical evidence stage is missing."
    else:
        ps = NOT_APPLICABLE
        pr = "Physical evidence is not required by the release policy."
    rows.append(stage("PHYSICAL_EVIDENCE", "Physical evidence", physical_required, ps, pr, [RR]))

    dist_present, ds, dr = distribution_state(distribution, ident)
    rr_dist = rr_stage(reality, "DISTRIBUTION_VERIFIED")
    dist_required = bool(rr_dist and rr_dist.get("applicable", True)) or dist_present
    if not dist_present and rr_dist and norm_state(rr_dist.get("state")) == PASS:
        ds, dr = BLOCKED, "Release Reality claims distribution PASS without attached trusted distribution evidence."
    rows.append(stage(
        "DISTRIBUTION_EVIDENCE",
        "Distribution evidence",
        dist_required,
        ds if dist_required else NOT_APPLICABLE,
        dr,
        [DIST] if distribution else [],
    ))

    cross_present, cs, cr = cross_state(cross, ident)
    rows.append(stage(
        "CROSS_APP",
        "Cross-app verification",
        cross_present,
        cs if cross_present else NOT_APPLICABLE,
        cr,
        [CROSS] if cross else [],
    ))

    cert_payload = certification or (reality.get("certification") if isinstance(reality.get("certification"), dict) else {})
    cert_status = clean(cert_payload.get("status")).upper()
    cert_state = PASS if cert_status == "CERTIFIED" else FAIL if cert_status in {"FAIL", "FAILED", "FAILURE", "NOT_CERTIFIED"} else BLOCKED
    rows.append(stage(
        "CERTIFICATION",
        "Canonical certification",
        True,
        cert_state,
        "Canonical certification authority reports CERTIFIED." if cert_state == PASS else f"Canonical certification authority is {cert_status or 'NOT_VERIFIED'}.",
        [CERT, RR] if certification else [RR],
    ))

    required = [row for row in rows if row["required"]]
    if any(row["state"] == FAIL for row in required):
        overall = FAIL
    elif all(row["state"] == PASS for row in required):
        overall = PASS
    elif any(row["state"] in {BLOCKED, NOT_VERIFIED} for row in required):
        overall = BLOCKED
    else:
        overall = NOT_VERIFIED

    failures = [row for row in required if row["state"] == FAIL]
    blockers = [row for row in required if row["state"] in {BLOCKED, NOT_VERIFIED}]
    next_required = next((row for row in required if row["state"] != PASS), None)

    return {
        "schema_version": SCHEMA_VERSION,
        "applab_version": APPLAB_VERSION,
        "record_type": RECORD_TYPE,
        "authority": AUTHORITY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "release_id": clean(reality.get("release_id")),
        "assurance_digest": digest(ident, rows),
        "identity": ident,
        "state": overall,
        "stages": rows,
        "failures": failures,
        "blockers": blockers,
        "next_required_stage": next_required,
        "certification": {
            "status": cert_status or NOT_VERIFIED,
            "authority": "PRODUCTION_CERTIFICATION_GATE",
            "release_assurance_can_certify": False,
        },
        "guardrails": {
            "fail_closed": True,
            "no_numeric_score": True,
            "same_artifact_required": True,
            "missing_required_evidence_never_passes": True,
            "release_assurance_is_not_certification_authority": True,
            "emulator_is_not_physical_device": True,
            "certification_is_not_distribution_proof": True,
            "cross_app_pass_is_independent_from_single_app_pass": True,
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    ident = payload["identity"]
    lines = [
        "# AppLab Autonomous Release Assurance",
        "",
        f"- State: **{payload['state']}**",
        f"- Release: {payload.get('release_id') or 'UNKNOWN'}",
        f"- Source: {ident['repository']}@{ident['resolved_sha']}",
        f"- Package: {ident['package_id']}",
        f"- APK SHA-256: {ident['artifact_sha256']}",
        f"- Assurance digest: {payload['assurance_digest']}",
        "",
        "## Assurance chain",
        "",
        "| Stage | Required | State | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["stages"]:
        lines.append(f"| {row['key']} | {'YES' if row['required'] else 'NO'} | {row['state']} | {row['reason'].replace('|', '/') } |")
    lines.extend([
        "",
        "## Authority boundary",
        "",
        "- This record never upgrades certification.",
        "- Missing required evidence never becomes PASS.",
        "- Physical, distribution and cross-app evidence remain separate authorities.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(report_dir: Path, payload: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "release-assurance.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "release-assurance.md").write_text(
        render_markdown(payload),
        encoding="utf-8",
    )


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        reality = {
            "release_id": "r1",
            "identity_complete": True,
            "source": {"repository": "owner/demo", "resolved_sha": "a" * 40},
            "artifact": {
                "sha256": "b" * 64,
                "package_id": "com.example.demo",
                "version_name": "1.0.0",
                "version_code": "1",
            },
            "same_artifact_semantics": {"same_bytes_verified": True},
            "levels": [
                {"key": "STATICALLY_CHECKED", "state": PASS},
                {"key": "TESTED", "state": PASS},
                {"key": "CI_GREEN", "state": PASS},
                {"key": "ARTIFACT_BUILT", "state": PASS},
                {"key": "TRUSTED_RUNTIME_VERIFIED", "state": PASS, "reason": "trusted runtime PASS"},
                {"key": "PHYSICAL_DEVICE_VERIFIED", "state": NOT_APPLICABLE, "applicable": False},
                {"key": "DISTRIBUTION_VERIFIED", "state": NOT_VERIFIED, "applicable": True},
            ],
            "physical_evidence": {"required": False},
            "certification": {"status": "CERTIFIED"},
        }
        (root / RR).write_text(json.dumps(reality), encoding="utf-8")
        (root / GRAPH).write_text(json.dumps({
            "identity": {
                "repository": "owner/demo",
                "resolved_sha": "a" * 40,
                "package_id": "com.example.demo",
            }
        }), encoding="utf-8")
        (root / PLAN).write_text(json.dumps({"lane": "CERTIFICATION", "confidence": "HIGH"}), encoding="utf-8")
        (root / CERT).write_text(json.dumps({"status": "CERTIFIED"}), encoding="utf-8")

        first = build_report(root)
        assert first["state"] == BLOCKED
        assert first["next_required_stage"]["key"] == "DISTRIBUTION_EVIDENCE"

        distribution = {
            "source": {"repository": "owner/demo", "resolved_sha": "a" * 40},
            "artifact": {
                "sha256": "b" * 64,
                "package_id": "com.example.demo",
                "version_name": "1.0.0",
                "version_code": "1",
            },
            "verification": {"trusted": True, "exact_artifact_match": True},
            "result": PASS,
        }
        (root / DIST).write_text(json.dumps(distribution), encoding="utf-8")
        second = build_report(root)
        assert second["state"] == PASS
        assert second["certification"]["release_assurance_can_certify"] is False

        bad = json.loads(json.dumps(distribution))
        bad["artifact"]["sha256"] = "c" * 64
        (root / DIST).write_text(json.dumps(bad), encoding="utf-8")
        assert build_report(root)["state"] == FAIL

        (root / DIST).write_text(json.dumps(distribution), encoding="utf-8")
        write_outputs(root, second)
        assert (root / "release-assurance.json").is_file()
        assert "Authority boundary" in (root / "release-assurance.md").read_text(encoding="utf-8")

    print("AppLab v4.9 Autonomous Release Assurance self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.report_dir:
        parser.error("--report-dir is required unless --self-test is used")

    report_dir = Path(args.report_dir)
    payload = build_report(report_dir)
    write_outputs(Path(args.output_dir) if args.output_dir else report_dir, payload)
    print(json.dumps({
        "applab_version": APPLAB_VERSION,
        "state": payload["state"],
        "assurance_digest": payload["assurance_digest"],
    }, sort_keys=True))
    return 0 if payload["state"] == PASS or not args.require_pass else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab Autonomous Release Assurance failed: {exc}") from exc
