#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _work_item_id(record: dict[str, Any]) -> str:
    record_type = str(record.get("record_type") or "")
    if record_type in {"VERIFY_REPAIR_LOOP_DECISION_V60D", "DRAFT_PR_MATERIALIZATION_V60E"}:
        root = str(record.get("root_work_item_id") or "")
        if root:
            return root
    direct = str(record.get("work_item_id") or "")
    if direct:
        return direct
    nested = record.get("work_item")
    if isinstance(nested, dict):
        nested_id = str(nested.get("work_item_id") or "")
        if nested_id:
            return nested_id
    return str(record.get("root_work_item_id") or "")


def _attempt_number(record: dict[str, Any]) -> int:
    try:
        return int(record.get("attempt_number", 0) or 0)
    except (TypeError, ValueError):
        return 0


def build_agent_operations(records: list[dict[str, Any]]) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}

    def ensure(work_item_id: str) -> dict[str, Any]:
        return items.setdefault(
            work_item_id,
            {
                "work_item_id": work_item_id,
                "repository": "",
                "resolved_sha": "",
                "state": "UNKNOWN",
                "risk": "UNKNOWN",
                "attempts": 0,
                "actions": 0,
                "evidence_count": 0,
                "repair_budget": 0,
                "repair_attempts_used": 0,
                "file_budget": 0,
                "line_budget": 0,
                "changed_lines_used": 0,
                "stop_reason": "",
                "next_action": "",
                "pr_state": "",
                "pr_number": None,
                "pr_url": "",
                "authority_envelope": {"allowed_capabilities": [], "denied_capabilities": []},
                "sensor_producers": [],
                "cost": {},
                "runtime": {},
                "record_count": 0,
            },
        )

    for record in records:
        record_type = str(record.get("record_type") or "")
        work_item_id = _work_item_id(record)
        if not work_item_id:
            continue
        item = ensure(work_item_id)
        item["record_count"] += 1

        repository = str(record.get("repository") or "")
        resolved_sha = str(record.get("resolved_sha") or record.get("root_resolved_sha") or "")
        if repository:
            item["repository"] = repository
        if resolved_sha:
            item["resolved_sha"] = resolved_sha

        if record_type == "APPLAB_WORK_ITEM":
            item["state"] = str(record.get("current_state") or record.get("state") or item["state"])
            item["risk"] = str(record.get("risk") or item["risk"])
            budgets = record.get("budgets") if isinstance(record.get("budgets"), dict) else {}
            item["repair_budget"] = int(budgets.get("max_repair_attempts", 0) or 0)
            item["file_budget"] = int(budgets.get("max_files", 0) or 0)
            item["line_budget"] = int(budgets.get("max_changed_lines", 0) or 0)
            envelope = record.get("authority_envelope")
            if isinstance(envelope, dict):
                item["authority_envelope"] = {
                    "allowed_capabilities": list(envelope.get("allowed_capabilities") or []),
                    "denied_capabilities": list(envelope.get("denied_capabilities") or []),
                }

        elif record_type == "APPLAB_WORK_TRANSITION":
            item["state"] = str(record.get("to_state") or item["state"])

        elif record_type == "APPLAB_WORK_ACTION":
            item["actions"] += 1

        elif record_type == "APPLAB_ATTEMPT":
            item["attempts"] = max(item["attempts"], _attempt_number(record))

        elif record_type == "APPLAB_EVIDENCE_REF":
            item["evidence_count"] += 1

        elif record_type == "BOUNDED_FIX_RESULT_V60C":
            attempt = _attempt_number(record)
            item["repair_attempts_used"] = max(item["repair_attempts_used"], attempt)
            item["changed_lines_used"] += int(record.get("changed_lines", 0) or 0)
            item["state"] = str(record.get("state") or item["state"])

        elif record_type == "VERIFY_REPAIR_LOOP_DECISION_V60D":
            item["state"] = str(record.get("state") or item["state"])
            item["stop_reason"] = str(record.get("reason_code") or "")
            item["next_action"] = str(record.get("next_action") or "")
            item["repair_attempts_used"] = max(
                item["repair_attempts_used"],
                int(record.get("repair_attempt_count", 0) or 0),
            )

        elif record_type in {
            "AUTONOMOUS_PR_STEWARD_PLAN_V60E",
            "AUTONOMOUS_PR_STEWARD_RESULT_V60E",
            "DRAFT_PR_MATERIALIZATION_V60E",
        }:
            item["pr_state"] = str(record.get("state") or "")
            number = record.get("pr_number", record.get("pull_request_number"))
            item["pr_number"] = int(number) if isinstance(number, int) else item["pr_number"]
            item["pr_url"] = str(
                record.get("pr_url") or record.get("pull_request_url") or item["pr_url"]
            )
            item["next_action"] = str(record.get("next_action") or item["next_action"])

        elif record_type == "SENSOR_MESH_EVIDENCE_V60H":
            producer = str(record.get("producer") or "")
            if producer and producer not in item["sensor_producers"]:
                item["sensor_producers"].append(producer)
            item["evidence_count"] += 1

        cost = record.get("cost")
        if isinstance(cost, dict):
            item["cost"].update(cost)
        runtime = record.get("runtime")
        if isinstance(runtime, dict):
            item["runtime"].update(runtime)

    ordered = sorted(
        items.values(),
        key=lambda row: (
            row["state"] in {"COMPLETE", "STOPPED", "BLOCKED"},
            row["repository"],
            row["work_item_id"],
        ),
    )
    for item in ordered:
        item["sensor_producers"] = sorted(item["sensor_producers"])
        item["budget"] = {
            "repair_attempts": {
                "used": item.pop("repair_attempts_used"),
                "max": item.pop("repair_budget"),
            },
            "files": {"max": item.pop("file_budget")},
            "changed_lines": {
                "used": item.pop("changed_lines_used"),
                "max": item.pop("line_budget"),
            },
        }

    active = sum(
        1 for row in ordered if row["state"] not in {"COMPLETE", "STOPPED", "BLOCKED"}
    )
    complete = sum(1 for row in ordered if row["state"] == "COMPLETE")
    stopped = sum(1 for row in ordered if row["state"] in {"STOPPED", "BLOCKED"})
    draft_prs = sum(1 for row in ordered if row["pr_state"] in {"DRAFT_PR_CREATED", "DRAFT_PR_UPDATED"})

    return {
        "schema_version": 1,
        "record_type": "AGENTIC_OPERATIONS_STUDIO_V60I",
        "authority": "READ_ONLY_PROJECTION",
        "available": bool(ordered),
        "summary": {
            "work_items": len(ordered),
            "active": active,
            "complete": complete,
            "stopped_or_blocked": stopped,
            "draft_prs": draft_prs,
            "evidence_records": sum(int(row["evidence_count"]) for row in ordered),
        },
        "work_items": ordered[:100],
        "source_of_truth": "DURABLE_BRAIN_AND_EVIDENCE_RECORDS",
        "merge_authority": "NONE",
        "release_authority": "NONE",
    }


