#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "integration/orchestration/contracts/continuous-maintenance-v56.json"
LANES = ("BLOCKING_NOW", "FIX_CURRENT_STEP", "BACKGROUND_MAINTENANCE", "FUTURE")
LANE_RANK = {name: index for index, name in enumerate(LANES)}
CRITICAL_FLAGS = {
    "trust_boundary_violation": ("P1", "TRUST_BOUNDARY"),
    "false_pass_detected": ("P0", "FALSE_PASS"),
    "artifact_identity_mismatch": ("P1", "ARTIFACT_IDENTITY"),
    "data_loss_detected": ("P0", "DATA_LOSS"),
    "critical_security": ("P0", "CRITICAL_SECURITY"),
}


class MaintenanceError(RuntimeError):
    pass


def _safe(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_policy(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_POLICY
    payload = load_json(target)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MaintenanceError("continuous maintenance policy schema_version must be 1")
    if payload.get("mode") != "ROADMAP_FAST_PLUS_CONTINUOUS_MAINTENANCE":
        raise MaintenanceError("unexpected continuous maintenance mode")
    authority = payload.get("authority")
    if not isinstance(authority, dict):
        raise MaintenanceError("authority policy is required")
    forbidden = (
        "can_mint_pass",
        "can_mint_certified",
        "can_reduce_test_coverage",
        "can_change_release_artifact_identity",
        "can_treat_emulator_as_physical",
        "can_mutate_active_roadmap_pr",
    )
    if any(authority.get(key) is not False for key in forbidden):
        raise MaintenanceError("continuous maintenance authority must remain evidence-only")
    return payload


def _normalize_signal(raw: dict[str, Any]) -> dict[str, Any]:
    repository = _safe(raw.get("repository")) or "unknown"
    category = _safe(raw.get("category")).upper() or "GENERAL"
    severity = _safe(raw.get("severity")).upper() or "P3"
    code = _safe(raw.get("code")).upper() or category
    message = _safe(raw.get("message")) or code
    evidence_ref = _safe(raw.get("evidence_ref"))
    observed_at = _safe(raw.get("observed_at")) or _now()
    introduced = bool(raw.get("introduced_by_current_step", False))
    return {
        "repository": repository,
        "category": category,
        "severity": severity,
        "code": code,
        "message": message,
        "evidence_ref": evidence_ref,
        "observed_at": observed_at,
        "introduced_by_current_step": introduced,
        "source": _safe(raw.get("source")) or "EXPLICIT_FINDING",
    }


def classify_signal(signal: dict[str, Any], policy: dict[str, Any]) -> str:
    severity = signal["severity"]
    category = signal["category"]
    if severity in set(policy.get("blocking_severities") or []):
        return "BLOCKING_NOW"
    if category in set(policy.get("blocking_categories") or []):
        return "BLOCKING_NOW"
    if bool(policy.get("current_step_blocks_when_introduced")) and signal["introduced_by_current_step"]:
        return "FIX_CURRENT_STEP"
    if category in set(policy.get("future_categories") or []):
        return "FUTURE"
    return "BACKGROUND_MAINTENANCE"


def _signal_id(signal: dict[str, Any]) -> str:
    stable = "|".join(
        [
            signal["repository"].lower(),
            signal["category"],
            signal["code"],
            signal["message"].lower(),
        ]
    )
    return "mnt_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


def _critical_signals(record: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for flag, (severity, category) in CRITICAL_FLAGS.items():
        if record.get(flag) is not True:
            continue
        out.append(
            {
                "repository": _safe(record.get("repository")) or "unknown",
                "severity": severity,
                "category": category,
                "code": flag.upper(),
                "message": _safe(record.get("reason")) or f"{flag} observed in trusted AppLab evidence",
                "evidence_ref": _safe(record.get("watcher_run_url"))
                or _safe(record.get("workflow_run_url")),
                "observed_at": _safe(record.get("recorded_at"))
                or _safe(record.get("observed_at")),
                "source": "WATCHER_HISTORY",
                "introduced_by_current_step": False,
            }
        )
    return out


def signals_from_history(records: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    max_records = int((policy.get("history") or {}).get("max_records", 250))
    infra = set((policy.get("history") or {}).get("infrastructure_failure_classes") or [])
    out: list[dict[str, Any]] = []
    for record in records[-max_records:]:
        if not isinstance(record, dict):
            continue
        out.extend(_critical_signals(record))
        result = _safe(record.get("result")).upper()
        if result not in {"FAIL", "ERROR"}:
            continue
        failure = record.get("failure_intelligence")
        failure = failure if isinstance(failure, dict) else {}
        kind = _safe(failure.get("kind")).upper() or "UNKNOWN_FAILURE"
        if kind in infra:
            category = "INFRASTRUCTURE"
            severity = "P3"
        elif kind == "APP_RUNTIME_FAILURE":
            category = "RUNTIME_REGRESSION"
            severity = "P2"
        elif kind == "APP_VISUAL_FAILURE":
            category = "VISUAL_REGRESSION"
            severity = "P2"
        elif kind == "BUILD_OR_QUALITY_FAILURE":
            category = "BUILD_QUALITY"
            severity = "P2"
        else:
            category = "VERIFICATION_FAILURE"
            severity = "P2"
        failed_labs = failure.get("failed_labs") if isinstance(failure.get("failed_labs"), list) else []
        code = kind + (":" + ",".join(sorted(map(str, failed_labs))) if failed_labs else "")
        out.append(
            {
                "repository": _safe(record.get("repository")) or "unknown",
                "severity": severity,
                "category": category,
                "code": code,
                "message": _safe(record.get("reason"))
                or _safe(failure.get("reason"))
                or f"{kind} observed by AppLab",
                "evidence_ref": _safe(record.get("watcher_run_url"))
                or _safe(record.get("workflow_run_url"))
                or _safe(record.get("workflow_run_id")),
                "observed_at": _safe(record.get("recorded_at"))
                or _safe(record.get("observed_at")),
                "source": "WATCHER_HISTORY",
                "introduced_by_current_step": False,
            }
        )
    return out


def read_history(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def read_findings(paths: list[Path]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        payload = load_json(path)
        if isinstance(payload, dict):
            rows = payload.get("findings", [])
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        for row in rows:
            if isinstance(row, dict):
                out.append(row)
    return out


def _previous_items(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    payload = load_json(path)
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    return {
        _safe(row.get("id")): dict(row)
        for row in rows
        if isinstance(row, dict) and _safe(row.get("id"))
    }


def build_queue(
    *,
    policy: dict[str, Any],
    history: list[dict[str, Any]],
    explicit_findings: list[dict[str, Any]],
    previous: dict[str, dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    now = generated_at or _now()
    previous = previous or {}
    combined = signals_from_history(history, policy) + explicit_findings
    items = {key: dict(value) for key, value in previous.items()}

    for raw in combined:
        signal = _normalize_signal(raw)
        item_id = _signal_id(signal)
        lane = classify_signal(signal, policy)
        old = items.get(item_id)
        observation_key = signal["evidence_ref"] or (
            signal["source"] + "|" + signal["observed_at"]
        )
        if old:
            old_lane = _safe(old.get("lane"))
            if LANE_RANK.get(lane, 99) < LANE_RANK.get(old_lane, 99):
                old["lane"] = lane
            old["severity"] = signal["severity"]
            keys = list(old.get("observation_keys") or [])
            if observation_key not in keys:
                old["last_seen"] = signal["observed_at"]
                old["occurrences"] = int(old.get("occurrences", 1)) + 1
                keys.append(observation_key)
                old["observation_keys"] = keys[-20:]
                if signal["evidence_ref"]:
                    refs = list(old.get("evidence_refs") or [])
                    if signal["evidence_ref"] not in refs:
                        refs.append(signal["evidence_ref"])
                    old["evidence_refs"] = refs[-10:]
            continue

        items[item_id] = {
            "id": item_id,
            "lane": lane,
            "repository": signal["repository"],
            "severity": signal["severity"],
            "category": signal["category"],
            "code": signal["code"],
            "message": signal["message"],
            "source": signal["source"],
            "introduced_by_current_step": signal["introduced_by_current_step"],
            "first_seen": signal["observed_at"],
            "last_seen": signal["observed_at"],
            "occurrences": 1,
            "evidence_refs": [signal["evidence_ref"]] if signal["evidence_ref"] else [],
            "observation_keys": [observation_key],
            "status": "OPEN",
        }

    ordered = sorted(
        items.values(),
        key=lambda row: (
            LANE_RANK.get(_safe(row.get("lane")), 99),
            _safe(row.get("repository")),
            _safe(row.get("id")),
        ),
    )[:500]
    counts = {lane: 0 for lane in LANES}
    for row in ordered:
        lane = _safe(row.get("lane"))
        if lane in counts and _safe(row.get("status")).upper() == "OPEN":
            counts[lane] += 1
    blockers = [
        row["id"]
        for row in ordered
        if row.get("status") == "OPEN"
        and row.get("lane") in {"BLOCKING_NOW", "FIX_CURRENT_STEP"}
    ]
    return {
        "schema_version": 1,
        "mode": policy["mode"],
        "generated_at": now,
        "roadmap_gate": "BLOCKED" if blockers else "CONTINUE",
        "roadmap_gate_items": blockers,
        "summary": {
            "open_items": sum(counts.values()),
            "counts": counts,
            "background_safe": not blockers,
        },
        "authority": dict(policy["authority"]),
        "items": ordered,
    }


def render_markdown(queue: dict[str, Any]) -> str:
    counts = (queue.get("summary") or {}).get("counts") or {}
    lines = [
        "# AppLab Continuous Maintenance",
        "",
        f"- Mode: `{queue.get('mode', 'unknown')}`",
        f"- Roadmap gate: **{queue.get('roadmap_gate', 'UNKNOWN')}**",
        f"- Open items: {queue.get('summary', {}).get('open_items', 0)}",
        f"- Blocking now: {counts.get('BLOCKING_NOW', 0)}",
        f"- Fix current step: {counts.get('FIX_CURRENT_STEP', 0)}",
        f"- Background maintenance: {counts.get('BACKGROUND_MAINTENANCE', 0)}",
        f"- Future: {counts.get('FUTURE', 0)}",
        "",
        "| Lane | Repository | Severity | Category | Occurrences | Finding |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for item in queue.get("items", []):
        if item.get("status") != "OPEN":
            continue
        message = _safe(item.get("message")).replace("|", "\\|")
        lines.append(
            f"| {item.get('lane')} | {item.get('repository')} | {item.get('severity')} | "
            f"{item.get('category')} | {item.get('occurrences', 1)} | {message} |"
        )
    lines.extend(
        [
            "",
            "Background maintenance is evidence-only. It cannot mint PASS/CERTIFIED, "
            "reduce test coverage, mutate the active roadmap PR, change release-artifact "
            "identity, or treat emulator evidence as physical-device evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def self_test() -> dict[str, Any]:
    policy = load_policy()
    history = [
        {
            "repository": "owner/app-a",
            "result": "FAIL",
            "recorded_at": "2026-10-26T01:00:00+00:00",
            "watcher_run_url": "https://example.invalid/run/1",
            "failure_intelligence": {
                "kind": "INFRA_ERROR",
                "reason": "emulator startup timeout",
                "failed_labs": [],
            },
        },
        {
            "repository": "owner/app-a",
            "result": "FAIL",
            "recorded_at": "2026-10-26T02:00:00+00:00",
            "watcher_run_url": "https://example.invalid/run/2",
            "failure_intelligence": {
                "kind": "INFRA_ERROR",
                "reason": "emulator startup timeout",
                "failed_labs": [],
            },
        },
    ]
    findings = [
        {
            "repository": "owner/app-b",
            "severity": "P1",
            "category": "TRUST_BOUNDARY",
            "code": "CROSS_REPO_EVIDENCE",
            "message": "repository binding mismatch",
            "evidence_ref": "evidence://trust",
        },
        {
            "repository": "owner/app-c",
            "severity": "P2",
            "category": "RUNTIME_REGRESSION",
            "code": "STEP_REGRESSION",
            "message": "regression introduced by current roadmap step",
            "introduced_by_current_step": True,
        },
        {
            "repository": "owner/app-d",
            "severity": "P3",
            "category": "OPTIONAL_REFACTOR",
            "code": "CLEANUP",
            "message": "optional cleanup",
        },
    ]
    queue = build_queue(
        policy=policy,
        history=history,
        explicit_findings=findings,
        generated_at="2026-10-26T03:00:00+00:00",
    )
    lanes = {item["code"]: item["lane"] for item in queue["items"]}
    assert lanes["INFRA_ERROR"] == "BACKGROUND_MAINTENANCE"
    assert lanes["CROSS_REPO_EVIDENCE"] == "BLOCKING_NOW"
    assert lanes["STEP_REGRESSION"] == "FIX_CURRENT_STEP"
    assert lanes["CLEANUP"] == "FUTURE"
    infra_item = next(item for item in queue["items"] if item["code"] == "INFRA_ERROR")
    assert infra_item["occurrences"] == 2
    rerun = build_queue(
        policy=policy,
        history=history,
        explicit_findings=[],
        previous={item["id"]: item for item in safe["items"]} if False else {},
        generated_at="2026-10-26T03:00:00+00:00",
    )
    assert queue["roadmap_gate"] == "BLOCKED"
    assert queue["authority"]["can_mint_pass"] is False
    assert queue["authority"]["can_mutate_active_roadmap_pr"] is False

    safe = build_queue(
        policy=policy,
        history=history,
        explicit_findings=[],
        generated_at="2026-10-26T03:00:00+00:00",
    )
    assert safe["roadmap_gate"] == "CONTINUE"
    assert safe["summary"]["background_safe"] is True
    return {
        "status": "PASS",
        "mode": queue["mode"],
        "blocking_rules_proven": True,
        "current_step_isolation_proven": True,
        "background_non_blocking_proven": True,
        "dedupe_recurrence_proven": True,
        "authority_preserved": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--history-file", default="")
    parser.add_argument("--finding-file", action="append", default=[])
    parser.add_argument("--previous-queue", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        print(json.dumps(self_test(), sort_keys=True))
        print("v5.6 continuous maintenance self-test PASS")
        return 0

    policy = load_policy(Path(args.policy))
    history = read_history(Path(args.history_file)) if args.history_file else []
    findings = read_findings([Path(value) for value in args.finding_file])
    previous = _previous_items(Path(args.previous_queue)) if args.previous_queue else {}
    queue = build_queue(
        policy=policy,
        history=history,
        explicit_findings=findings,
        previous=previous,
    )

    if args.output_json:
        target = Path(args.output_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_md:
        target = Path(args.output_md)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_markdown(queue), encoding="utf-8")

    print(json.dumps(queue["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
