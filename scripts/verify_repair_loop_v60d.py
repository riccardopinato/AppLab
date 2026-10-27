#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import agent_work_graph_v60a as workgraph
import verification_intelligence

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "verify-repair-loop-v1.json"


class LoopError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise LoopError("unsupported verify-repair loop contract version")
    if payload.get("contract_name") != "APPLAB_VERIFY_REPAIR_LOOP":
        raise LoopError("unexpected verify-repair loop contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise LoopError("verify-repair loop authority must remain orchestration-only")
    return payload


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalize_reason(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b[0-9a-f]{7,64}\b", "<hex>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", text)
    return re.sub(r"\s+", " ", text).strip()[:400]


def _failure(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    existing = result.get("failure_intelligence")
    if isinstance(existing, dict) and existing.get("kind"):
        return existing
    return verification_intelligence.classify_failure(result, plan)


def failure_signature(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    intelligence = _failure(result, plan)
    payload = {
        "classification": str(intelligence.get("kind", "UNKNOWN_FAILURE")),
        "failed_labs": sorted(str(x) for x in intelligence.get("failed_labs", []) if str(x)),
        "normalized_reason": _normalize_reason(
            " ".join(
                str(result.get(key, "") or "")
                for key in ("reason", "build_error", "error", "pipeline_status")
            )
            + " "
            + str(intelligence.get("reason", "") or "")
        ),
    }
    return {**payload, "signature_sha256": _digest(payload)}


def fix_result_identity(result: dict[str, Any]) -> str:
    stable = {
        "record_type": result.get("record_type"),
        "state": result.get("state"),
        "repository": result.get("repository"),
        "resolved_sha": str(result.get("resolved_sha") or "").lower(),
        "work_item_id": result.get("work_item_id"),
        "attempt_number": int(result.get("attempt_number", 0) or 0),
        "patch_sha256": result.get("patch_sha256"),
        "result_patch_sha256": result.get("result_patch_sha256"),
        "changed_files": sorted(str(x) for x in result.get("changed_files", []) if str(x)),
        "additions": int(result.get("additions", 0) or 0),
        "deletions": int(result.get("deletions", 0) or 0),
        "changed_lines": int(result.get("changed_lines", 0) or 0),
    }
    return _digest(stable)


def _verify_work_item(work_item: dict[str, Any], contract: dict[str, Any]) -> int:
    workgraph.validate_work_item(work_item, workgraph.load_contract())
    budget = int((work_item.get("budgets") or {}).get("max_repair_attempts", 0) or 0)
    if budget < 1:
        raise LoopError("WorkItem has no repair budget")
    return min(budget, int(contract["max_repair_attempts"]))


def _validate_fix(
    work_item: dict[str, Any],
    fix: dict[str, Any],
    number: int,
    contract: dict[str, Any],
) -> str:
    if fix.get("record_type") != contract["required_fix_record_type"]:
        raise LoopError("attempt does not contain canonical BOUNDED_FIX_RESULT_V60C")
    if fix.get("state") != contract["required_fix_state"]:
        raise LoopError("bounded fix is not READY_FOR_VERIFICATION")
    if str(fix.get("repository") or "") != str(work_item.get("repository") or ""):
        raise LoopError("fix repository identity mismatch")
    if str(fix.get("resolved_sha") or "").lower() != str(work_item.get("resolved_sha") or "").lower():
        raise LoopError("fix source SHA identity mismatch")
    if str(fix.get("work_item_id") or "") != str(work_item.get("work_item_id") or ""):
        raise LoopError("fix WorkItem identity mismatch")
    if int(fix.get("attempt_number", 0) or 0) != number:
        raise LoopError("fix attempt number mismatch")
    if fix.get("remote_write_performed") is not False:
        raise LoopError("v6.0D accepts only non-pushed v6.0C fix results")
    return fix_result_identity(fix)


def _status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "NOT_VERIFIED"
    raw = str(payload.get("result") or payload.get("status") or payload.get("state") or "").upper()
    if raw in {"PASS", "SUCCESS", "SUCCEEDED"}:
        return "PASS"
    if raw in {"FAIL", "FAILED", "ERROR"}:
        return "FAIL"
    if raw in {"BLOCKED", "HOLD", "WAITING"}:
        return "BLOCKED"
    return "NOT_VERIFIED"


def _identity_bound(payload: dict[str, Any], work_item: dict[str, Any], identity: str) -> bool:
    return (
        str(payload.get("repository") or "") == str(work_item.get("repository") or "")
        and str(payload.get("resolved_sha") or "").lower()
        == str(work_item.get("resolved_sha") or "").lower()
        and str(payload.get("fix_result_identity_sha256") or "") == identity
    )


def evaluate(
    work_item: dict[str, Any],
    initial_triage: dict[str, Any],
    investigation: dict[str, Any],
    attempts: list[dict[str, Any]],
    *,
    plan: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    plan = plan or {}
    budget = _verify_work_item(work_item, contract)
    base = {
        "schema_version": 1,
        "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
        "authority": "ORCHESTRATION_ONLY",
        "repository": work_item.get("repository", ""),
        "resolved_sha": work_item.get("resolved_sha", ""),
        "work_item_id": work_item.get("work_item_id", ""),
        "repair_attempt_count": len(attempts),
        "merge_authority": "DENIED",
        "release_authority": "DENIED",
        "verification_authority": "OBSERVE_EXISTING_APPLAB_ONLY",
    }

    classification = str(initial_triage.get("classification", "UNKNOWN_FAILURE"))
    if classification == "UNKNOWN_FAILURE":
        return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "UNKNOWN_CLASSIFICATION"}
    if classification in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
        return {**base, "state": "WAITING_EXTERNAL", "next_action": "WAIT_EXTERNAL", "reason_code": "HUMAN_DECISION_REQUIRED"}
    if classification == "NONE":
        return {**base, "state": "COMPLETE", "next_action": "NONE", "reason_code": "VERIFIED_PASS"}
    if investigation.get("state") != "LOCALIZED":
        return {**base, "state": "NEEDS_INVESTIGATION", "next_action": "INVESTIGATE", "reason_code": "HUMAN_DECISION_REQUIRED"}
    if investigation.get("edit_recommendation") != "ELIGIBLE_FOR_BOUNDED_REPAIR":
        return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "HUMAN_DECISION_REQUIRED"}
    if len(attempts) > budget:
        raise LoopError("attempt history exceeds repair budget")
    if not attempts:
        return {**base, "state": "NEEDS_REPAIR", "next_action": "APPLY_BOUNDED_REPAIR", "next_attempt_number": 1, "reason_code": "HUMAN_DECISION_REQUIRED"}

    signatures: list[dict[str, Any]] = []
    previous_class = ""
    previous_signature = ""

    for number, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict) or int(attempt.get("attempt_number", 0) or 0) != number:
            raise LoopError("attempt history must be contiguous and ordered")
        fix = attempt.get("fix_result")
        if not isinstance(fix, dict):
            raise LoopError("attempt missing fix_result")
        identity = _validate_fix(work_item, fix, number, contract)

        focused = attempt.get("focused_verification")
        focused_status = _status(focused)
        if focused_status == "NOT_VERIFIED":
            if number != len(attempts):
                raise LoopError("later repair exists before focused verification")
            return {**base, "state": "NEEDS_FOCUSED_VERIFY", "next_action": "RUN_FOCUSED_VERIFY", "reason_code": "HUMAN_DECISION_REQUIRED", "fix_result_identity_sha256": identity, "attempt_signatures": signatures}
        if focused_status == "BLOCKED":
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "VERIFICATION_BLOCKED", "fix_result_identity_sha256": identity, "attempt_signatures": signatures}
        if not isinstance(focused, dict) or not _identity_bound(focused, work_item, identity):
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "IDENTITY_NOT_PROVEN", "fix_result_identity_sha256": identity, "attempt_signatures": signatures}
        if focused_status == "FAIL":
            focused_sig = failure_signature(focused, plan)
            signatures.append({"attempt_number": number, "stage": "FOCUSED", **focused_sig})
            if focused_sig["classification"] == "UNKNOWN_FAILURE":
                return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "UNKNOWN_CLASSIFICATION", "attempt_signatures": signatures}
            if number >= budget:
                return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "BUDGET_EXHAUSTED", "attempt_signatures": signatures}
            return {**base, "state": "NEEDS_INVESTIGATION", "next_action": "INVESTIGATE", "next_attempt_number": number + 1, "reason_code": "HUMAN_DECISION_REQUIRED", "attempt_signatures": signatures}

        applab = attempt.get("applab_verification")
        applab_status = _status(applab)
        if applab_status == "NOT_VERIFIED":
            if number != len(attempts):
                raise LoopError("later repair exists before AppLab verification")
            return {**base, "state": "NEEDS_APPLAB_VERIFY", "next_action": "RUN_APPLAB_FAST", "reason_code": "HUMAN_DECISION_REQUIRED", "fix_result_identity_sha256": identity, "attempt_signatures": signatures}
        if not isinstance(applab, dict) or not _identity_bound(applab, work_item, identity):
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "IDENTITY_NOT_PROVEN", "fix_result_identity_sha256": identity, "attempt_signatures": signatures}
        if applab_status == "PASS":
            if number != len(attempts):
                raise LoopError("attempt history continues after PASS")
            return {
                **base,
                "state": "COMPLETE",
                "next_action": "OPEN_DRAFT_PR",
                "reason_code": "VERIFIED_PASS",
                "fix_result_identity_sha256": identity,
                "observed_verification_result": "PASS",
                "attempt_signatures": signatures,
            }
        if applab_status == "BLOCKED":
            intel = _failure(applab, plan)
            if str(intel.get("kind")) in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
                return {**base, "state": "WAITING_EXTERNAL", "next_action": "WAIT_EXTERNAL", "reason_code": "HUMAN_DECISION_REQUIRED", "attempt_signatures": signatures}
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "VERIFICATION_BLOCKED", "attempt_signatures": signatures}

        signature = failure_signature(applab, plan)
        signatures.append({"attempt_number": number, "stage": "APPLAB", **signature})
        current_class = signature["classification"]
        if current_class == "UNKNOWN_FAILURE":
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "UNKNOWN_CLASSIFICATION", "attempt_signatures": signatures}
        if current_class in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
            return {**base, "state": "WAITING_EXTERNAL", "next_action": "WAIT_EXTERNAL", "reason_code": "HUMAN_DECISION_REQUIRED", "attempt_signatures": signatures}
        if previous_class and current_class != previous_class:
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "UNEXPLAINED_FAILURE_MUTATION", "attempt_signatures": signatures}
        if number >= 2 and previous_signature == signature["signature_sha256"]:
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "REPEATED_FAILURE_SIGNATURE", "attempt_signatures": signatures}

        previous_class = current_class
        previous_signature = signature["signature_sha256"]
        if number >= budget:
            return {**base, "state": "STOPPED", "next_action": "NONE", "reason_code": "BUDGET_EXHAUSTED", "attempt_signatures": signatures}
        if number == len(attempts):
            return {**base, "state": "NEEDS_INVESTIGATION", "next_action": "INVESTIGATE", "next_attempt_number": number + 1, "reason_code": "HUMAN_DECISION_REQUIRED", "attempt_signatures": signatures}

    raise LoopError("unreachable verify-repair state")


