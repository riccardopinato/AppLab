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


class RepairLoopError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RepairLoopError("unsupported verify-repair loop contract version")
    if payload.get("contract_name") != "APPLAB_VERIFY_REPAIR_LOOP":
        raise RepairLoopError("unexpected verify-repair loop contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise RepairLoopError("verify-repair loop authority must remain orchestration-only")
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
    return text[:400]


def _classify(result: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    existing = result.get("failure_intelligence")
    if isinstance(existing, dict) and existing.get("kind"):
        return existing
    return verification_intelligence.classify_failure(result, plan)


def failure_signature(
    result: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    classification = _classify(result, plan)
    kind = str(classification.get("kind", "UNKNOWN_FAILURE"))
    failed_labs = sorted(
        str(value) for value in classification.get("failed_labs", []) if str(value)
    )
    reason_parts = [
        classification.get("reason", ""),
        result.get("reason", ""),
        result.get("build_error", ""),
        result.get("error", ""),
    ]
    normalized = _normalize_reason(" ".join(str(x or "") for x in reason_parts))
    payload = {
        "classification": kind,
        "failed_labs": failed_labs,
        "normalized_reason": normalized,
    }
    return {
        **payload,
        "signature_sha256": _sha256(payload),
    }


def repair_identity(manifest: dict[str, Any]) -> str:
    files = []
    for raw in manifest.get("files", []) if isinstance(manifest.get("files"), list) else []:
        if not isinstance(raw, dict):
            continue
        files.append(
            {
                "path": str(raw.get("path") or ""),
                "created": bool(raw.get("created")),
                "changed_lines": int(raw.get("changed_lines", 0) or 0),
                "before_sha256": raw.get("before_sha256"),
                "after_sha256": raw.get("after_sha256"),
            }
        )
    stable = {
        "repository": str(manifest.get("repository") or ""),
        "resolved_sha": str(manifest.get("resolved_sha") or "").lower(),
        "work_item_id": str(manifest.get("work_item_id") or ""),
        "attempt_number": int(manifest.get("attempt_number", 0) or 0),
        "total_changed_lines": int(manifest.get("total_changed_lines", 0) or 0),
        "files": sorted(files, key=lambda row: row["path"]),
    }
    return _sha256(stable)


def _validate_work_item(work_item: dict[str, Any]) -> int:
    workgraph.validate_work_item(work_item, workgraph.load_contract())
    budget = int((work_item.get("budgets") or {}).get("max_repair_attempts", 0) or 0)
    if budget < 1:
        raise RepairLoopError("WorkItem has no repair attempt budget")
    return budget


def _identity_matches(
    work_item: dict[str, Any],
    payload: dict[str, Any],
    label: str,
) -> None:
    if str(payload.get("repository") or "") != str(work_item.get("repository") or ""):
        raise RepairLoopError(f"{label} repository identity mismatch")
    source = str(payload.get("resolved_sha") or "").lower()
    if source and source != str(work_item.get("resolved_sha") or "").lower():
        raise RepairLoopError(f"{label} source identity mismatch")


def _repair_attempt(
    work_item: dict[str, Any],
    attempt: dict[str, Any],
    expected_number: int,
) -> tuple[dict[str, Any], str]:
    if not isinstance(attempt, dict):
        raise RepairLoopError("attempt history item must be an object")
    number = attempt.get("attempt_number")
    if number != expected_number:
        raise RepairLoopError("attempt history must be contiguous and ordered")
    manifest = attempt.get("repair_manifest")
    if not isinstance(manifest, dict):
        raise RepairLoopError("attempt missing repair_manifest")
    if manifest.get("state") != "APPLIED_IN_ISOLATED_WORKSPACE":
        raise RepairLoopError("attempt repair_manifest is not an applied bounded repair")
    _identity_matches(work_item, manifest, "repair_manifest")
    if str(manifest.get("work_item_id") or "") != str(work_item.get("work_item_id") or ""):
        raise RepairLoopError("repair_manifest WorkItem identity mismatch")
    if int(manifest.get("attempt_number", 0) or 0) != expected_number:
        raise RepairLoopError("repair_manifest attempt number mismatch")
    identity = repair_identity(manifest)
    return manifest, identity


def _verification_status(payload: Any) -> str:
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


def _base_report(
    work_item: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
        "authority": "ORCHESTRATION_ONLY",
        "repository": str(work_item.get("repository") or ""),
        "resolved_sha": str(work_item.get("resolved_sha") or ""),
        "work_item_id": str(work_item.get("work_item_id") or ""),
        "repair_attempt_count": len(attempts),
        "merge_authority": "DENIED",
        "release_authority": "DENIED",
        "verification_authority": "OBSERVE_EXISTING_APPLAB_ONLY",
    }


def evaluate_loop(
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
    work_budget = _validate_work_item(work_item)
    max_attempts = min(work_budget, int(contract["max_repair_attempts"]))
    base = _base_report(work_item, attempts)

    initial_class = str(initial_triage.get("classification", "UNKNOWN_FAILURE"))
    if initial_class == "UNKNOWN_FAILURE":
        return {
            **base,
            "state": "STOPPED",
            "next_action": "NONE",
            "reason_code": "UNKNOWN_CLASSIFICATION",
            "attempt_signatures": [],
        }
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
        }
    if investigation.get("state") != "LOCALIZED":
        return {
            **base,
            "state": "NEEDS_INVESTIGATION",
            "next_action": "INVESTIGATE",
            "reason_code": "HUMAN_DECISION_REQUIRED",
            "attempt_signatures": [],
        }
    if investigation.get("edit_recommendation") != "ELIGIBLE_FOR_BOUNDED_REPAIR":
        return {
            **base,
            "state": "STOPPED",
            "next_action": "NONE",
            "reason_code": "HUMAN_DECISION_REQUIRED",
            "attempt_signatures": [],
        }

    if len(attempts) > max_attempts:
        raise RepairLoopError("attempt history exceeds repair budget")
    if not attempts:
        return {
            **base,
            "state": "NEEDS_REPAIR",
            "next_action": "APPLY_BOUNDED_REPAIR",
            "reason_code": "HUMAN_DECISION_REQUIRED",
            "next_attempt_number": 1,
            "attempt_signatures": [],
        }

    signatures: list[dict[str, Any]] = []
    prior_failure_class = ""
    prior_failure_signature = ""

    for index, attempt in enumerate(attempts, start=1):
        _, identity = _repair_attempt(work_item, attempt, index)
        focused = attempt.get("focused_verification")
        focused_status = _verification_status(focused)
        if focused_status == "BLOCKED":
            return {
                **base,
                "state": "STOPPED",
                "next_action": "NONE",
                "reason_code": "VERIFICATION_BLOCKED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }
        if focused_status in {"NOT_VERIFIED", "FAIL"}:
            if index != len(attempts):
                raise RepairLoopError("later attempt exists before focused verification resolved")
            return {
                **base,
                "state": "NEEDS_FOCUSED_VERIFY",
                "next_action": "RUN_FOCUSED_VERIFY",
                "reason_code": "HUMAN_DECISION_REQUIRED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        applab = attempt.get("applab_verification")
        applab_status = _verification_status(applab)
        if applab_status == "NOT_VERIFIED":
            if index != len(attempts):
                raise RepairLoopError("later attempt exists before AppLab verification resolved")
            return {
                **base,
                "state": "NEEDS_APPLAB_VERIFY",
                "next_action": "RUN_APPLAB_FAST",
                "reason_code": "HUMAN_DECISION_REQUIRED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        if not isinstance(applab, dict):
            raise RepairLoopError("AppLab verification payload must be an object")
        _identity_matches(work_item, applab, "applab_verification")
        bound_identity = str(applab.get("repair_identity_sha256") or "")
        if bound_identity != identity:
            return {
                **base,
                "state": "STOPPED",
                "next_action": "NONE",
                "reason_code": "IDENTITY_NOT_PROVEN",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        if applab_status == "PASS":
            if index != len(attempts):
                raise RepairLoopError("attempt history continues after verified PASS")
            return {
                **base,
                "state": "COMPLETE",
                "next_action": "OPEN_DRAFT_PR",
                "reason_code": "VERIFIED_PASS",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
                "observed_verification_result": "PASS",
            }

        if applab_status == "BLOCKED":
            intelligence = _classify(applab, plan)
            if str(intelligence.get("kind")) in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
                return {
                    **base,
                    "state": "WAITING_EXTERNAL",
                    "next_action": "WAIT_EXTERNAL",
                    "reason_code": "HUMAN_DECISION_REQUIRED",
                    "repair_identity_sha256": identity,
                    "attempt_signatures": signatures,
                }
            return {
                **base,
                "state": "STOPPED",
                "next_action": "NONE",
                "reason_code": "VERIFICATION_BLOCKED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        signature = failure_signature(applab, plan)
        signatures.append({"attempt_number": index, **signature})
        failure_class = signature["classification"]
        if failure_class == "UNKNOWN_FAILURE":
            return {
                **base,
                "state": "STOPPED",
                "next_action": "NONE",
                "reason_code": "UNKNOWN_CLASSIFICATION",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }
        if failure_class in {"INFRA_ERROR", "FLAKY_SUSPECT"}:
            return {
                **base,
                "state": "WAITING_EXTERNAL",
                "next_action": "WAIT_EXTERNAL",
                "reason_code": "HUMAN_DECISION_REQUIRED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        if prior_failure_class and failure_class != prior_failure_class:
            return {
                **base,
                "state": "STOPPED",
                "next_action": "NONE",
                "reason_code": "UNEXPLAINED_FAILURE_MUTATION",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }
        if (
            index >= 2
            and prior_failure_signature
            and signature["signature_sha256"] == prior_failure_signature
        ):
            return {
                **base,
                "state": "STOPPED",
                "next_action": "NONE",
                "reason_code": "REPEATED_FAILURE_SIGNATURE",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

        prior_failure_class = failure_class
        prior_failure_signature = signature["signature_sha256"]

        if index >= max_attempts:
            return {
                **base,
                "state": "STOPPED",
                "next_action": "NONE",
                "reason_code": "BUDGET_EXHAUSTED",
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }
        if index == len(attempts):
            return {
                **base,
                "state": "NEEDS_INVESTIGATION",
                "next_action": "INVESTIGATE",
                "reason_code": "HUMAN_DECISION_REQUIRED",
                "next_attempt_number": index + 1,
                "repair_identity_sha256": identity,
                "attempt_signatures": signatures,
            }

    raise RepairLoopError("unreachable verify-repair state")


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
        "rollback": {"strategy": "revert bounded delta"},
        "terminal_conditions": list(contract["terminal_conditions"]),
    }


def _manifest(number: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "BOUNDED_REPAIR_PREPARED_V60C",
        "authority": "BOUNDED_WORKSPACE_EDIT_ONLY",
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "work_item_id": "wrk_loop",
        "attempt_number": number,
        "branch": f"applab-repair/attempt-{number}",
        "total_changed_lines": 2,
        "state": "APPLIED_IN_ISOLATED_WORKSPACE",
        "files": [
            {
                "path": "lib/fix.dart",
                "created": False,
                "changed_lines": 2,
                "before_sha256": "sha256:" + "1" * 64,
                "after_sha256": "sha256:" + str(number) * 64,
            }
        ],
    }


def _attempt(number: int, result: dict[str, Any] | None) -> dict[str, Any]:
    manifest = _manifest(number)
    identity = repair_identity(manifest)
    payload = {
        "attempt_number": number,
        "repair_manifest": manifest,
        "focused_verification": {"status": "PASS"},
    }
    if result is not None:
        payload["applab_verification"] = {
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "repair_identity_sha256": identity,
            **result,
        }
    return payload


def self_test() -> None:
    work_item = _fixture_work_item()
    triage = {
        "classification": "BUILD_OR_QUALITY_FAILURE",
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
    }
    investigation = {
        "state": "LOCALIZED",
        "edit_recommendation": "ELIGIBLE_FOR_BOUNDED_REPAIR",
    }

    start = evaluate_loop(work_item, triage, investigation, [])
    assert start["state"] == "NEEDS_REPAIR"
    assert start["next_attempt_number"] == 1

    needs_app = evaluate_loop(
        work_item,
        triage,
        investigation,
        [_attempt(1, None)],
    )
    assert needs_app["state"] == "NEEDS_APPLAB_VERIFY"

    passed = evaluate_loop(
        work_item,
        triage,
        investigation,
        [_attempt(1, {"result": "PASS", "runtime_result": "PASS"})],
    )
    assert passed["state"] == "COMPLETE"
    assert passed["next_action"] == "OPEN_DRAFT_PR"
    assert passed["observed_verification_result"] == "PASS"

    fail_one = _attempt(
        1,
        {
            "result": "FAIL",
            "build_error": "unit test failed in lib/fix.dart line 10",
        },
    )
    again = evaluate_loop(work_item, triage, investigation, [fail_one])
    assert again["state"] == "NEEDS_INVESTIGATION"
    assert again["next_attempt_number"] == 2

    fail_two_same = _attempt(
        2,
        {
            "result": "FAIL",
            "build_error": "unit test failed in lib/fix.dart line 99",
        },
    )
    repeated = evaluate_loop(
        work_item, triage, investigation, [fail_one, fail_two_same]
    )
    assert repeated["state"] == "STOPPED"
    assert repeated["reason_code"] == "REPEATED_FAILURE_SIGNATURE"

    mutated = _attempt(
        2,
        {
            "result": "FAIL",
            "network_lab": "FAIL",
            "reason": "network request failed",
        },
    )
    mutation = evaluate_loop(work_item, triage, investigation, [fail_one, mutated])
    assert mutation["state"] == "STOPPED"
    assert mutation["reason_code"] == "UNEXPLAINED_FAILURE_MUTATION"

    unknown = evaluate_loop(
        work_item,
        {**triage, "classification": "UNKNOWN_FAILURE"},
        investigation,
        [],
    )
    assert unknown["reason_code"] == "UNKNOWN_CLASSIFICATION"

    bad_identity = _attempt(1, {"result": "PASS"})
    bad_identity["applab_verification"]["repair_identity_sha256"] = "sha256:" + "0" * 64
    identity_stop = evaluate_loop(
        work_item, triage, investigation, [bad_identity]
    )
    assert identity_stop["reason_code"] == "IDENTITY_NOT_PROVEN"

    print("AppLab v6.0D verify-repair loop self-test PASS")


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RepairLoopError(f"JSON root must be object: {path}")
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
        raise RepairLoopError("attempts payload must contain a list")
    report = evaluate_loop(
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
