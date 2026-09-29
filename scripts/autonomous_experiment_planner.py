#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from product_review_common import write_report

SCHEMA_VERSION = 1
ENGINE_VERSION = "3.6.0"

PRIORITY_ORDER = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
SOURCE_ORDER = {
    "FIX_NOW": 0,
    "LONGITUDINAL_REGRESSION": 1,
    "EVIDENCE_CONTRADICTION": 2,
    "VERIFY_NEXT": 3,
}

RUNTIME_LABS = {
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
JOURNEY_LABS = {"safe-interaction-crawler", "visual-journey"}


def _safe(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_evidence(root: Path) -> dict[str, dict[str, Any]]:
    names = {
        "autonomous": "autonomous-review.json",
        "decision": "decision-brief.json",
        "longitudinal": "longitudinal-intelligence.json",
        "confidence": "evidence-confidence.json",
        "journey": "user-journey.json",
        "ux": "ux-friction.json",
        "states": "state-edge-case.json",
        "behavioral": "behavioral-product.json",
        "contract": "product-contract-audit.json",
        "app": "app-intelligence.json",
    }
    result: dict[str, dict[str, Any]] = {}
    for key, filename in names.items():
        payload = read_json(root / filename)
        if payload is not None:
            result[key] = payload
    return result


def _tokens(*values: Any) -> str:
    return " ".join(_safe(value).lower() for value in values if value is not None)


def select_targets(
    *,
    source: str,
    kind: str,
    subject: str,
    message: str,
) -> tuple[str, list[str], str]:
    text = _tokens(source, kind, subject, message)

    if source == "FIX_NOW":
        if any(token in text for token in ("network", "offline", "connectiv", "http", "api", "sync", "cloud")):
            labs = ["network"]
        elif any(token in text for token in ("migration", "upgrade", "schema", "version")):
            labs = ["upgrade", "persistence", "storage"]
        elif any(token in text for token in ("persistence", "restart", "database", "room", "dao", "save", "restore")):
            labs = ["persistence", "storage"]
        elif any(token in text for token in ("background", "doze", "worker", "service", "process death", "process_death")):
            labs = ["background", "resource_pressure"]
        elif any(token in text for token in ("permission", "notification", "camera", "location", "system ui", "system_ui")):
            labs = ["system"]
        elif any(token in text for token in ("performance", "startup", "jank", "slow", "latency")):
            labs = ["performance"]
        else:
            labs = ["core-runtime", "visual-regression"]
        return "POST_FIX_VERIFICATION", labs, "Reproduce the trusted failure path and repeat it after the fix without delaying the fix itself."

    if source == "EVIDENCE_CONTRADICTION":
        if any(token in text for token in ("network", "offline", "connectiv", "http", "api", "sync", "cloud")):
            labs = ["product-analysis", "network"]
        elif any(token in text for token in ("migration", "upgrade", "schema", "persistence", "database", "storage", "save")):
            labs = ["product-analysis", "persistence", "storage"]
        elif any(token in text for token in ("journey", "navigation", "loop", "interaction", "reachab")):
            labs = ["product-analysis", "safe-interaction-crawler"]
        elif any(token in text for token in ("permission", "notification", "camera", "location", "system ui", "system_ui")):
            labs = ["product-analysis", "system"]
        else:
            labs = ["product-analysis", "full-source-review"]
        return "EVIDENCE_RECONCILIATION", labs, "Reconcile contradictory bounded evidence and, where useful, collect direct specialist evidence for the same subject."

    if any(token in text for token in ("network", "offline", "connectiv", "http", "api", "sync", "cloud")):
        return "SPECIALIST_RUNTIME", ["network"], "Exercise network-dependent behavior under bounded offline/recovery conditions."

    if any(token in text for token in ("migration", "upgrade", "schema", "version")):
        return "SPECIALIST_RUNTIME", ["upgrade", "persistence", "storage"], "Verify data and behavior across a bounded upgrade/migration path."

    if any(token in text for token in ("persistence", "restart", "database", "room", "dao", "save", "restore")):
        return "SPECIALIST_RUNTIME", ["persistence", "storage"], "Verify state survival and data integrity across restart/reload boundaries."

    if any(token in text for token in ("process death", "process_death", "memory", "resource pressure", "resource_pressure")):
        return "SPECIALIST_RUNTIME", ["resource_pressure", "persistence"], "Verify recovery after bounded process/resource pressure."

    if any(token in text for token in ("background", "doze", "worker", "service", "alarm", "job")):
        return "SPECIALIST_RUNTIME", ["background", "resource_pressure"], "Verify background lifecycle and recovery behavior."

    if any(token in text for token in ("orientation", "configuration", "recreate", "rotation", "theme")):
        return "SPECIALIST_RUNTIME", ["configuration"], "Verify state and UI behavior across configuration recreation."

    if any(token in text for token in ("permission", "notification", "camera", "location", "system ui", "system_ui", "intent", "deeplink")):
        return "SPECIALIST_RUNTIME", ["system"], "Verify the relevant system/permission transition and recovery path."

    if any(token in text for token in ("performance", "startup", "jank", "slow", "latency", "memory pressure")):
        return "SPECIALIST_RUNTIME", ["performance"], "Measure the affected runtime path against the existing performance evidence."

    if any(token in text for token in (
        "journey", "navigation", "loop", "dead end", "dead_end", "discover",
        "ambiguous", "stable_signature", "state change", "state_change", "interaction",
        "clickable", "reachab",
    )):
        return "TARGETED_JOURNEY", ["safe-interaction-crawler", "visual-journey"], "Replay the bounded user path and compare observed UI-state transitions."

    if "contradict" in text:
        return "EVIDENCE_RECONCILIATION", ["product-analysis", "full-source-review"], "Reconcile the contradictory bounded evidence without choosing a source by assumption."

    if any(token in text for token in ("contract", "capability", "documentation", "doc_only", "promised", "excluded")):
        return "STATIC_EVIDENCE_REVIEW", ["product-analysis", "full-source-review"], "Reconcile product contract, implementation and bounded runtime evidence."

    if any(token in text for token in ("ux", "accessibility", "density", "label", "friction")):
        return "TARGETED_JOURNEY", ["safe-interaction-crawler", "ux-manual-review"], "Inspect the affected interaction with runtime evidence and bounded UX review."

    return "TARGETED_RUNTIME", ["core-runtime"], "Reproduce the bounded signal in the trusted runtime before changing product conclusions."


def procedure_for(experiment_type: str, subject: str, labs: list[str]) -> dict[str, Any]:
    label = subject or "affected behavior"
    if experiment_type == "SPECIALIST_RUNTIME":
        return {
            "preconditions": [
                "Use the exact reviewed source SHA and trusted build artifact.",
                "Keep the existing AppLab trusted-runtime isolation boundary.",
            ],
            "actions": [
                f"Reproduce the normal path for {label}.",
                f"Run the selected specialist coverage: {', '.join(labs)}.",
                "Repeat the affected transition after the specialist condition is applied.",
            ],
            "observe": [
                "Trusted result state and specialist-lab evidence.",
                "UI hierarchy/state preservation where applicable.",
                "Recovery behavior after the specialist condition is removed.",
            ],
            "sufficient_evidence": [
                "A reproducible trusted PASS/WARN/FAIL observation bound to the same source SHA.",
                "Evidence that directly addresses the original subject rather than a nearby feature.",
            ],
        }
    if experiment_type == "TARGETED_JOURNEY":
        return {
            "preconditions": [
                "Start from a deterministic trusted runtime state.",
                "Use only safe actions allowed by the existing crawler policy.",
            ],
            "actions": [
                f"Replay or discover the shortest safe path involving {label}.",
                "Capture every state transition and reduced signature.",
                "Capture UI hierarchy and screenshots for the relevant transition.",
            ],
            "observe": [
                "Whether the target transition is reproducible.",
                "Whether a repeated target forms an actual cycle or only path convergence.",
                "Whether visible/accessibility state contradicts the reduced signature.",
            ],
            "sufficient_evidence": [
                "Bounded journey evidence tied to concrete states/actions.",
                "No conclusion from signature stability alone.",
            ],
        }
    if experiment_type == "EVIDENCE_RECONCILIATION":
        return {
            "preconditions": ["Preserve every contradictory source and its provenance."],
            "actions": [
                f"Collect all bounded claims for {label}.",
                "Compare contract, code/configuration and trusted runtime bindings.",
                "Identify whether the contradiction is current, stale or genuinely unresolved.",
            ],
            "observe": [
                "Source revision and evidence class for each claim.",
                "Whether a stronger source directly addresses the same subject.",
            ],
            "sufficient_evidence": [
                "Contradictory sources remain visible.",
                "Any resolution is tied to explicit stronger/current evidence, never majority vote.",
            ],
        }
    if experiment_type == "STATIC_EVIDENCE_REVIEW":
        return {
            "preconditions": ["Use the current bounded source scan and product contract."],
            "actions": [
                f"Trace {label} from product claim to implementation evidence.",
                "Check whether runtime verification exists for the same capability.",
            ],
            "observe": [
                "Contract status, implementation provenance and runtime binding.",
                "Any scan-bound limitation that makes absence inconclusive.",
            ],
            "sufficient_evidence": [
                "A traceable product/code/runtime chain or an explicit evidence gap.",
            ],
        }
    if experiment_type == "POST_FIX_VERIFICATION":
        return {
            "preconditions": [
                "The original trusted failure evidence is retained.",
                "The candidate fix is isolated from unrelated product changes where practical.",
            ],
            "actions": [
                f"Reproduce {label} on the failing baseline when available.",
                "Run the same trusted path on the fixed revision.",
                "Run adjacent regression coverage selected by the existing planner.",
            ],
            "observe": [
                "Whether the original failure disappears on the same evidence path.",
                "Whether adjacent runtime behavior remains unchanged.",
            ],
            "sufficient_evidence": [
                "Before/after trusted evidence for the same subject.",
                "No claim that absence in a different path proves the fix.",
            ],
        }
    return {
        "preconditions": ["Use the exact reviewed SHA and trusted runtime evidence."],
        "actions": [f"Reproduce {label} in the smallest bounded trusted scenario."],
        "observe": ["Direct runtime evidence for the original subject."],
        "sufficient_evidence": ["A traceable observation that supports, contradicts or leaves the hypothesis unverified."],
    }


def experiment_id(kind: str, subject: str, labs: list[str]) -> str:
    payload = "|".join((kind, subject, ",".join(labs))).encode("utf-8")
    return "EXP-" + hashlib.sha256(payload).hexdigest()[:12].upper()


def build_experiment(
    *,
    source: str,
    priority: str,
    kind: str,
    subject: str,
    message: str,
    evidence: list[Any],
    basis: str,
) -> dict[str, Any]:
    experiment_type, labs, rationale = select_targets(
        source=source,
        kind=kind,
        subject=subject,
        message=message,
    )
    execution_mode = (
        "EXISTING_TRUSTED_LABS"
        if any(lab in RUNTIME_LABS or lab in JOURNEY_LABS or lab in {"core-runtime", "visual-regression"} for lab in labs)
        else "BOUNDED_REVIEW"
    )
    return {
        "id": experiment_id(kind, subject, labs),
        "priority": priority,
        "source": source,
        "kind": kind,
        "subject": subject,
        "hypothesis": (
            f"The signal '{kind}' for '{subject or 'the affected product area'}' "
            "represents a reproducible current behavior rather than a bounded-evidence artifact."
        ),
        "reason": message or rationale,
        "basis": basis,
        "evidence": [str(value) for value in evidence[:8]],
        "experiment_type": experiment_type,
        "labs": labs,
        "execution": {
            "mode": execution_mode,
            "reuses_existing_labs": True,
            "requires_new_test_engine": False,
            "automatic_product_mutation": False,
        },
        "procedure": procedure_for(experiment_type, subject, labs),
        "outcomes": {
            "SUPPORTED": "Direct bounded evidence supports the hypothesis.",
            "CONTRADICTED": "Direct bounded evidence contradicts the hypothesis.",
            "UNVERIFIED": "The experiment did not obtain sufficient direct evidence.",
        },
    }


def _add(
    rows: list[dict[str, Any]],
    *,
    source: str,
    priority: str,
    kind: str,
    subject: str,
    message: str,
    evidence: list[Any],
    basis: str,
) -> None:
    rows.append(
        build_experiment(
            source=source,
            priority=priority,
            kind=kind,
            subject=subject,
            message=message,
            evidence=evidence,
            basis=basis,
        )
    )


def build_plan(evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    decision = evidence.get("decision", {})
    longitudinal = evidence.get("longitudinal", {})
    confidence = evidence.get("confidence", {})

    candidates: list[dict[str, Any]] = []

    buckets = decision.get("buckets") if isinstance(decision.get("buckets"), dict) else {}
    for bucket, priority in (("FIX_NOW", "HIGH"), ("VERIFY_NEXT", "NORMAL")):
        values = buckets.get(bucket) if isinstance(buckets.get(bucket), list) else []
        for row in values:
            if not isinstance(row, dict):
                continue
            _add(
                candidates,
                source=bucket,
                priority=priority,
                kind=_safe(row.get("kind")),
                subject=_safe(row.get("subject")),
                message=_safe(row.get("message")),
                evidence=row.get("evidence", []) if isinstance(row.get("evidence"), list) else [],
                basis=_safe(row.get("basis")),
            )

    regressions = (
        longitudinal.get("regression_candidates")
        if isinstance(longitudinal.get("regression_candidates"), list)
        else []
    )
    for row in regressions:
        if not isinstance(row, dict):
            continue
        _add(
            candidates,
            source="LONGITUDINAL_REGRESSION",
            priority="HIGH",
            kind=_safe(row.get("kind")),
            subject=_safe(row.get("subject")),
            message=_safe(row.get("reason")) or _safe(row.get("message")),
            evidence=row.get("evidence", []) if isinstance(row.get("evidence"), list) else [],
            basis=_safe(longitudinal.get("state")) or "LONGITUDINAL",
        )

    contradictions = (
        confidence.get("contradictions")
        if isinstance(confidence.get("contradictions"), list)
        else []
    )
    for row in contradictions:
        if not isinstance(row, dict):
            continue
        _add(
            candidates,
            source="EVIDENCE_CONTRADICTION",
            priority="HIGH",
            kind=_safe(row.get("kind")) or "EVIDENCE_CONTRADICTION",
            subject=_safe(row.get("subject")),
            message=_safe(row.get("message")),
            evidence=row.get("evidence", []) if isinstance(row.get("evidence"), list) else [],
            basis="EVIDENCE_CONFIDENCE",
        )

    merged: dict[str, dict[str, Any]] = {}
    for row in candidates:
        key = "|".join(
            (
                _safe(row.get("kind")).lower(),
                _safe(row.get("subject")).lower(),
                ",".join(row.get("labs", [])),
            )
        )
        if key not in merged:
            merged[key] = row
            merged[key]["triggers"] = [row["source"]]
            continue
        existing = merged[key]
        existing["triggers"] = sorted(set(existing.get("triggers", []) + [row["source"]]))
        existing["evidence"] = list(dict.fromkeys(existing.get("evidence", []) + row.get("evidence", [])))[:8]
        if PRIORITY_ORDER[row["priority"]] < PRIORITY_ORDER[existing["priority"]]:
            existing["priority"] = row["priority"]
            existing["source"] = row["source"]
            existing["reason"] = row["reason"]
            existing["basis"] = row["basis"]

    experiments = list(merged.values())
    experiments.sort(
        key=lambda row: (
            PRIORITY_ORDER.get(_safe(row.get("priority")), 9),
            min(SOURCE_ORDER.get(trigger, 9) for trigger in row.get("triggers", [""])),
            _safe(row.get("kind")),
            _safe(row.get("subject")),
        )
    )
    experiments = experiments[:24]

    ready = sum(1 for row in experiments if (row.get("execution") or {}).get("mode") == "EXISTING_TRUSTED_LABS")
    review_only = len(experiments) - ready
    next_experiment = experiments[0]["id"] if experiments else None

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "state": "EXPERIMENTS_READY" if experiments else "NO_EXPERIMENTS_REQUIRED",
        "next_experiment_id": next_experiment,
        "experiments": experiments,
        "summary": {
            "experiments": len(experiments),
            "high_priority": sum(1 for row in experiments if row["priority"] == "HIGH"),
            "normal_priority": sum(1 for row in experiments if row["priority"] == "NORMAL"),
            "existing_lab_ready": ready,
            "bounded_review_only": review_only,
            "longitudinal_regression_inputs": len(regressions),
            "contradiction_inputs": len(contradictions),
            "verify_next_inputs": len(
                buckets.get("VERIFY_NEXT", [])
                if isinstance(buckets.get("VERIFY_NEXT"), list)
                else []
            ),
        },
        "guardrails": {
            "no_numeric_product_score": True,
            "planner_is_advisory": True,
            "no_automatic_product_mutation": True,
            "existing_labs_are_reused": True,
            "missing_evidence_never_becomes_pass": True,
            "experiment_outcome_cannot_override_certification": True,
            "fix_now_is_not_delayed_by_planner": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AppLab v3.6 — Autonomous Experiment Planner",
        "",
        f"- State: **{report['state']}**",
        f"- Experiments: **{summary['experiments']}**",
        f"- High priority: **{summary['high_priority']}**",
        f"- Existing-lab ready: **{summary['existing_lab_ready']}**",
        f"- Review-only: **{summary['bounded_review_only']}**",
        "",
    ]
    if not report["experiments"]:
        lines.append("Current evidence does not require an additional bounded experiment.")
        return "\n".join(lines)

    lines.extend(["## Ordered experiment plan", ""])
    for row in report["experiments"]:
        lines.extend(
            [
                f"### {row['id']} — {row['kind']}",
                "",
                f"- Priority: **{row['priority']}**",
                f"- Subject: **{row['subject'] or '—'}**",
                f"- Type: **{row['experiment_type']}**",
                f"- Labs: **{', '.join(row['labs'])}**",
                f"- Triggers: **{', '.join(row.get('triggers', []))}**",
                f"- Hypothesis: {row['hypothesis']}",
                "",
            ]
        )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    write_report(output_dir, "experiment-plan", report, markdown(report))


def self_test() -> None:
    evidence = {
        "decision": {
            "buckets": {
                "FIX_NOW": [
                    {
                        "kind": "RUNTIME_INTERACTION_FAILURE",
                        "subject": "Save",
                        "message": "Save failed in trusted runtime.",
                        "evidence": ["interaction-crawl.json"],
                        "basis": "RUNTIME_CONFIRMED",
                    }
                ],
                "VERIFY_NEXT": [
                    {
                        "kind": "EDGE_STATE_NOT_OBSERVED",
                        "subject": "offline",
                        "message": "Offline state not observed.",
                        "evidence": [],
                        "basis": "STATIC_HEURISTIC",
                    },
                    {
                        "kind": "NAVIGATION_LOOP_CANDIDATE",
                        "subject": "Search → Detail",
                        "message": "Observed journey may contain a loop.",
                        "evidence": ["journey-crawl.json"],
                        "basis": "RUNTIME_UX_REVIEW",
                    },
                ],
            }
        },
        "longitudinal": {
            "state": "REGRESSION_REVIEW",
            "regression_candidates": [
                {
                    "kind": "NAVIGATION_LOOP_CANDIDATE",
                    "subject": "Search → Detail",
                    "reason": "finding returned",
                    "evidence": ["journey-crawl.json"],
                }
            ],
        },
        "confidence": {
            "contradictions": [
                {
                    "kind": "CONTRACT_RUNTIME_CONTRADICTION",
                    "subject": "authentication",
                    "message": "Contract and runtime disagree.",
                    "evidence": ["README.md", "ui.xml"],
                }
            ]
        },
    }
    report = build_plan(evidence)
    assert report["state"] == "EXPERIMENTS_READY"
    assert report["summary"]["high_priority"] >= 3
    assert report["summary"]["existing_lab_ready"] >= 3
    fix = next(row for row in report["experiments"] if row["source"] == "FIX_NOW")
    assert fix["experiment_type"] == "POST_FIX_VERIFICATION"
    assert fix["labs"] == ["persistence", "storage"]
    loop = next(row for row in report["experiments"] if row["kind"] == "NAVIGATION_LOOP_CANDIDATE")
    assert loop["priority"] == "HIGH"
    assert "LONGITUDINAL_REGRESSION" in loop["triggers"]
    assert loop["experiment_type"] == "TARGETED_JOURNEY"
    offline = next(row for row in report["experiments"] if row["subject"] == "offline")
    assert offline["labs"] == ["network"]
    contradiction = next(row for row in report["experiments"] if row["source"] == "EVIDENCE_CONTRADICTION")
    assert contradiction["experiment_type"] == "EVIDENCE_RECONCILIATION"
    network_contradiction = build_experiment(
        source="EVIDENCE_CONTRADICTION",
        priority="HIGH",
        kind="NETWORK_EVIDENCE_CONTRADICTION",
        subject="sync",
        message="Static and runtime network evidence disagree.",
        evidence=[],
        basis="EVIDENCE_CONFIDENCE",
    )
    assert network_contradiction["experiment_type"] == "EVIDENCE_RECONCILIATION"
    assert "network" in network_contradiction["labs"]
    assert experiment_id("A", "subject", ["network"]) == experiment_id("A", "subject", ["network"])
    assert build_plan({"decision": {"buckets": {}}})["state"] == "NO_EXPERIMENTS_REQUIRED"
    print("AppLab Autonomous Experiment Planner self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output-dir", default="applab-autonomous-review")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.evidence_dir:
        raise SystemExit("--evidence-dir is required")

    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.is_dir():
        raise SystemExit("evidence directory does not exist")

    report = build_plan(load_evidence(evidence_dir))
    write_outputs(report, Path(args.output_dir))
    print(json.dumps({"engine_version": ENGINE_VERSION, "state": report["state"], **report["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