def _fixture_work_item() -> dict[str, Any]:
    contract = workgraph.load_contract()
    return {
        "schema_version": 1,
        "record_type": "APPLAB_WORK_ITEM",
        "work_item_id": "wrk_loop",
        "operation_id": "op_loop",
        "repository": "owner/app",
        "source_ref": "main",
        "resolved_sha": "b" * 40,
        "baseline_sha": "a" * 40,
        "applab_sha": "c" * 40,
        "risk": "NORMAL",
        "state": "PLANNED",
        "authority": "ORCHESTRATION_ONLY",
        "authority_envelope": {
            "allowed_capabilities": ["READ_REPOSITORY", "READ_EVIDENCE", "RUN_FOCUSED_TESTS", "RUN_APPLAB_FAST", "ALLOW_CODE_EDIT"],
            "denied_capabilities": list(contract["authority_envelope"]["mandatory_denials"]),
        },
        "budgets": {"max_files": 5, "max_changed_lines": 250, "max_repair_attempts": 2, "max_agent_actions": 24},
        "acceptance_criteria": ["trusted AppLab PASS"],
        "required_evidence": ["exact fix result identity"],
        "rollback": {"strategy": "discard bounded repair workspace"},
        "terminal_conditions": list(contract["terminal_conditions"]),
    }


