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
PLAN_LANES = {"NO_RUNTIME_CHANGE", "STATIC_ONLY", "FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}
PLAN_MODES = {"fast", "full", "certification"}
PLAN_LABS = {
    "system",
    "performance",
    "network",
    "persistence",
    "configuration",
    "resource_pressure",
    "background",
    "storage",
    "upgrade",
}
CANONICAL_STAGE_KEYS = (
    "SOURCE_BUILD_BOUND",
    "STATIC_BUILD_ASSURANCE",
    "TRUSTED_RUNTIME",
    "EVIDENCE_GRAPH",
    "RISK_BASED_VALIDATION",
    "PHYSICAL_EVIDENCE",
    "DISTRIBUTION_EVIDENCE",
    "CROSS_APP",
    "CERTIFICATION",
)
ALWAYS_REQUIRED_STAGE_KEYS = {
    "SOURCE_BUILD_BOUND",
    "STATIC_BUILD_ASSURANCE",
    "TRUSTED_RUNTIME",
    "EVIDENCE_GRAPH",
    "RISK_BASED_VALIDATION",
    "CERTIFICATION",
}
CONDITIONAL_STAGE_KEYS = {
    "PHYSICAL_EVIDENCE",
    "DISTRIBUTION_EVIDENCE",
    "CROSS_APP",
}

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
    if required and state == NOT_APPLICABLE:
        state = BLOCKED
        reason = "Required assurance stage cannot be N/A. " + reason
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
    if graph.get("schema_version") != 2 or clean(graph.get("graph_version")) != "2.0":
        return FAIL, "Evidence Graph schema/version is invalid."
    current = graph.get("identity") if isinstance(graph.get("identity"), dict) else {}
    repo = clean(current.get("repository"))
    sha = clean(current.get("resolved_sha")).lower()
    pkg = clean(current.get("package_id"))
    if repo != ident["repository"]:
        return FAIL, "Evidence Graph repository mismatch."
    if sha != ident["resolved_sha"]:
        return FAIL, "Evidence Graph source SHA mismatch."
    if pkg != ident["package_id"]:
        return FAIL, "Evidence Graph package id mismatch."

    roots = graph.get("root_nodes") if isinstance(graph.get("root_nodes"), dict) else {}
    artifact_id = clean(roots.get("build_artifact"))
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    if not artifact_id or not nodes:
        return FAIL, "Evidence Graph canonical build-artifact root is missing."
    matches = [
        row
        for row in nodes
        if isinstance(row, dict)
        and clean(row.get("id")) == artifact_id
        and clean(row.get("type")) == "BuildArtifact"
    ]
    if len(matches) != 1:
        return FAIL, "Evidence Graph build-artifact root does not resolve uniquely."
    attrs = matches[0].get("attributes")
    if not isinstance(attrs, dict):
        return FAIL, "Evidence Graph build-artifact attributes are missing."
    observed = {
        "artifact_sha256": clean(attrs.get("apk_sha256")).lower(),
        "package_id": clean(attrs.get("package_id")),
        "version_name": clean(attrs.get("version_name")),
        "version_code": clean(attrs.get("version_code")),
    }
    for key, expected in (
        ("artifact_sha256", ident["artifact_sha256"]),
        ("package_id", ident["package_id"]),
        ("version_name", ident["version_name"]),
        ("version_code", ident["version_code"]),
    ):
        if observed[key] != expected:
            return FAIL, f"Evidence Graph build artifact {key} mismatch."
    return PASS, "Evidence Graph is bound to the exact release artifact."


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


def certification_identity_matches(record: dict[str, Any], ident: dict[str, str]) -> bool:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    apk = record.get("apk") if isinstance(record.get("apk"), dict) else {}
    observed = {
        "repository": clean(source.get("repository")),
        "resolved_sha": clean(source.get("resolved_sha")).lower(),
        "artifact_sha256": clean(apk.get("sha256") or record.get("apk_sha256")).lower(),
        "package_id": clean(apk.get("package_id")),
        "version_name": clean(apk.get("version_name")),
        "version_code": clean(apk.get("version_code")),
    }
    return all(observed.get(key) == expected for key, expected in ident.items())


def certification_contract_state(
    record: dict[str, Any],
    ident: dict[str, str],
) -> tuple[str, str, str]:
    if not certification_identity_matches(record, ident):
        status = clean(record.get("status")).upper() or NOT_VERIFIED
        return FAIL, status, "Certification evidence identity does not match the release."

    status = clean(record.get("status")).upper() or NOT_VERIFIED
    certified = record.get("certified")
    failures = record.get("failures")
    blockers = record.get("blockers")
    if (
        not isinstance(certified, bool)
        or not isinstance(failures, list)
        or not isinstance(blockers, list)
        or not all(isinstance(item, dict) for item in failures + blockers)
    ):
        return FAIL, status, "Certification evidence contract is structurally inconsistent."
    if status == "CERTIFIED":
        if certified is not True or failures or blockers:
            return FAIL, status, "CERTIFIED conflicts with certified/failures/blockers fields."
        return PASS, status, "Canonical certification authority reports CERTIFIED."
    if status == "NOT_CERTIFIED":
        if certified is not False:
            return FAIL, status, "NOT_CERTIFIED conflicts with certified=true."
        return FAIL, status, "Canonical certification authority reports NOT_CERTIFIED."
    if status == BLOCKED:
        if certified is not False:
            return FAIL, status, "BLOCKED certification conflicts with certified=true."
        return BLOCKED, status, "Canonical certification authority is BLOCKED."
    return FAIL, status, f"Certification evidence uses invalid status {status}."


def pair_identity_matches(row: dict[str, Any], ident: dict[str, str]) -> bool:
    return (
        clean(row.get("repository")) == ident["repository"]
        and clean(row.get("resolved_sha")).lower() == ident["resolved_sha"]
        and clean(row.get("artifact_sha256")).lower() == ident["artifact_sha256"]
        and clean(row.get("package_id")) == ident["package_id"]
        and clean(row.get("version_name")) == ident["version_name"]
        and clean(row.get("version_code")) == ident["version_code"]
    )


def distribution_state(record: dict[str, Any], ident: dict[str, str]) -> tuple[bool, str, str]:
    if not record:
        return False, NOT_VERIFIED, "No trusted distribution evidence is attached."
    if not exact_identity(record, ident):
        return True, FAIL, "Distribution evidence identity does not match the release."
    verification = record.get("verification") if isinstance(record.get("verification"), dict) else {}
    if verification.get("trusted") is not True or verification.get("exact_artifact_match") is not True:
        return True, BLOCKED, "Distribution evidence is not trusted and exact-artifact-bound."
    result = clean(record.get("result")).upper()
    if result == PASS:
        return True, PASS, "Trusted distribution evidence proves delivery/install for the exact artifact."
    if result == FAIL:
        return True, FAIL, "Trusted distribution evidence reports a failed delivery/install scenario."
    if result in {BLOCKED, NOT_VERIFIED}:
        return True, BLOCKED, "Distribution evidence is present but does not prove PASS."
    return True, FAIL, f"Distribution evidence uses invalid result state {result or 'MISSING'}."


def cross_state(record: dict[str, Any], ident: dict[str, str]) -> tuple[bool, str, str]:
    if not record:
        return False, NOT_VERIFIED, "No cross-app pair evidence is attached."
    pair = record.get("pair_identity") if isinstance(record.get("pair_identity"), dict) else {}
    candidates = [
        pair.get("producer") if isinstance(pair.get("producer"), dict) else {},
        pair.get("consumer") if isinstance(pair.get("consumer"), dict) else {},
    ]
    found = any(pair_identity_matches(row, ident) for row in candidates)
    if not found:
        return True, FAIL, "Cross-app evidence does not contain the bound artifact identity."
    round_trip = record.get("cross_app_round_trip") if isinstance(record.get("cross_app_round_trip"), dict) else {}
    result = clean(round_trip.get("state")).upper()
    if result == PASS:
        return True, PASS, "Cross-app round-trip PASS is bound to this release artifact."
    if result == FAIL:
        return True, FAIL, "Cross-app round-trip failed."
    if result in {BLOCKED, NOT_VERIFIED}:
        return True, BLOCKED, "Cross-app evidence is present but is not PASS."
    return True, FAIL, f"Cross-app evidence uses invalid round-trip state {result or 'MISSING'}."


def risk_plan_state(plan: dict[str, Any], ident: dict[str, str]) -> tuple[str, str]:
    if not plan:
        return BLOCKED, "Adaptive validation plan is missing."
    schema = plan.get("schema_version")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema not in {1, 2}:
        return FAIL, "Adaptive validation plan schema is invalid."
    mode = clean(plan.get("mode")).lower()
    if mode not in PLAN_MODES:
        return FAIL, f"Adaptive validation plan mode is invalid: {mode or 'MISSING'}."
    lane = clean(plan.get("lane")).upper()
    if lane not in PLAN_LANES:
        return FAIL, f"Adaptive validation plan lane is invalid: {lane or 'MISSING'}."
    repository = clean(plan.get("repository"))
    head_sha = clean(plan.get("head_sha")).lower()
    if repository != ident["repository"]:
        return FAIL, "Adaptive validation plan repository does not match the release."
    if head_sha != ident["resolved_sha"]:
        return FAIL, "Adaptive validation plan head SHA does not match the release."
    selected = plan.get("selected_labs")
    if (
        not isinstance(selected, dict)
        or set(selected) != PLAN_LABS
        or not all(type(selected[key]) is bool for key in PLAN_LABS)
    ):
        return FAIL, "Adaptive validation plan selected_labs schema is invalid."
    if schema == 2:
        risk_score = plan.get("risk_score")
        confidence = plan.get("confidence")
        if (
            not isinstance(risk_score, int)
            or isinstance(risk_score, bool)
            or not 0 <= risk_score <= 100
        ):
            return FAIL, "Adaptive validation plan risk_score is invalid."
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0.0 <= float(confidence) <= 1.0
        ):
            return FAIL, "Adaptive validation plan confidence is invalid."
    return PASS, f"Risk-based plan is bound to this release: {lane} / {mode}."