def self_test() -> None:
    records = [
        {
            "record_type": "APPLAB_WORK_ITEM",
            "work_item_id": "wrk_1",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "state": "PLANNED",
            "risk": "NORMAL",
            "budgets": {
                "max_repair_attempts": 2,
                "max_files": 5,
                "max_changed_lines": 250,
            },
            "authority_envelope": {
                "allowed_capabilities": ["ALLOW_CODE_EDIT"],
                "denied_capabilities": ["SELF_MERGE", "RELEASE"],
            },
        },
        {
            "record_type": "BOUNDED_FIX_RESULT_V60C",
            "work_item_id": "wrk_1",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "attempt_number": 1,
            "state": "READY_FOR_VERIFICATION",
            "changed_lines": 12,
        },
        {
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "work_item_id": "wrk_1",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "state": "COMPLETE",
            "reason_code": "VERIFIED_PASS",
            "next_action": "OPEN_DRAFT_PR",
            "repair_attempt_count": 1,
        },
        {
            "record_type": "AUTONOMOUS_PR_STEWARD_RESULT_V60E",
            "work_item_id": "wrk_1",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "state": "DRAFT_PR_CREATED",
            "pull_request_number": 123,
            "pull_request_url": "https://example.test/pr/123",
        },
        {
            "record_type": "SENSOR_MESH_EVIDENCE_V60H",
            "work_item_id": "wrk_1",
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "producer": "SEMGREP",
        },
    ]
    snapshot = build_agent_operations(records)
    assert snapshot["available"] is True
    assert snapshot["summary"]["work_items"] == 1
    assert snapshot["summary"]["complete"] == 1
    assert snapshot["summary"]["draft_prs"] == 1
    row = snapshot["work_items"][0]
    assert row["budget"]["repair_attempts"] == {"used": 1, "max": 2}
    assert row["budget"]["changed_lines"] == {"used": 12, "max": 250}
    assert row["pr_number"] == 123
    assert row["sensor_producers"] == ["SEMGREP"]
    assert snapshot["merge_authority"] == "NONE"
    print("AppLab v6.0I agent operations snapshot self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    records = read_jsonl(Path(args.records)) if args.records else []
    snapshot = build_agent_operations(records)
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