def _fix(number: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "BOUNDED_FIX_RESULT_V60C",
        "authority": "BRANCH_WORKSPACE_ONLY",
        "state": "READY_FOR_VERIFICATION",
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "work_item_id": "wrk_loop",
        "attempt_number": number,
        "branch": f"applab/repair/bbbbbbbbbb-a{number}",
        "patch_sha256": str(number) * 64,
        "result_patch_sha256": str(number + 1) * 64,
        "changed_files": ["lib/fix.py"],
        "additions": 1,
        "deletions": 1,
        "changed_lines": 2,
        "repository_mutation_performed": True,
        "remote_write_performed": False,
    }


def _attempt(number: int, applab: dict[str, Any] | None) -> dict[str, Any]:
    fix = _fix(number)
    identity = fix_result_identity(fix)
    focused = {
        "result": "PASS",
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "fix_result_identity_sha256": identity,
    }
    row: dict[str, Any] = {"attempt_number": number, "fix_result": fix, "focused_verification": focused}
    if applab is not None:
        row["applab_verification"] = {
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "fix_result_identity_sha256": identity,
            **applab,
        }
    return row


def self_test() -> None:
    item = _fixture_work_item()
    triage = {"classification": "BUILD_OR_QUALITY_FAILURE"}
    investigation = {"state": "LOCALIZED", "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR"}

    start = evaluate(item, triage, investigation, [])
    assert start["state"] == "NEEDS_REPAIR"

    pending = evaluate(item, triage, investigation, [_attempt(1, None)])
    assert pending["state"] == "NEEDS_APPLAB_VERIFY"

    passed = evaluate(item, triage, investigation, [_attempt(1, {"result": "PASS", "runtime_result": "PASS"})])
    assert passed["state"] == "COMPLETE"
    assert passed["next_action"] == "OPEN_DRAFT_PR"

    fail1 = _attempt(1, {"result": "FAIL", "build_error": "unit test failed at line 10"})
    next_try = evaluate(item, triage, investigation, [fail1])
    assert next_try["next_attempt_number"] == 2

    fail2 = _attempt(2, {"result": "FAIL", "build_error": "unit test failed at line 99"})
    repeated = evaluate(item, triage, investigation, [fail1, fail2])
    assert repeated["reason_code"] == "REPEATED_FAILURE_SIGNATURE"

    mutation = _attempt(2, {"result": "FAIL", "network_lab": "FAIL", "reason": "network regression"})
    changed = evaluate(item, triage, investigation, [fail1, mutation])
    assert changed["reason_code"] == "UNEXPLAINED_FAILURE_MUTATION"

    broken_identity = _attempt(1, {"result": "PASS"})
    broken_identity["applab_verification"]["fix_result_identity_sha256"] = "sha256:" + "0" * 64
    identity = evaluate(item, triage, investigation, [broken_identity])
    assert identity["reason_code"] == "IDENTITY_NOT_PROVEN"

    print("AppLab v6.0D canonical verify-repair loop self-test PASS")


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LoopError(f"JSON root must be an object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-item", default="")
    parser.add_argument("--triage", default="")
    parser.add_argument("--investigation", default="")
    parser.add_argument("--attempts", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.work_item or not args.triage or not args.investigation:
        raise SystemExit("--work-item, --triage and --investigation are required")
    attempts_payload = _read_json(args.attempts) if args.attempts else {"attempts": []}
    attempts = attempts_payload.get("attempts")
    if not isinstance(attempts, list):
        raise LoopError("attempts payload must contain a list")
    report = evaluate(
        _read_json(args.work_item),
        _read_json(args.triage),
        _read_json(args.investigation),
        attempts,
        plan=_read_json(args.plan) if args.plan else {},
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
