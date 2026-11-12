#!/usr/bin/env python3
"""X10-033: fail-closed, read-only release decision brief across EXISTING AppLab authorities.

Does NOT replace release_assurance/release_reality, trusted evidence verifier,
CI, signing, release_artifact or product-owner signoff. Report-only everywhere.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+\Z")
STATES = frozenset(("PASS", "FAIL", "BLOCKED", "NOT_VERIFIED", "N/A"))
REQUIRED_STAGES = frozenset((
    "SOURCE_BUILD_BOUND", "STATIC_BUILD_ASSURANCE", "TRUSTED_RUNTIME",
    "EVIDENCE_GRAPH", "RISK_BASED_VALIDATION", "CERTIFICATION",
))
REQUIRED_CHECKS = frozenset((
    "AppLab CI", "AppLab CodeQL", "Repository Governance Audit",
    "Canonical Runtime Fixture Build", "Emulator Self Test",
    "AppLab True Autonomous App Review v5.3.5", "Live Emulator Browser E2E",
))
MAX_SCREENS = 30


class DecisionGateError(ValueError):
    pass


def demand(ok: bool, code: str) -> None:
    if not ok:
        raise DecisionGateError(code)


def _identity(record: dict[str, Any], ident: dict[str, Any], kind: str,
              *, include_package: bool = True) -> None:
    demand(isinstance(record, dict)
           and record.get("repository") == ident["repository"]
           and record.get("source_sha") == ident["source_sha"]
           and (not include_package or record.get("package_id") == ident["package_id"]),
           kind + "_IDENTITY_MISMATCH")


def assess_release_decision(
    payload: dict[str, Any], *,
    trusted_evidence_lookup: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate existing reports without minting any release authority.

    Trusted evidence lookup MUST be a host-owned independent provenance resolver,
    never the app under test or caller-supplied report. Fixtures cannot attest CI.
    """
    demand(isinstance(payload, dict) and set(payload) == {
        "schema_version", "identity", "workflow_checks", "qa", "visual",
        "performance", "signing", "release_assurance",
    } and payload["schema_version"] == 1, "INVALID_DECISION_SCHEMA")
    ident = payload["identity"]
    demand(isinstance(ident, dict)
           and set(ident) == {"repository", "source_sha", "apk_sha256", "package_id",
                              "version_code", "workflow_run_id", "workflow_repository"}
           and isinstance(ident["repository"], str) and REPO.fullmatch(ident["repository"]) is not None
           and isinstance(ident["source_sha"], str) and SHA40.fullmatch(ident["source_sha"]) is not None
           and isinstance(ident["apk_sha256"], str) and SHA256.fullmatch(ident["apk_sha256"]) is not None
           and isinstance(ident["package_id"], str) and PACKAGE.fullmatch(ident["package_id"]) is not None
           and isinstance(ident["version_code"], str) and ident["version_code"].isdigit()
           and isinstance(ident["workflow_run_id"], int) and type(ident["workflow_run_id"]) is int
           and ident["workflow_run_id"] > 0
           and isinstance(ident["workflow_repository"], str)
           and ident["workflow_repository"].casefold() in {
               ident["repository"].casefold(), "riccardopinato/applab"},
           "RELEASE_IDENTITY_INVALID")
    demand(callable(trusted_evidence_lookup), "TRUSTED_EVIDENCE_RESOLVER_REQUIRED")
    blockers: list[str] = []
    checks = payload["workflow_checks"]
    demand(isinstance(checks, list) and len(checks) == len(REQUIRED_CHECKS),
           "REQUIRED_WORKFLOW_CHECKS_MISSING")
    by_name = {}
    for check in checks:
        demand(isinstance(check, dict)
               and set(check) == {"name", "source_sha", "status", "conclusion", "run_id"}
               and isinstance(check["name"], str) and check["name"] in REQUIRED_CHECKS
               and check["name"] not in by_name
               and check["source_sha"] == ident["source_sha"]
               and type(check["run_id"]) is int and check["run_id"] > 0
               and check["status"] in ("completed", "in_progress", "queued", "pending")
               and check["conclusion"] in (None, "success", "failure", "cancelled", "skipped", "timed_out"),
               "WORKFLOW_HEAD_OR_CHECKLIST_INVALID")
        by_name[check["name"]] = check
    demand(set(by_name) == REQUIRED_CHECKS, "WORKFLOW_REQUIRED_SET_MISMATCH")
    for name, check in by_name.items():
        if check["status"] != "completed" or check["conclusion"] != "success":
            blockers.append("CI_NOT_GREEN:" + name)

    qa = payload["qa"]
    # Canonical qa_test_router_x10.delegate receipt has no package_id.
    _identity(qa, ident, "QA", include_package=False)
    demand(qa.get("record_type") == "APP_FACTORY_X10_QA_RECEIPT"
           and qa.get("analysis_mode") == "certification"
           and qa.get("independent_provenance_verified") is False
           and qa.get("certification_granted") is False
           and qa.get("store_release_granted") is False
           and qa.get("state") in ("RUNNER_REPORTED_ONLY", "BLOCKED_OR_FAIL_REPORTED")
           and isinstance(qa.get("gate_results"), dict)
           and isinstance(qa.get("run_url"), str)
           and re.fullmatch(
               re.escape(f"https://github.com/{ident['workflow_repository']}/actions/runs/{ident['workflow_run_id']}")
               + r"(?:/attempts/[1-9][0-9]*)?", qa["run_url"]) is not None,
           "QA_RECEIPT_INVALID_OR_NON_CERTIFICATION")
    if qa["state"] != "RUNNER_REPORTED_ONLY" or not qa["gate_results"] or any(
            state != "PASS" for state in qa["gate_results"].values()):
        blockers.append("QA_NOT_ALL_REPORTED_PASS")

    visual = payload["visual"]
    demand(isinstance(visual, list) and 1 <= len(visual) <= MAX_SCREENS,
           "VISUAL_SCREEN_COVERAGE_MISSING")
    names = set()
    for case in visual:
        _identity(case, ident, "VISUAL")
        screen = case.get("screen")
        profile = case.get("profile")
        demand(isinstance(profile, dict) and set(profile) == {
            "theme", "locale", "form_factor", "text_scale"
        } and profile["theme"] in ("light", "dark")
           and profile["form_factor"] in ("phone", "tablet")
           and isinstance(profile["locale"], str)
           and re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", profile["locale"]) is not None
           and type(profile["text_scale"]) in (int, float)
           and 0.8 <= profile["text_scale"] <= 2.0,
           "VISUAL_PROFILE_INVALID")
        key = (screen, profile["theme"], profile["locale"], profile["form_factor"],
               profile["text_scale"])
        demand(case.get("record_type") == "X10_VISUAL_BASELINE_DIFF"
               and case.get("authority") == "REPORT_ONLY"
               and isinstance(screen, str) and 1 <= len(screen) <= 100
               and key not in names
               and case.get("certified") is False
               and case.get("false_positives_auto_approved") is False,
               "VISUAL_RECEIPT_INVALID")
        names.add(key)
        if case.get("state") != "REFERENCE_MATCH_REPORTED":
            blockers.append("VISUAL_REVIEW_REQUIRED:" + screen + ":" + profile["theme"])

    performance = payload["performance"]
    _identity(performance, ident, "PERFORMANCE")
    demand(performance.get("record_type") == "X10_PERF_A11Y_REVIEW_RECEIPT"
           and performance.get("authority") == "REPORT_ONLY"
           and performance.get("apk_sha256") == ident["apk_sha256"]
           and performance.get("workflow_run_id") == ident["workflow_run_id"]
           and performance.get("consumer_certified") is False
           and performance.get("independent_provenance_verified") is False
           and isinstance(performance.get("accessibility_findings"), list)
           and isinstance(performance.get("regression_codes"), list),
           "PERFORMANCE_RECEIPT_INVALID")
    if (performance.get("state") != "BENCHMARK_MATCH_REPORTED" or
            performance.get("baseline") != "APPROVED_REFERENCE_REPORTED" or
            performance["accessibility_findings"] or performance["regression_codes"]):
        blockers.append("PERFORMANCE_OR_A11Y_REVIEW_REQUIRED")

    signing = payload["signing"]
    _identity(signing, ident, "SIGNING")
    demand(signing.get("record_type") == "X10_SIGNED_RELEASE_PROVENANCE_CANDIDATE"
           and signing.get("authority") == "SOURCE_BOUND_ONLY"
           and signing.get("workflow_run_id") == ident["workflow_run_id"]
           and signing.get("version_code") == ident["version_code"]
           and signing.get("state") == "PENDING_INDEPENDENT_REMOTE_AND_DEVICE_EVIDENCE"
           and signing.get("store_ready") is False
           and signing.get("production_released") is False
           and isinstance(signing.get("artifacts"), list)
           and bool(signing["artifacts"])
           and any(item.get("sha256") == ident["apk_sha256"] and item.get("kind") == "APK"
                   for item in signing["artifacts"] if isinstance(item, dict)),
           "SIGNING_SOURCE_OR_ARTIFACT_MISMATCH")

    assurance = payload["release_assurance"]
    demand(isinstance(assurance, dict)
           and assurance.get("record_type") == "AUTONOMOUS_RELEASE_ASSURANCE"
           and assurance.get("authority") == "APPLAB_RELEASE_ASSURANCE"
           and isinstance(assurance.get("identity"), dict)
           and assurance["identity"].get("repository") == ident["repository"]
           and assurance["identity"].get("resolved_sha") == ident["source_sha"]
           and assurance["identity"].get("artifact_sha256") == ident["apk_sha256"]
           and assurance["identity"].get("package_id") == ident["package_id"]
           and str(assurance["identity"].get("version_code")) == ident["version_code"]
           and assurance.get("state") in ("PASS", "FAIL", "BLOCKED")
           and isinstance(assurance.get("stages"), list),
           "CANONICAL_RELEASE_ASSURANCE_MISMATCH")
    stages = {}
    for row in assurance["stages"]:
        demand(isinstance(row, dict) and isinstance(row.get("key"), str)
               and row["key"] not in stages and row.get("state") in STATES
               and type(row.get("required")) is bool,
               "CANONICAL_STAGE_MALFORMED_OR_DUPLICATE")
        stages[row["key"]] = row
    demand(REQUIRED_STAGES.issubset(stages)
           and all(stages[k]["required"] is True for k in REQUIRED_STAGES),
           "CANONICAL_REQUIRED_STAGE_MISSING")
    if (assurance["state"] != "PASS" or any(
            row["required"] and row["state"] != "PASS" for row in stages.values())):
        blockers.append("CANONICAL_ASSURANCE_NOT_PASS")
    # Never let the caller assert provenance; check an independent host-owned
    # verifier for each existing report separately. No trust-token persistence.
    refs = {"qa": qa, "visual": visual, "performance": performance,
            "signing": signing, "release_assurance": assurance,
            "workflow_checks": checks}
    for kind, report in refs.items():
        trusted = trusted_evidence_lookup(kind, report)
        demand(isinstance(trusted, dict)
               and trusted.get("repository") == ident["repository"]
               and trusted.get("source_sha") == ident["source_sha"]
               and trusted.get("apk_sha256") == ident["apk_sha256"]
               and trusted.get("workflow_run_id") == ident["workflow_run_id"],
               "EXTERNAL_EVIDENCE_IDENTITY_MISMATCH")
        if trusted.get("verified") is not True:
            blockers.append("INDEPENDENT_EVIDENCE_UNVERIFIED:" + kind)
    blockers = sorted(set(blockers))
    fingerprint = hashlib.sha256(json.dumps({
        "identity": ident, "blockers": blockers, "canonical_assurance_state": assurance["state"]
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "record_type": "X10_RELEASE_DECISION_BRIEF",
        "authority": "REPORT_ONLY",
        "state": ("BLOCKED_OR_UNVERIFIED" if blockers else "INPUTS_REPORTED_READY_FOR_HUMAN_REVIEW"),
        "repository": ident["repository"], "source_sha": ident["source_sha"],
        "apk_sha256": ident["apk_sha256"], "package_id": ident["package_id"],
        "workflow_run_id": ident["workflow_run_id"],
        "blockers": blockers, "decision_fingerprint": fingerprint,
        "canonical_assurance_state": assurance["state"],
        "next_action": "REQUIRE_INDEPENDENT_PRODUCT_OWNER_RELEASE_APPROVAL",
        "release_authorized": False, "auto_store_publish": False,
        "physical_device_verification_granted": False,
        "trusted_runtime_verification_granted": False,
        "certification_granted": False, "production_released": False,
    }
