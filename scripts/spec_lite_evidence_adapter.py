"""Factory Spec Lite acceptance -> existing AppLab WorkGraph/evidence trace.

No new verifier, scheduler, receipt issuer, persistent ledger or certification.
The caller injects AppLab's trusted evidence verifier and authenticated
product-decision lookup; untrusted text cannot grant PASS or merge authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

import agent_work_graph_v60a as workgraph

SHA = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQ = re.compile(r"^FR-[0-9]{3}$")
AC = re.compile(r"^AC-[0-9]{3}$")
ALLOWED_CHECKS = frozenset({
    "SOURCE_TEST", "UNIT_TEST", "INTEGRATION_TEST", "RUNTIME_TEST",
    "DEVICE_TEST", "PROVIDER_TEST", "MANUAL_ACCEPTANCE"
})


class SpecEvidenceError(ValueError):
    """No attestation or source mutation occurred; projection rejected."""


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def project_spec_evidence(
    manifest: dict[str, Any],
    binding: dict[str, Any],
    work_item: dict[str, Any],
    receipts: list[dict[str, Any]],
    *,
    expected_factory_sha: str,
    expected_source_sha: str,
    expected_job_sha256: str,
    expected_spec_sha256: str,
    trusted_evidence_verifier: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    trusted_product_decision: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Project criterion coverage only after AppLab WorkGraph and source checks.

    expected_job_sha256 AND expected_spec_sha256 MUST be resolved
    independently from trusted durable Agent Core/AppLab admission context;
    never derive either from the supplied manifest or Spec Lite projection.
    A verifier callback MUST delegate to an independent AppLab-authorized,
    immutable-evidence verifier, never to a user-provided boolean/LLM claim.
    Passing unit fake callbacks is only fixture proof, not real validation.
    """
    if not all(isinstance(x, dict) for x in (manifest, binding, work_item)) or not isinstance(receipts, list):
        raise SpecEvidenceError("MALFORMED_INPUT")
    if (not isinstance(expected_factory_sha, str) or not SHA.fullmatch(expected_factory_sha)
        or not isinstance(expected_source_sha, str) or not SHA.fullmatch(expected_source_sha)):
        raise SpecEvidenceError("TRUSTED_BASELINE_MISSING")
    if (manifest.get("schema_version") != 1
        or manifest.get("factory", {}).get("sha") != expected_factory_sha
        or manifest.get("canonical_refs", {}).get("factory_current", {}).get("sha") != expected_factory_sha
        or manifest.get("target", {}).get("source_sha") != expected_source_sha):
        raise SpecEvidenceError("FACTORY_OR_SOURCE_SHA_DRIFT")
    if not isinstance(expected_job_sha256, str) or not HEX64.fullmatch(expected_job_sha256):
        raise SpecEvidenceError("TRUSTED_JOB_DIGEST_REQUIRED")
    if not isinstance(expected_spec_sha256, str) or not HEX64.fullmatch(expected_spec_sha256):
        raise SpecEvidenceError("TRUSTED_SPEC_DIGEST_REQUIRED")
    if binding.get("job_sha256") != expected_job_sha256:
        raise SpecEvidenceError("BINDING_JOB_DIGEST_MISMATCH")
    if _digest(manifest) != expected_spec_sha256:
        raise SpecEvidenceError("MANIFEST_DIGEST_MISMATCH")
    if binding.get("spec_sha256") != expected_spec_sha256:
        raise SpecEvidenceError("BINDING_SPEC_DIGEST_MISMATCH")
    if (binding.get("schema_version") != 1
        or binding.get("record_type") != "FSL_WORK_ITEM_TRACE_PROJECTION"
        or binding.get("authority") != "TRACE_ONLY"
        or binding.get("spec_id") != manifest.get("spec_id")):
        raise SpecEvidenceError("UNTRUSTED_OR_CHANGED_SPEC_BINDING")
    if (not isinstance(binding.get("job_sha256"), str) or not HEX64.fullmatch(binding["job_sha256"])
        or not isinstance(binding.get("binding_id"), str)
        or not binding["binding_id"].startswith("fsl_")
        or binding.get("runtime_verified") is not False
        or binding.get("side_effects_performed") is not False
        or binding.get("dispatch_performed") is not False
        or binding.get("certified") is not False):
        raise SpecEvidenceError("BINDING_AUTHORITY_ESCALATION")
    try:
        # AppLab is sole WorkItem schema authority, using its current contract.
        workgraph.validate_work_item(work_item, workgraph.load_contract())
    except (ValueError, KeyError, TypeError) as exc:
        raise SpecEvidenceError("EXISTING_APPLAB_WORKITEM_INVALID") from exc
    repo = manifest.get("target", {}).get("repository")
    if (binding.get("source_sha") != expected_source_sha
        or binding.get("repository") != repo
        or work_item.get("repository") != repo
        or work_item.get("resolved_sha") != expected_source_sha
        or work_item.get("work_item_id") != binding.get("work_item_id")
        or work_item.get("operation_id") != binding.get("operation_id")):
        raise SpecEvidenceError("WORKITEM_SOURCE_OR_IDENTITY_MISMATCH")
    requirements = manifest.get("requirements")
    checks = manifest.get("validation", {}).get("required_checks")
    if (not isinstance(requirements, list) or not requirements
        or not isinstance(checks, list) or not checks
        or any(not isinstance(x, str) for x in checks)
        or not set(checks).issubset(ALLOWED_CHECKS)):
        raise SpecEvidenceError("REQUIRED_TEST_POLICY_MISSING")
    expected = []
    seen_req, seen_ac = set(), set()
    for req in requirements:
        if not isinstance(req, dict) or not REQ.fullmatch(str(req.get("id",""))) or req["id"] in seen_req:
            raise SpecEvidenceError("INVALID_REQUIREMENT_ID")
        seen_req.add(req["id"])
        acs = req.get("acceptance")
        if not isinstance(acs, list) or not acs or req.get("conflicts_with"):
            raise SpecEvidenceError("MISSING_OR_CONFLICTING_REQUIREMENTS")
        for ac in acs:
            if (not isinstance(ac, dict) or not AC.fullmatch(str(ac.get("id","")))
                or ac["id"] in seen_ac):
                raise SpecEvidenceError("DUPLICATE_OR_INVALID_ACCEPTANCE")
            seen_ac.add(ac["id"])
            if ac.get("evidence_type") not in checks:
                raise SpecEvidenceError("REQUIRED_TEST_NOT_DECLARED")
            expected.append({"requirement_id": req["id"], "acceptance_id": ac["id"],
                             "required_check": ac["evidence_type"]})
    unused_required_checks = set(checks) - {item["required_check"] for item in expected}
    if unused_required_checks:
        # A required check with no acceptance mapping cannot be evidenced.
        # Reject the inconsistent manifest rather than report false completeness.
        raise SpecEvidenceError("REQUIRED_CHECK_UNMAPPED:" + ",".join(sorted(unused_required_checks)))
    if binding.get("acceptance") != expected:
        raise SpecEvidenceError("BINDING_ACCEPTANCE_DRIFT")

    known: dict[str, dict[str, Any]] = {}
    for rec in receipts:
        if not isinstance(rec, dict):
            raise SpecEvidenceError("EVIDENCE_MALFORMED")
        evidence_id = rec.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or len(evidence_id) > 160:
            raise SpecEvidenceError("EVIDENCE_ID_MISSING")
        if evidence_id in known:
            if known[evidence_id] != rec:
                raise SpecEvidenceError("REPLAY_RECEIPT_IDENTITY_CONFLICT")
            continue  # identical replay is idempotent and not double-counted
        if (rec.get("repository") != repo or rec.get("resolved_sha") != expected_source_sha
            or rec.get("work_item_id") != work_item["work_item_id"]):
            raise SpecEvidenceError("EVIDENCE_IMMUTABLE_IDENTITY_MISMATCH")
        kind = rec.get("check_type")
        ac_id = rec.get("acceptance_id")
        if not any(x["acceptance_id"] == ac_id and x["required_check"] == kind for x in expected):
            raise SpecEvidenceError("EVIDENCE_UNDECLARED_CRITERION_OR_TEST")
        if rec.get("outcome") != "PASS":
            raise SpecEvidenceError("EVIDENCE_NOT_PASS")
        if not callable(trusted_evidence_verifier):
            raise SpecEvidenceError("EXISTING_TRUSTED_VERIFIER_REQUIRED")
        if trusted_evidence_verifier(rec, work_item) is not True:
            raise SpecEvidenceError("UNTRUSTED_EVIDENCE")
        known[evidence_id] = rec

    evidence_by_ac: dict[str, list[str]] = {item["acceptance_id"]: [] for item in expected}
    for evidence_id, rec in known.items():
        evidence_by_ac[rec["acceptance_id"]].append(evidence_id)
    coverage = [
        {"requirement_id": item["requirement_id"], "acceptance_id": item["acceptance_id"],
         "required_check": item["required_check"], "evidence_ref_ids": sorted(evidence_by_ac[item["acceptance_id"]]),
         "state": "EVIDENCE_LINKED_SOURCE_ONLY" if evidence_by_ac[item["acceptance_id"]] else "NOT_VERIFIED"}
        for item in expected
    ]
    missing = [x["acceptance_id"] for x in coverage if not x["evidence_ref_ids"]]
    approved = (
        manifest.get("approval", {}).get("status") == "APPROVED"
        and all(r.get("status") == "APPROVED" for r in requirements)
        and callable(trusted_product_decision)
        and trusted_product_decision(manifest) is True
    )
    state = (
        "MISSING_EVIDENCE" if missing else
        "SOURCE_EVIDENCE_LINKED_NOT_APPROVED" if not approved else
        "SOURCE_EVIDENCE_LINKED_NOT_CERTIFIED"
    )
    return {
        "schema_version": 1, "record_type": "APPLAB_SPEC_LITE_COVERAGE_PROJECTION",
        "spec_id": manifest["spec_id"], "repository": repo,
        "resolved_sha": expected_source_sha, "work_item_id": work_item["work_item_id"],
        "binding_id": binding["binding_id"], "state": state,
        "criteria": coverage, "missing_acceptance_ids": missing,
        "linked_evidence_count": len(known), "product_decision_verified": bool(approved),
        "authority": "TRACE_ONLY", "source_only": True, "runtime_verified": False,
        "physical_verified": False, "certified": False,
        "work_item_mutated": False, "side_effects_performed": False,
    }