def overall_state(rows: list[dict[str, Any]]) -> str:
    required = [row for row in rows if isinstance(row, dict) and row.get("required") is True]
    if not required:
        return BLOCKED
    states = [clean(row.get("state")).upper() for row in required]
    if any(state == FAIL for state in states):
        return FAIL
    if all(state == PASS for state in states):
        return PASS
    if any(state in {BLOCKED, NOT_VERIFIED, NOT_APPLICABLE} for state in states):
        return BLOCKED
    return BLOCKED


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

    same_bytes = (reality.get("same_artifact_semantics") or {}).get("same_bytes_verified") is True
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

    plan_state, plan_reason = risk_plan_state(plan, ident)
    if plan and plan.get("fallback_full") is True:
        plan_reason += " Conservative FULL fallback is active."
    rows.append(stage(
        "RISK_BASED_VALIDATION",
        "Risk-based validation",
        True,
        plan_state,
        plan_reason,
        [PLAN] if plan else [],
    ))

    physical = rr_stage(reality, "PHYSICAL_DEVICE_VERIFIED")
    physical_summary = reality.get("physical_evidence") if isinstance(reality.get("physical_evidence"), dict) else {}
    physical_required = physical_summary.get("required") is True
    physical_present = physical_summary.get("present") is True
    physical_applicable = bool(physical and physical.get("applicable", True))
    physical_observed = physical_present or physical_applicable or physical_required
    if physical_observed:
        ps = norm_state(physical.get("state")) if physical else BLOCKED
        pr = clean(physical.get("reason")) if physical else "Physical evidence stage is missing."
    else:
        ps = NOT_APPLICABLE
        pr = "Physical evidence is not required and no optional trusted physical result is attached."
    rows.append(stage("PHYSICAL_EVIDENCE", "Physical evidence", physical_observed, ps, pr, [RR]))

    dist_present, ds, dr = distribution_state(distribution, ident)
    rr_dist = rr_stage(reality, "DISTRIBUTION_VERIFIED")
    dist_required = bool(rr_dist and rr_dist.get("applicable", True)) or dist_present
    rr_dist_state = norm_state(rr_dist.get("state")) if rr_dist else NOT_VERIFIED
    if rr_dist_state == FAIL:
        ds, dr = FAIL, clean(rr_dist.get("reason")) or "Release Reality records a distribution failure."
    elif not dist_present and rr_dist_state == PASS:
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

    embedded_cert = reality.get("certification") if isinstance(reality.get("certification"), dict) else {}
    embedded_status = clean(embedded_cert.get("status")).upper()
    if not certification:
        cert_status = embedded_status or NOT_VERIFIED
        cert_state = BLOCKED
        cert_reason = (
            "Canonical certification.json is missing; embedded Release Reality certification "
            f"summary ({cert_status}) is context only and cannot satisfy certification."
        )
    else:
        cert_state, cert_status, cert_reason = certification_contract_state(
            certification, ident
        )
    rows.append(stage(
        "CERTIFICATION",
        "Canonical certification",
        True,
        cert_state,
        cert_reason,
        [CERT, RR] if certification else [RR],
    ))

    if tuple(row["key"] for row in rows) != CANONICAL_STAGE_KEYS:
        raise ValueError("release assurance canonical stage order drift")
    required = [row for row in rows if row["required"]]
    overall = overall_state(rows)

    failures = [row for row in required if row["state"] == FAIL]
    blockers = [row for row in required if row["state"] in {BLOCKED, NOT_VERIFIED, NOT_APPLICABLE}]
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
        graph = {
            "schema_version": 2,
            "graph_version": "2.0",
            "identity": {
                "repository": "owner/demo",
                "resolved_sha": "a" * 40,
                "package_id": "com.example.demo",
            },
            "root_nodes": {"build_artifact": "artifact:demo"},
            "nodes": [
                {
                    "id": "artifact:demo",
                    "type": "BuildArtifact",
                    "attributes": {
                        "apk_sha256": "b" * 64,
                        "package_id": "com.example.demo",
                        "version_name": "1.0.0",
                        "version_code": "1",
                    },
                }
            ],
        }
        (root / GRAPH).write_text(json.dumps(graph), encoding="utf-8")
        plan = {
            "schema_version": 2,
            "mode": "certification",
            "lane": "CERTIFICATION",
            "repository": "owner/demo",
            "head_sha": "a" * 40,
            "selected_labs": {key: True for key in sorted(PLAN_LABS)},
            "risk_score": 50,
            "confidence": 1.0,
        }
        (root / PLAN).write_text(json.dumps(plan), encoding="utf-8")
        certification = {
            "status": "CERTIFIED",
            "certified": True,
            "failures": [],
            "blockers": [],
            "source": {"repository": "owner/demo", "resolved_sha": "a" * 40},
            "apk": {
                "sha256": "b" * 64,
                "package_id": "com.example.demo",
                "version_name": "1.0.0",
                "version_code": "1",
            },
            "apk_sha256": "b" * 64,
        }
        (root / CERT).write_text(json.dumps(certification), encoding="utf-8")

        first = build_report(root)
        assert first["state"] == BLOCKED
        assert first["next_required_stage"]["key"] == "DISTRIBUTION_EVIDENCE"

        non_boolean_bytes = json.loads(json.dumps(reality))
        non_boolean_bytes["same_artifact_semantics"]["same_bytes_verified"] = "false"
        (root / RR).write_text(json.dumps(non_boolean_bytes), encoding="utf-8")
        assert build_report(root)["state"] == BLOCKED
        (root / RR).write_text(json.dumps(reality), encoding="utf-8")

        bad_risk = json.loads(json.dumps(plan))
        bad_risk["risk_score"] = 101
        (root / PLAN).write_text(json.dumps(bad_risk), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        bad_confidence = json.loads(json.dumps(plan))
        bad_confidence["confidence"] = "high"
        (root / PLAN).write_text(json.dumps(bad_confidence), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / PLAN).write_text(json.dumps(plan), encoding="utf-8")

        stale_graph = json.loads(json.dumps(graph))
        stale_graph["nodes"][0]["attributes"]["apk_sha256"] = "c" * 64
        (root / GRAPH).write_text(json.dumps(stale_graph), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / GRAPH).write_text(json.dumps(graph), encoding="utf-8")

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
        stale_cert = json.loads(json.dumps(certification))
        stale_cert["apk"]["sha256"] = "d" * 64
        stale_cert["apk_sha256"] = "d" * 64
        (root / CERT).write_text(json.dumps(stale_cert), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / CERT).write_text(json.dumps(certification), encoding="utf-8")

        contradictory_cert = json.loads(json.dumps(certification))
        contradictory_cert["certified"] = False
        contradictory_cert["failures"] = [{"gate": "runtime", "observed": "FAIL"}]
        (root / CERT).write_text(json.dumps(contradictory_cert), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / CERT).write_text(json.dumps(certification), encoding="utf-8")
        bad_pair = {
            "pair_identity": {
                "producer": {
                    "repository": "owner/demo",
                    "resolved_sha": "a" * 40,
                    "artifact_sha256": "b" * 64,
                    "package_id": "com.example.wrong",
                    "version_name": "1.0.0",
                    "version_code": "1",
                },
                "consumer": {
                    "repository": "owner/other",
                    "resolved_sha": "e" * 40,
                    "artifact_sha256": "f" * 64,
                    "package_id": "com.example.other",
                    "version_name": "1.0.0",
                    "version_code": "1",
                },
            },
            "cross_app_round_trip": {"state": PASS},
        }
        (root / CROSS).write_text(json.dumps(bad_pair), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / CROSS).unlink()

        invalid_distribution = json.loads(json.dumps(distribution))
        invalid_distribution["result"] = "CERTIFIED"
        (root / DIST).write_text(json.dumps(invalid_distribution), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / DIST).write_text(json.dumps(distribution), encoding="utf-8")

        bad_selected = json.loads(json.dumps(plan))
        bad_selected["selected_labs"] = {"bogus": True}
        (root / PLAN).write_text(json.dumps(bad_selected), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / PLAN).write_text(json.dumps(plan), encoding="utf-8")

        invalid_cross = {
            "pair_identity": {
                "producer": {
                    "repository": "owner/demo",
                    "resolved_sha": "a" * 40,
                    "artifact_sha256": "b" * 64,
                    "package_id": "com.example.demo",
                    "version_name": "1.0.0",
                    "version_code": "1",
                },
                "consumer": {
                    "repository": "owner/other",
                    "resolved_sha": "e" * 40,
                    "artifact_sha256": "f" * 64,
                    "package_id": "com.example.other",
                    "version_name": "1.0.0",
                    "version_code": "1",
                },
            },
            "cross_app_round_trip": {"state": "CERTIFIED"},
        }
        (root / CROSS).write_text(json.dumps(invalid_cross), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / CROSS).unlink()

        rr_distribution_fail = json.loads(json.dumps(reality))
        for row in rr_distribution_fail["levels"]:
            if row.get("key") == "DISTRIBUTION_VERIFIED":
                row.update({"state": FAIL, "applicable": True, "reason": "distribution failed"})
        (root / DIST).unlink()
        (root / RR).write_text(json.dumps(rr_distribution_fail), encoding="utf-8")
        distribution_failure = build_report(root)
        assert distribution_failure["state"] == FAIL
        assert any(row["key"] == "DISTRIBUTION_EVIDENCE" for row in distribution_failure["failures"])
        (root / DIST).write_text(json.dumps(distribution), encoding="utf-8")
        distribution_conflict = build_report(root)
        assert distribution_conflict["state"] == FAIL
        assert any(row["key"] == "DISTRIBUTION_EVIDENCE" for row in distribution_conflict["failures"])
        (root / RR).write_text(json.dumps(reality), encoding="utf-8")
        (root / DIST).write_text(json.dumps(distribution), encoding="utf-8")

        assert stage("REQUIRED_NA", "Required N/A", True, NOT_APPLICABLE, "not applicable", [])["state"] == BLOCKED
        assert overall_state([
            {"required": True, "state": PASS},
            {"required": True, "state": NOT_APPLICABLE},
        ]) == BLOCKED

        stale_plan = json.loads(json.dumps(plan))
        stale_plan["head_sha"] = "e" * 40
        (root / PLAN).write_text(json.dumps(stale_plan), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        bad_lane = json.loads(json.dumps(plan))
        bad_lane["lane"] = "BOGUS"
        (root / PLAN).write_text(json.dumps(bad_lane), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / PLAN).write_text(json.dumps(plan), encoding="utf-8")

        (root / CERT).unlink()
        assert build_report(root)["state"] == BLOCKED
        (root / CERT).write_text(json.dumps(certification), encoding="utf-8")

        physical_fail_reality = json.loads(json.dumps(reality))
        physical_fail_reality["physical_evidence"] = {"required": False, "present": True}
        for row in physical_fail_reality["levels"]:
            if row.get("key") == "PHYSICAL_DEVICE_VERIFIED":
                row.update({"state": FAIL, "applicable": True, "reason": "optional physical test failed"})
        (root / RR).write_text(json.dumps(physical_fail_reality), encoding="utf-8")
        assert build_report(root)["state"] == FAIL
        (root / RR).write_text(json.dumps(reality), encoding="utf-8")

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
