#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from product_review_common import load_json, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.4.0"

CORE_ROLES = {"home", "search", "editor", "onboarding"}
NON_CORE_DEEP_LABELS = {
    "settings", "impostazioni", "profile", "profilo", "about", "info",
    "help", "aiuto", "privacy", "terms", "termini",
}


def graph_has_path(adjacency: dict[str, set[str]], start: str, goal: str) -> bool:
    if not start or not goal:
        return False
    pending = [start]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current == goal:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(
            target
            for target in adjacency.get(current, set())
            if target not in seen
        )
    return False


def finding(
    *,
    kind: str,
    category: str,
    severity: str,
    confidence: str,
    subject: str,
    message: str,
    evidence: list[str] | None = None,
    state_id: str = "",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "subject": subject,
        "message": message,
        "evidence": (evidence or [])[:10],
        "state_id": state_id,
    }


def build_report(
    app: dict[str, Any],
    user_journey: dict[str, Any],
    state_edge: dict[str, Any],
) -> dict[str, Any]:
    runtime_graph = (
        user_journey.get("runtime_graph")
        if isinstance(user_journey.get("runtime_graph"), dict)
        else {}
    )
    states = runtime_graph.get("states") if isinstance(runtime_graph.get("states"), list) else []
    transitions = (
        runtime_graph.get("transitions")
        if isinstance(runtime_graph.get("transitions"), list)
        else []
    )
    states = [row for row in states if isinstance(row, dict)]
    transitions = [row for row in transitions if isinstance(row, dict)]

    findings: list[dict[str, Any]] = []

    no_change = [row for row in transitions if str(row.get("status", "")) == "NO_CHANGE"]
    for row in no_change:
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        evidence = [
            value
            for value in (
                str(row.get("ui_hierarchy", "")),
                str(row.get("screenshot", "")),
            )
            if value
        ]
        findings.append(
            finding(
                kind="STABLE_SIGNATURE_AFTER_ACTION_CANDIDATE",
                category="feedback",
                severity="REVIEW",
                confidence="MEDIUM",
                subject=str(action.get("label", "")),
                message=(
                    "A safe trusted-runtime action left the crawler's reduced stable signature unchanged. "
                    "The signature normalizes digits and omits some visual/accessibility state, so verify "
                    "actual feedback before treating this as UX friction."
                ),
                evidence=evidence,
                state_id=str(row.get("from", "")),
            )
        )

    if len(no_change) >= 2:
        findings.append(
            finding(
                kind="REPEATED_STABLE_SIGNATURE_PATTERN",
                category="feedback",
                severity="REVIEW",
                confidence="MEDIUM",
                subject="runtime-journeys",
                message=(
                    "Multiple safe runtime actions left the crawler's reduced stable signature unchanged "
                    "during bounded journey exploration. Verify visual/accessibility feedback before drawing conclusions."
                ),
            )
        )

    for row in states:
        signature = row.get("signature") if isinstance(row.get("signature"), dict) else {}
        clickable = int(signature.get("clickable", 0) or 0)
        if clickable >= 12:
            findings.append(
                finding(
                    kind="HIGH_CLICKABLE_DENSITY_CANDIDATE",
                    category="density",
                    severity="INFO",
                    confidence="LOW",
                    subject=str(row.get("id", "")),
                    message=(
                        f"Observed runtime state exposes {clickable} clickable nodes. "
                        "Review visual hierarchy and prioritization; UI hierarchy count alone does not prove clutter."
                    ),
                    evidence=[
                        value
                        for value in (
                            str(row.get("ui_hierarchy", "")),
                            str(row.get("screenshot", "")),
                        )
                        if value
                    ],
                    state_id=str(row.get("id", "")),
                )
            )

    by_source_label: dict[tuple[str, str], set[str]] = defaultdict(set)
    transition_evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in transitions:
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        source = str(row.get("from", "")).strip()
        label = str(action.get("label", "")).strip()
        raw_target = row.get("to")
        target = raw_target.strip() if isinstance(raw_target, str) else ""
        if (
            str(row.get("status", "")) != "CHANGED"
            or not bool(row.get("state_changed"))
            or not source
            or not label
            or not target
        ):
            continue
        key = (source, label.lower())
        by_source_label[key].add(target)
        for value in (
            str(row.get("ui_hierarchy", "")),
            str(row.get("screenshot", "")),
        ):
            if value and value not in transition_evidence[key]:
                transition_evidence[key].append(value)

    for (source, label), targets in sorted(by_source_label.items()):
        if len(targets) <= 1:
            continue
        findings.append(
            finding(
                kind="AMBIGUOUS_RUNTIME_ACTION_LABEL",
                category="discoverability",
                severity="REVIEW",
                confidence="MEDIUM",
                subject=label,
                message=(
                    "The same visible safe-action label from one observed state led to "
                    "multiple runtime target states. Verify whether the control is contextually unambiguous."
                ),
                evidence=transition_evidence[(source, label)],
                state_id=source,
            )
        )

    changed_adjacency: dict[str, set[str]] = defaultdict(set)
    for row in transitions:
        if str(row.get("status", "")) != "CHANGED" or not bool(row.get("state_changed")):
            continue
        source = row.get("from")
        target = row.get("to")
        if isinstance(source, str) and isinstance(target, str) and source and target and source != target:
            changed_adjacency[source].add(target)

    for row in transitions:
        source = row.get("from")
        target = row.get("to")
        if (
            not bool(row.get("target_seen_before"))
            or not isinstance(source, str)
            or not isinstance(target, str)
            or not source
            or not target
            or source == target
            or str(row.get("status", "")) != "CHANGED"
            or not bool(row.get("state_changed"))
            or not graph_has_path(changed_adjacency, target, source)
        ):
            continue
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        findings.append(
            finding(
                kind="NAVIGATION_LOOP_CANDIDATE",
                category="navigation",
                severity="INFO",
                confidence="MEDIUM",
                subject=str(action.get("label", "")),
                message=(
                    "A safe navigation action returned to a previously observed state. "
                    "This may be intentional navigation; review only if it creates user confusion."
                ),
                evidence=[
                    value
                    for value in (
                        str(row.get("ui_hierarchy", "")),
                        str(row.get("screenshot", "")),
                    )
                    if value
                ],
                state_id=str(row.get("from", "")),
            )
        )

    journeys = user_journey.get("journeys") if isinstance(user_journey.get("journeys"), list) else []
    for row in journeys:
        if not isinstance(row, dict):
            continue
        depth = int(row.get("depth", 0) or 0)
        steps = [str(value) for value in row.get("steps", [])] if isinstance(row.get("steps"), list) else []
        if depth < 3 or not steps:
            continue
        normalized = {step.lower().strip() for step in steps}
        if normalized & NON_CORE_DEEP_LABELS:
            continue
        findings.append(
            finding(
                kind="DEEP_JOURNEY_CANDIDATE",
                category="navigation",
                severity="INFO",
                confidence="LOW",
                subject=" → ".join(steps),
                message=(
                    f"A bounded observed journey required {depth} safe navigation steps. "
                    "Review whether the path is appropriate for the user job; depth alone is not a defect."
                ),
                evidence=[
                    value
                    for value in (
                        str(row.get("ui_hierarchy", "")),
                        str(row.get("screenshot", "")),
                    )
                    if value
                ],
                state_id=str(row.get("state_id", "")),
            )
        )

    flow = app.get("product_flow_graph") if isinstance(app.get("product_flow_graph"), dict) else {}
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    journey_findings = (
        user_journey.get("findings")
        if isinstance(user_journey.get("findings"), list)
        else []
    )
    static_journey_graph = (
        user_journey.get("static_graph")
        if isinstance(user_journey.get("static_graph"), dict)
        else {}
    )
    raw_unverified = static_journey_graph.get("runtime_unmatched_surfaces")
    if isinstance(raw_unverified, list):
        unverified = {
            str(value)
            for value in raw_unverified
            if isinstance(value, str) and value
        }
    else:
        unverified = {
            str(row.get("subject", ""))
            for row in journey_findings
            if isinstance(row, dict)
            and str(row.get("kind", "")) == "STATIC_SURFACE_JOURNEY_UNVERIFIED"
        }
    for node in nodes:
        if not isinstance(node, dict):
            continue
        surface = str(node.get("id", ""))
        roles = {
            str(value).lower()
            for value in node.get("roles", [])
            if isinstance(value, str)
        }
        if not surface or surface not in unverified or not (roles & CORE_ROLES):
            continue
        findings.append(
            finding(
                kind="CORE_SURFACE_DISCOVERABILITY_UNVERIFIED",
                category="discoverability",
                severity="REVIEW",
                confidence="LOW",
                subject=surface,
                message=(
                    "A core-role static surface was not matched during bounded trusted "
                    "journey exploration. This requires discoverability review, not an unreachable-screen verdict."
                ),
                evidence=[surface],
            )
        )

    edge_states = state_edge.get("states") if isinstance(state_edge.get("states"), dict) else {}
    for state_name in ("empty", "error", "permission_denied"):
        row = edge_states.get(state_name)
        if not isinstance(row, dict):
            continue
        if str(row.get("applicability", "")) != "APPLICABLE":
            continue
        if str(row.get("status", "")) not in {"NOT_OBSERVED", "OBSERVED_UNKNOWN"}:
            continue
        findings.append(
            finding(
                kind="UX_EDGE_STATE_UNVERIFIED",
                category="recovery",
                severity="REVIEW",
                confidence="MEDIUM",
                subject=state_name,
                message=(
                    f"Applicable UX state '{state_name}' was not observed in trusted runtime evidence."
                ),
            )
        )

    order = {"HIGH_REVIEW": 0, "REVIEW": 1, "INFO": 2}
    findings.sort(
        key=lambda row: (
            order.get(str(row.get("severity", "INFO")), 9),
            str(row.get("category", "")),
            str(row.get("kind", "")),
            str(row.get("subject", "")),
        )
    )
    by_category = Counter(str(row.get("category", "other")) for row in findings)
    review_signals = sum(
        1 for row in findings if row.get("severity") in {"HIGH_REVIEW", "REVIEW"}
    )
    no_change_share = (
        round(len(no_change) / len(transitions), 3) if transitions else 0.0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "findings": findings,
        "summary": {
            "runtime_transitions": len(transitions),
            "no_change_actions": len(no_change),
            "no_change_share": no_change_share,
            "review_signals": review_signals,
            "info_signals": sum(1 for row in findings if row.get("severity") == "INFO"),
            "by_category": dict(sorted(by_category.items())),
        },
        "guardrails": {
            "no_numeric_ux_score": True,
            "no_change_is_review_not_defect": True,
            "clickable_density_is_candidate_only": True,
            "journey_depth_is_candidate_only": True,
            "unobserved_core_surface_is_not_unreachable": True,
            "release_verdict_unchanged": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AppLab UX Friction & Discoverability Lab",
        "",
        f"- Runtime transitions: **{summary['runtime_transitions']}**",
        f"- No-change actions: **{summary['no_change_actions']}**",
        f"- No-change share: **{summary['no_change_share']}**",
        f"- Review signals: **{summary['review_signals']}**",
        "",
    ]
    for row in report["findings"][:35]:
        lines.append(
            f"- **{row.get('severity','INFO')} / {row.get('category','')} / "
            f"{row.get('kind','')}** · {row.get('subject','')} — {row.get('message','')}"
        )
    return "\n".join(lines)


def self_test() -> None:
    app = {
        "product_flow_graph": {
            "nodes": [
                {"id": "home.dart", "roles": ["home"]},
                {"id": "search.dart", "roles": ["search"]},
            ]
        }
    }
    user_journey = {
        "runtime_graph": {
            "states": [
                {
                    "id": "root",
                    "signature": {"clickable": 14},
                    "ui_hierarchy": "root.xml",
                    "screenshot": "root.png",
                }
            ],
            "transitions": [
                {
                    "from": "root",
                    "to": "root",
                    "status": "NO_CHANGE",
                    "state_changed": False,
                    "target_seen_before": True,
                    "action": {"label": "Search"},
                    "ui_hierarchy": "after.xml",
                    "screenshot": "after.png",
                },
                {
                    "from": "root",
                    "to": "settings",
                    "status": "CHANGED",
                    "state_changed": True,
                    "target_seen_before": False,
                    "action": {"label": "Open"},
                },
                {
                    "from": "root",
                    "to": None,
                    "status": "OBSERVATION_WARN",
                    "state_changed": False,
                    "target_seen_before": False,
                    "action": {"label": "Open"},
                },
                {
                    "from": "other",
                    "to": "settings",
                    "status": "CHANGED",
                    "state_changed": True,
                    "target_seen_before": True,
                    "action": {"label": "Converge"},
                },
            ],
        },
        "journeys": [
            {
                "state_id": "deep",
                "depth": 3,
                "steps": ["Open", "Browse", "Item"],
            }
        ],
        "findings": [],
        "static_graph": {
            "runtime_unmatched_surfaces": ["search.dart"],
        },
    }
    state_edge = {
        "states": {
            "empty": {
                "applicability": "APPLICABLE",
                "status": "NOT_OBSERVED",
            },
            "error": {
                "applicability": "APPLICABLE",
                "status": "OBSERVED",
            },
        }
    }
    report = build_report(app, user_journey, state_edge)
    kinds = {row["kind"] for row in report["findings"]}
    assert "STABLE_SIGNATURE_AFTER_ACTION_CANDIDATE" in kinds
    assert "HIGH_CLICKABLE_DENSITY_CANDIDATE" in kinds
    assert "CORE_SURFACE_DISCOVERABILITY_UNVERIFIED" in kinds
    assert "DEEP_JOURNEY_CANDIDATE" in kinds
    assert "UX_EDGE_STATE_UNVERIFIED" in kinds
    assert "AMBIGUOUS_RUNTIME_ACTION_LABEL" not in kinds
    assert "NAVIGATION_LOOP_CANDIDATE" not in kinds
    print("AppLab UX Friction & Discoverability Lab self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-intelligence")
    parser.add_argument("--user-journey")
    parser.add_argument("--state-edge")
    parser.add_argument("--output-dir", default="applab-ux-friction")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    app = load_json(Path(args.app_intelligence)) if args.app_intelligence else None
    journey = load_json(Path(args.user_journey)) if args.user_journey else None
    states = load_json(Path(args.state_edge)) if args.state_edge else None
    if app is None or journey is None or states is None:
        raise SystemExit("--app-intelligence, --user-journey and --state-edge are required")

    report = build_report(app, journey, states)
    write_report(Path(args.output_dir), "ux-friction", report, markdown(report))
    print(json.dumps({"lab_version": LAB_VERSION, **report["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
