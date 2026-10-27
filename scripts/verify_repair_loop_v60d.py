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
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "verify-repair-loop-v1.json"
)
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


class RepairLoopError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RepairLoopError("unsupported verify-repair loop contract version")
    if payload.get("contract_name") != "APPLAB_VERIFY_REPAIR_LOOP":
        raise RepairLoopError("unexpected verify-repair loop contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise RepairLoopError("verify-repair loop must remain orchestration-only")
    return payload


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalize_reason(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b[0-9a-f]{7,64}\b", "<hex>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<n>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def _classify(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    existing = result.get("failure_intelligence")
    if isinstance(existing, dict) and existing.get("kind"):
        return existing
    return verification_intelligence.classify_failure(result, plan)


def failure_signature(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    intelligence = _classify(result, plan)
    kind = str(intelligence.get("kind") or "UNKNOWN_FAILURE")
    failed_labs = sorted(
        str(value)
        for value in intelligence.get("failed_labs", [])
        if str(value)
    )
    reason = _normalize_reason(
        " ".join(
            str(value or "")
            for value in (
                intelligence.get("reason"),
                result.get("reason"),
                result.get("build_error"),
                result.get("error"),
            )
        )
    )
    payload = {
        "classification": kind,
        "failed_labs": failed_labs,
        "normalized_reason": reason,
    }
    return {**payload, "signature_sha256": _sha256(payload)}


def repair_identity(repair_result: dict[str, Any]) -> str:
    changed = sorted(
        str(path)
        for path in repair_result.get("changed_files", [])
        if str(path)
    )
    stable = {
        "repository": str(repair_result.get("repository") or ""),
        "resolved_sha": str(repair_result.get("resolved_sha") or "").lower(),
        "work_item_id": str(repair_result.get("work_item_id") or ""),
        "attempt_number": int(repair_result.get("attempt_number", 0) or 0),
        "patch_sha256": str(repair_result.get("patch_sha256") or "").lower(),
        "result_patch_sha256": str(
            repair_result.get("result_patch_sha256") or ""
        ).lower(),
        "changed_files": changed,
        "additions": int(repair_result.get("additions", 0) or 0),
        "deletions": int(repair_result.get("deletions", 0) or 0),
        "changed_lines": int(repair_result.get("changed_lines", 0) or 0),
    }
    return _sha256(stable)


def _validate_work_item(payload: dict[str, Any], *, require_edit: bool = True) -> None:
    workgraph.validate_work_item(payload, workgraph.load_contract())
    allowed = set(
        (payload.get("authority_envelope") or {}).get("allowed_capabilities") or []
    )
    if require_edit and "ALLOW_CODE_EDIT" not in allowed:
        raise RepairLoopError("repair WorkItem does not allow code edit")


def _identity_matches(
    payload: dict[str, Any],
    *,
    repository: str,
    resolved_sha: str,
    label: str,
) -> None:
    if str(payload.get("repository") or "") != repository:
        raise RepairLoopError(f"{label} repository identity mismatch")
    value = str(payload.get("resolved_sha") or "").lower()
    if value != resolved_sha:
        raise RepairLoopError(f"{label} resolved_sha identity mismatch")


def _validate_investigation(
    investigation: dict[str, Any],
    *,
    work_item: dict[str, Any],
) -> None:
    if not isinstance(investigation, dict):
        raise RepairLoopError("investigation must be an object")
    _identity_matches(
        investigation,
        repository=str(work_item["repository"]),
        resolved_sha=str(work_item["resolved_sha"]).lower(),
        label="investigation",
    )
    if investigation.get("state") != "LOCALIZED":
        raise RepairLoopError("investigation is not LOCALIZED")
    if investigation.get("edit_recommendation") != "ELIGIBLE_FOR_BOUNDED_REPAIR":
        raise RepairLoopError("investigation is not eligible for bounded repair")


def _validate_repair_result(
    repair_result: dict[str, Any],
    *,
    work_item: dict[str, Any],
    chain_attempt_number: int,
) -> str:
    if not isinstance(repair_result, dict):
        raise RepairLoopError("repair_result must be an object")
    if repair_result.get("record_type") != "BOUNDED_FIX_RESULT_V60C":
        raise RepairLoopError("unexpected repair_result record type")
    if repair_result.get("state") != "READY_FOR_VERIFICATION":
        raise RepairLoopError("repair_result is not ready for verification")
    _identity_matches(
        repair_result,
        repository=str(work_item["repository"]),
        resolved_sha=str(work_item["resolved_sha"]).lower(),
        label="repair_result",
    )
    if str(repair_result.get("work_item_id") or "") != str(
        work_item.get("work_item_id") or ""
    ):
        raise RepairLoopError("repair_result WorkItem identity mismatch")
    if int(repair_result.get("attempt_number", 0) or 0) != chain_attempt_number:
        raise RepairLoopError("repair_result chain attempt number mismatch")
    patch_hash = str(repair_result.get("result_patch_sha256") or "").lower()
    if not SHA256_RE.fullmatch(patch_hash):
        raise RepairLoopError("repair_result missing exact result patch SHA-256")
    changed = repair_result.get("changed_files")
    if not isinstance(changed, list) or not changed:
        raise RepairLoopError("repair_result contains no changed files")
    return repair_identity(repair_result)


def _status(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "NOT_VERIFIED"
    raw = str(
        payload.get("status")
        or payload.get("result")
        or payload.get("state")
        or "NOT_VERIFIED"
    ).upper()
    if raw in {"PASS", "SUCCESS", "SUCCEEDED"}:
        return "PASS"
    if raw in {"FAIL", "FAILED", "ERROR"}:
        return "FAIL"
    if raw in {"BLOCKED", "HOLD", "WAITING"}:
        return "BLOCKED"
    return "NOT_VERIFIED"


def _validate_focused(
    payload: dict[str, Any],
    *,
    repair_identity_sha256: str,
) -> str:
    status = _status(payload)
    if status == "NOT_VERIFIED":
        return status
    bound = str(payload.get("repair_identity_sha256") or "")
    if bound != repair_identity_sha256:
        raise RepairLoopError("focused verification repair identity mismatch")
    return status


def _validate_materialization(
    payload: dict[str, Any],
    *,
    work_item: dict[str, Any],
    repair_identity_sha256: str,
    repair_result: dict[str, Any],
) -> str:
    if not isinstance(payload, dict):
        raise RepairLoopError("materialization must be an object")
    if str(payload.get("repair_identity_sha256") or "") != repair_identity_sha256:
        raise RepairLoopError("materialization repair identity mismatch")
    if str(payload.get("repository") or "") != str(work_item["repository"]):
        raise RepairLoopError("materialization repository identity mismatch")
    if str(payload.get("parent_sha") or "").lower() != str(
        work_item["resolved_sha"]
    ).lower():
        raise RepairLoopError("materialization parent SHA mismatch")
    repaired = str(payload.get("repaired_source_sha") or "").lower()
    if not SHA40_RE.fullmatch(repaired):
        raise RepairLoopError("materialization repaired_source_sha is invalid")
    result_patch = str(repair_result.get("result_patch_sha256") or "").lower()
    materialized_patch = str(payload.get("result_patch_sha256") or "").lower()
    if materialized_patch != result_patch:
        raise RepairLoopError("materialization result patch identity mismatch")
    return repaired


def _validate_trusted_runtime(
    result: dict[str, Any],
    trusted_evidence: dict[str, Any],
    *,
    repository: str,
    repaired_source_sha: str,
    contract: dict[str, Any],
) -> None:
    if not isinstance(result, dict):
        raise RepairLoopError("AppLab verification result must be an object")
    _identity_matches(
        result,
        repository=repository,
        resolved_sha=repaired_source_sha,
        label="AppLab verification",
    )
    if not isinstance(trusted_evidence, dict):
        raise RepairLoopError("trusted AppLab evidence is missing")
    trusted_contract = contract["trusted_runtime"]
    if trusted_contract.get("require_trusted_true") and trusted_evidence.get("trusted") is not True:
        raise RepairLoopError("AppLab verification evidence is not trusted")
    if str(trusted_evidence.get("producer") or "") != str(
        trusted_contract["producer"]
    ):
        raise RepairLoopError("unexpected trusted evidence producer")
    manifest_sha = str(trusted_evidence.get("manifest_sha256") or "").lower()
    if not SHA256_RE.fullmatch(manifest_sha):
        raise RepairLoopError("trusted evidence manifest hash is missing or invalid")
    if int(trusted_evidence.get("file_count", 0) or 0) < 1:
        raise RepairLoopError("trusted evidence manifest contains no evidence files")
    binding = trusted_evidence.get("binding")
    if not isinstance(binding, dict):
        raise RepairLoopError("trusted evidence binding is missing")
    if str(binding.get("repository") or "") != repository:
        raise RepairLoopError("trusted evidence repository mismatch")
    if str(binding.get("resolved_sha") or "").lower() != repaired_source_sha:
        raise RepairLoopError("trusted evidence resolved_sha mismatch")


def _base(
    root_work_item: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
        "authority": "ORCHESTRATION_ONLY",
        "repository": str(root_work_item.get("repository") or ""),
        "root_resolved_sha": str(root_work_item.get("resolved_sha") or ""),
        "root_work_item_id": str(root_work_item.get("work_item_id") or ""),
        "repair_attempt_count": len(attempts),
        "merge_authority": "DENIED",
        "release_authority": "DENIED",
        "verification_authority": "OBSERVE_EXISTING_TRUSTED_APPLAB_ONLY",
    }


def _stop(
    base: dict[str, Any],
    reason: str,
    *,
    signatures: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    return {
        **base,
        "state": "STOPPED",
        "next_action": "NONE",
        "reason_code": reason,
        "attempt_signatures": signatures,
        **extra,
    }


def _failed_verification_decision(
    *,
    base: dict[str, Any],
    result: dict[str, Any],
    plan: dict[str, Any],
    initial_class: str,
    attempt_number: int,
    max_attempts: int,
    signatures: list[dict[str, Any]],
    repaired_source_sha: str,
    repair_identity_sha256: str,
) -> dict[str, Any]:
    signature = failure_signature(result, plan)
    signatures = [*signatures, {"attempt_number": attempt_number, **signature}]
    failure_class = str(signature["classification"])

    if failure_class == "UNKNOWN_FAILURE":
        return _stop(
            base,
            "UNKNOWN_CLASSIFICATION",
            signatures=signatures,
            repaired_source_sha=repaired_source_sha,
            repair_identity_sha256=repair_identity_sha256,
        )
    if failure_class in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
        return {
            **base,
            "state": "WAITING_EXTERNAL",
            "next_action": "WAIT_EXTERNAL",
            "reason_code": "HUMAN_DECISION_REQUIRED",
            "attempt_signatures": signatures,
            "repaired_source_sha": repaired_source_sha,
            "repair_identity_sha256": repair_identity_sha256,
        }
    if failure_class != initial_class:
        return _stop(
            base,
            "UNEXPLAINED_FAILURE_MUTATION",
            signatures=signatures,
            repaired_source_sha=repaired_source_sha,
            repair_identity_sha256=repair_identity_sha256,
        )

    if attempt_number >= 2 and len(signatures) >= 2:
        if (
            signatures[-1]["signature_sha256"]
            == signatures[-2]["signature_sha256"]
        ):
            return _stop(
                base,
                "REPEATED_FAILURE_SIGNATURE",
                signatures=signatures,
                repaired_source_sha=repaired_source_sha,
                repair_identity_sha256=repair_identity_sha256,
            )

    if attempt_number >= max_attempts:
        return _stop(
            base,
            "BUDGET_EXHAUSTED",
            signatures=signatures,
            repaired_source_sha=repaired_source_sha,
            repair_identity_sha256=repair_identity_sha256,
        )

    return {
        **base,
        "state": "NEEDS_INVESTIGATION",
        "next_action": "INVESTIGATE",
        "reason_code": "HUMAN_DECISION_REQUIRED",
        "next_attempt_number": attempt_number + 1,
        "next_source_sha": repaired_source_sha,
        "attempt_signatures": signatures,
        "repair_identity_sha256": repair_identity_sha256,
    }


def evaluate_loop(
    root_work_item: dict[str, Any],
    initial_triage: dict[str, Any],
    initial_investigation: dict[str, Any],
    attempts: list[dict[str, Any]],
    *,
    plan: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    plan = plan or {}
    _validate_work_item(root_work_item)
    base = _base(root_work_item, attempts)

    initial_class = str(initial_triage.get("classification") or "UNKNOWN_FAILURE")
    deterministic = set(contract["deterministic_failure_classes"])
    if initial_class == "UNKNOWN_FAILURE":
        return _stop(base, "UNKNOWN_CLASSIFICATION", signatures=[])
    if initial_class in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
        return {
            **base,
            "state": "WAITING_EXTERNAL",
            "next_action": "WAIT_EXTERNAL",
            "reason_code": "HUMAN_DECISION_REQUIRED",
            "attempt_signatures": [],
        }
    if initial_class == "NONE":
        return {
            **base,
            "state": "COMPLETE",
            "next_action": "NONE",
            "reason_code": "VERIFIED_PASS",
            "attempt_signatures": [],
            "observed_verification_result": "PREEXISTING_PASS",
        }
    if initial_class not in deterministic:
        raise RepairLoopError(f"unsupported initial classification: {initial_class}")

    max_attempts = min(
        int(contract["max_repair_attempts"]),
        int((root_work_item.get("budgets") or {}).get("max_repair_attempts", 0) or 0),
    )
    if max_attempts < 1:
        raise RepairLoopError("root WorkItem has no repair budget")
    if len(attempts) > max_attempts:
        raise RepairLoopError("attempt history exceeds repair budget")

    if not attempts:
        _validate_investigation(initial_investigation, work_item=root_work_item)
        return {
            **base,
            "state": "NEEDS_REPAIR",
            "next_action": "APPLY_BOUNDED_REPAIR",
            "reason_code": "HUMAN_DECISION_REQUIRED",
            "next_attempt_number": 1,
            "next_source_sha": str(root_work_item["resolved_sha"]),
            "next_work_item_id": str(root_work_item["work_item_id"]),
            "attempt_signatures": [],
        }

    signatures: list[dict[str, Any]] = []
    previous_repaired_sha = ""
    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            raise RepairLoopError("attempt history item must be an object")
        if int(attempt.get("chain_attempt_number", 0) or 0) != index:
            raise RepairLoopError("attempt history must be contiguous and ordered")

        work_item = attempt.get("work_item")
        investigation = attempt.get("investigation")
        repair_result = attempt.get("repair_result")
        if not isinstance(work_item, dict):
            raise RepairLoopError("attempt missing WorkItem")
        _validate_work_item(work_item)

        if str(work_item["repository"]) != str(root_work_item["repository"]):
            raise RepairLoopError("repair chain repository changed")
        if index == 1:
            if str(work_item["work_item_id"]) != str(root_work_item["work_item_id"]):
                raise RepairLoopError("first repair attempt must use root WorkItem")
            if str(work_item["resolved_sha"]).lower() != str(root_work_item["resolved_sha"]).lower():
                raise RepairLoopError("first repair attempt source identity mismatch")
        else:
            if str(work_item["resolved_sha"]).lower() != previous_repaired_sha:
                raise RepairLoopError("repair chain attempt source does not match prior repaired SHA")
            if str(work_item["work_item_id"]) == str(
                attempts[index - 2]["work_item"]["work_item_id"]
            ):
                raise RepairLoopError("new repaired source requires a new WorkItem identity")

        _validate_investigation(investigation, work_item=work_item)
        identity = _validate_repair_result(
            repair_result,
            work_item=work_item,
            chain_attempt_number=index,
        )

        focused = attempt.get("focused_verification")
        if focused is None:
            if index != len(attempts):
                raise RepairLoopError("later attempt exists before focused verification")
            return {
                **base,
                "state": "NEEDS_FOCUSED_VERIFY",
                "next_action": "RUN_FOCUSED_VERIFY",
                "reason_code": "HUMAN_DECISION_REQUIRED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        focused_status = _validate_focused(
            focused,
            repair_identity_sha256=identity,
        )
        if focused_status == "BLOCKED":
            intelligence = _classify(focused, plan)
            if str(intelligence.get("kind")) in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
                return {
                    **base,
                    "state": "WAITING_EXTERNAL",
                    "next_action": "WAIT_EXTERNAL",
                    "reason_code": "HUMAN_DECISION_REQUIRED",
                    "repair_identity_sha256": identity,
                    "attempt_signatures": signatures,
                }
            return _stop(
                base,
                "VERIFICATION_BLOCKED",
                signatures=signatures,
                repair_identity_sha256=identity,
            )
        if focused_status == "FAIL":
            # A failed focused gate is useful evidence, but v1 stops rather than
            # manufacturing an exact repaired source identity that was never
            # materialized. A future repair must start from a new causal decision.
            return _stop(
                base,
                "HUMAN_DECISION_REQUIRED",
                signatures=signatures,
                repair_identity_sha256=identity,
                focused_failure_signature=failure_signature(focused, plan),
            )
        if focused_status != "PASS":
            raise RepairLoopError("focused verification has unsupported state")

        materialization = attempt.get("materialization")
        if materialization is None:
            if index != len(attempts):
                raise RepairLoopError("later attempt exists before materialization")
            return {
                **base,
                "state": "NEEDS_MATERIALIZATION",
                "next_action": "MATERIALIZE_DRAFT_BRANCH",
                "reason_code": "HUMAN_DECISION_REQUIRED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }
        repaired_sha = _validate_materialization(
            materialization,
            work_item=work_item,
            repair_identity_sha256=identity,
            repair_result=repair_result,
        )
        previous_repaired_sha = repaired_sha

        applab = attempt.get("applab_verification")
        trusted = attempt.get("trusted_evidence")
        if applab is None or trusted is None:
            if index != len(attempts):
                raise RepairLoopError("later attempt exists before trusted AppLab verification")
            mode = "RUN_APPLAB_FULL" if str(plan.get("lane") or "") == "FULL_RUNTIME" else "RUN_APPLAB_FAST"
            return {
                **base,
                "state": "NEEDS_APPLAB_VERIFY",
                "next_action": mode,
                "reason_code": "HUMAN_DECISION_REQUIRED",
                "repaired_source_sha": repaired_sha,
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        try:
            _validate_trusted_runtime(
                applab,
                trusted,
                repository=str(work_item["repository"]),
                repaired_source_sha=repaired_sha,
                contract=contract,
            )
        except RepairLoopError as exc:
            return _stop(
                base,
                "VERIFICATION_NOT_TRUSTED",
                signatures=signatures,
                repaired_source_sha=repaired_sha,
                repair_identity_sha256=identity,
                trust_error=str(exc),
            )

        applab_status = _status(applab)
        if applab_status == "PASS":
            if index != len(attempts):
                raise RepairLoopError("attempt history continues after trusted PASS")
            return {
                **base,
                "state": "COMPLETE",
                "next_action": "NONE",
                "reason_code": "VERIFIED_PASS",
                "repaired_source_sha": repaired_sha,
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
                "observed_verification_result": "PASS",
                "trusted_evidence_producer": trusted.get("producer"),
            }
        if applab_status not in {"FAIL", "BLOCKED"}:
            raise RepairLoopError("trusted AppLab verification has unsupported state")

        decision = _failed_verification_decision(
            base=base,
            result=applab,
            plan=plan,
            initial_class=initial_class,
            attempt_number=index,
            max_attempts=max_attempts,
            signatures=signatures,
            repaired_source_sha=repaired_sha,
            repair_identity_sha256=identity,
        )
        signatures = list(decision.get("attempt_signatures") or signatures)
        if decision["state"] != "NEEDS_INVESTIGATION":
            return decision
        if index == len(attempts):
            return decision

    raise RepairLoopError("unreachable verify-repair loop state")


def _fixture_work_item(
    *,
    work_item_id: str,
    resolved_sha: str,
) -> dict[str, Any]:
    contract = workgraph.load_contract()
    return {
        "schema_version": 1,
        "record_type": "APPLAB_WORK_ITEM",
        "work_item_id": work_item_id,
        "operation_id": "op_" + work_item_id.split("_", 1)[-1],
        "repository": "owner/app",
        "source_ref": "repair",
        "resolved_sha": resolved_sha,
        "baseline_sha": "a" * 40,
        "applab_sha": "c" * 40,
        "risk": "NORMAL",
        "state": "PLANNED",
        "authority": "ORCHESTRATION_ONLY",
        "authority_envelope": {
            "allowed_capabilities": [
                "READ_REPOSITORY",
                "READ_EVIDENCE",
                "RUN_FOCUSED_TESTS",
                "RUN_APPLAB_FAST",
                "ALLOW_CODE_EDIT",
            ],
            "denied_capabilities": list(
                contract["authority_envelope"]["mandatory_denials"]
            ),
        },
        "budgets": {
            "max_files": 5,
            "max_changed_lines": 250,
            "max_repair_attempts": 2,
            "max_agent_actions": 24,
        },
        "acceptance_criteria": ["trusted AppLab PASS"],
        "required_evidence": ["exact repair identity"],
        "rollback": {"strategy": "revert bounded repair delta"},
        "terminal_conditions": list(contract["terminal_conditions"]),
    }


def _investigation(work_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "repository": work_item["repository"],
        "resolved_sha": work_item["resolved_sha"],
        "state": "LOCALIZED",
        "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR",
    }


def _repair(work_item: dict[str, Any], number: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "BOUNDED_FIX_RESULT_V60C",
        "authority": "BRANCH_WORKSPACE_ONLY",
        "state": "READY_FOR_VERIFICATION",
        "repository": work_item["repository"],
        "resolved_sha": work_item["resolved_sha"],
        "work_item_id": work_item["work_item_id"],
        "attempt_number": number,
        "branch": f"applab/repair/{number}",
        "patch_sha256": "1" * 64,
        "result_patch_sha256": str(number) * 64,
        "changed_files": ["lib/fix.dart"],
        "additions": 1,
        "deletions": 1,
        "changed_lines": 2,
    }


def _attempt(
    work_item: dict[str, Any],
    number: int,
    repaired_sha: str,
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    repair = _repair(work_item, number)
    identity = repair_identity(repair)
    payload: dict[str, Any] = {
        "chain_attempt_number": number,
        "work_item": work_item,
        "investigation": _investigation(work_item),
        "repair_result": repair,
        "focused_verification": {
            "status": "PASS",
            "repair_identity_sha256": identity,
        },
        "materialization": {
            "repository": work_item["repository"],
            "parent_sha": work_item["resolved_sha"],
            "repaired_source_sha": repaired_sha,
            "repair_identity_sha256": identity,
            "result_patch_sha256": repair["result_patch_sha256"],
        },
    }
    if result is not None:
        payload["applab_verification"] = {
            "repository": work_item["repository"],
            "resolved_sha": repaired_sha,
            **result,
        }
        payload["trusted_evidence"] = {
            "trusted": True,
            "producer": "trusted-apk-verifier",
            "manifest_sha256": "sha256:" + "f" * 64,
            "file_count": 8,
            "binding": {
                "repository": work_item["repository"],
                "resolved_sha": repaired_sha,
                "workflow_run_id": str(100 + number),
            },
        }
    return payload


def self_test() -> None:
    root = _fixture_work_item(work_item_id="wrk_loop_1", resolved_sha="b" * 40)
    triage = {
        "classification": "BUILD_OR_QUALITY_FAILURE",
        "repository": "owner/app",
        "resolved_sha": root["resolved_sha"],
    }
    first_investigation = _investigation(root)

    start = evaluate_loop(root, triage, first_investigation, [])
    assert start["state"] == "NEEDS_REPAIR"
    assert start["next_attempt_number"] == 1

    repair = _repair(root, 1)
    focused_pending = {
        "chain_attempt_number": 1,
        "work_item": root,
        "investigation": first_investigation,
        "repair_result": repair,
    }
    needs_focused = evaluate_loop(
        root, triage, first_investigation, [focused_pending]
    )
    assert needs_focused["state"] == "NEEDS_FOCUSED_VERIFY"

    focused_pass = dict(focused_pending)
    focused_pass["focused_verification"] = {
        "status": "PASS",
        "repair_identity_sha256": repair_identity(repair),
    }
    needs_materialization = evaluate_loop(
        root, triage, first_investigation, [focused_pass]
    )
    assert needs_materialization["state"] == "NEEDS_MATERIALIZATION"

    attempt1_pass = _attempt(root, 1, "d" * 40, {"result": "PASS"})
    passed = evaluate_loop(
        root, triage, first_investigation, [attempt1_pass]
    )
    assert passed["state"] == "COMPLETE"
    assert passed["observed_verification_result"] == "PASS"

    attempt1_fail = _attempt(
        root,
        1,
        "d" * 40,
        {
            "result": "FAIL",
            "build_error": "unit test failed in lib/fix.dart line 10",
        },
    )
    again = evaluate_loop(
        root, triage, first_investigation, [attempt1_fail]
    )
    assert again["state"] == "NEEDS_INVESTIGATION"
    assert again["next_attempt_number"] == 2
    assert again["next_source_sha"] == "d" * 40

    second_work = _fixture_work_item(
        work_item_id="wrk_loop_2",
        resolved_sha="d" * 40,
    )
    attempt2_same = _attempt(
        second_work,
        2,
        "e" * 40,
        {
            "result": "FAIL",
            "build_error": "unit test failed in lib/fix.dart line 99",
        },
    )
    repeated = evaluate_loop(
        root,
        triage,
        first_investigation,
        [attempt1_fail, attempt2_same],
    )
    assert repeated["state"] == "STOPPED"
    assert repeated["reason_code"] == "REPEATED_FAILURE_SIGNATURE"

    mutated = _attempt(
        second_work,
        2,
        "e" * 40,
        {
            "result": "FAIL",
            "network_lab": "FAIL",
            "reason": "network request failed",
        },
    )
    mutation = evaluate_loop(
        root,
        triage,
        first_investigation,
        [attempt1_fail, mutated],
    )
    assert mutation["reason_code"] == "UNEXPLAINED_FAILURE_MUTATION"

    untrusted = _attempt(root, 1, "d" * 40, {"result": "PASS"})
    untrusted["trusted_evidence"]["trusted"] = False
    stopped = evaluate_loop(root, triage, first_investigation, [untrusted])
    assert stopped["reason_code"] == "VERIFICATION_NOT_TRUSTED"

    print("AppLab v6.0D verify-repair loop self-test PASS")


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RepairLoopError(f"JSON root must be an object: {path}")
    return payload


def _public_cli_projection(report: dict[str, Any]) -> dict[str, Any]:
    state = report.get("state")
    if state == "NEEDS_REPAIR":
        safe_state = "NEEDS_REPAIR"
    elif state == "NEEDS_FOCUSED_VERIFY":
        safe_state = "NEEDS_FOCUSED_VERIFY"
    elif state == "NEEDS_MATERIALIZATION":
        safe_state = "NEEDS_MATERIALIZATION"
    elif state == "NEEDS_APPLAB_VERIFY":
        safe_state = "NEEDS_APPLAB_VERIFY"
    elif state == "NEEDS_INVESTIGATION":
        safe_state = "NEEDS_INVESTIGATION"
    elif state == "WAITING_EXTERNAL":
        safe_state = "WAITING_EXTERNAL"
    elif state == "COMPLETE":
        safe_state = "COMPLETE"
    else:
        safe_state = "STOPPED"

    action = report.get("next_action")
    if action == "APPLY_BOUNDED_REPAIR":
        safe_action = "APPLY_BOUNDED_REPAIR"
    elif action == "RUN_FOCUSED_VERIFY":
        safe_action = "RUN_FOCUSED_VERIFY"
    elif action == "MATERIALIZE_DRAFT_BRANCH":
        safe_action = "MATERIALIZE_DRAFT_BRANCH"
    elif action == "RUN_APPLAB_FAST":
        safe_action = "RUN_APPLAB_FAST"
    elif action == "RUN_APPLAB_FULL":
        safe_action = "RUN_APPLAB_FULL"
    elif action == "INVESTIGATE":
        safe_action = "INVESTIGATE"
    elif action == "WAIT_EXTERNAL":
        safe_action = "WAIT_EXTERNAL"
    else:
        safe_action = "NONE"

    reason = report.get("reason_code")
    if reason == "VERIFIED_PASS":
        safe_reason = "VERIFIED_PASS"
    elif reason == "UNKNOWN_CLASSIFICATION":
        safe_reason = "UNKNOWN_CLASSIFICATION"
    elif reason == "SCOPE_EXCEEDED":
        safe_reason = "SCOPE_EXCEEDED"
    elif reason == "PROTECTED_PATH":
        safe_reason = "PROTECTED_PATH"
    elif reason == "SECURITY_SENSITIVE_SCOPE":
        safe_reason = "SECURITY_SENSITIVE_SCOPE"
    elif reason == "TEST_WEAKENING_REQUIRED":
        safe_reason = "TEST_WEAKENING_REQUIRED"
    elif reason == "REPEATED_FAILURE_SIGNATURE":
        safe_reason = "REPEATED_FAILURE_SIGNATURE"
    elif reason == "UNEXPLAINED_FAILURE_MUTATION":
        safe_reason = "UNEXPLAINED_FAILURE_MUTATION"
    elif reason == "IDENTITY_NOT_PROVEN":
        safe_reason = "IDENTITY_NOT_PROVEN"
    elif reason == "VERIFICATION_NOT_TRUSTED":
        safe_reason = "VERIFICATION_NOT_TRUSTED"
    elif reason == "BUDGET_EXHAUSTED":
        safe_reason = "BUDGET_EXHAUSTED"
    elif reason == "VERIFICATION_BLOCKED":
        safe_reason = "VERIFICATION_BLOCKED"
    else:
        safe_reason = "HUMAN_DECISION_REQUIRED"

    return {
        "schema_version": 1,
        "record_type": "VERIFY_REPAIR_LOOP_PUBLIC_DECISION_V60D",
        "state": safe_state,
        "next_action": safe_action,
        "reason_code": safe_reason,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-work-item", default="")
    parser.add_argument("--triage", default="")
    parser.add_argument("--initial-investigation", default="")
    parser.add_argument("--attempts", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.root_work_item or not args.triage or not args.initial_investigation:
        raise SystemExit(
            "--root-work-item, --triage and --initial-investigation are required"
        )
    attempts_payload = _read_json(args.attempts) if args.attempts else {"attempts": []}
    attempts = attempts_payload.get("attempts")
    if not isinstance(attempts, list):
        raise RepairLoopError("attempts payload must contain a list")
    report = evaluate_loop(
        _read_json(args.root_work_item),
        _read_json(args.triage),
        _read_json(args.initial_investigation),
        attempts,
        plan=_read_json(args.plan) if args.plan else {},
    )
    # CLI output is intentionally a non-sensitive projection. Only
    # hard-coded enum literals are emitted; caller-provided repository/source/
    # evidence values never flow into logs or arbitrary output files.
    public_report = _public_cli_projection(report)
    rendered = json.dumps(public_report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
