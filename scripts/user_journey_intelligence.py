#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from product_review_common import load_json, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.3.0"


def static_graph(app: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    flow = app.get("product_flow_graph") if isinstance(app.get("product_flow_graph"), dict) else {}
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    edges = flow.get("edges") if isinstance(flow.get("edges"), list) else []
    return (
        [row for row in nodes if isinstance(row, dict)],
        [row for row in edges if isinstance(row, dict)],
    )


def runtime_graph(journey: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(journey, dict):
        return [], []
    states = journey.get("states") if isinstance(journey.get("states"), list) else []
    transitions = journey.get("transitions") if isinstance(journey.get("transitions"), list) else []
    return (
        [row for row in states if isinstance(row, dict)],
        [row for row in transitions if isinstance(row, dict)],
    )


def observed_journeys(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        labels = state.get("path_labels") if isinstance(state.get("path_labels"), list) else []
        if not labels:
            continue
        rows.append(
            {
                "state_id": str(state.get("id", "")),
                "depth": int(state.get("depth", len(labels)) or len(labels)),
                "steps": [str(label) for label in labels],
                "terminal_candidate": bool(state.get("safe_dead_end_candidate", False)),
                "screenshot": state.get("screenshot"),
                "ui_hierarchy": state.get("ui_hierarchy"),
            }
        )
    rows.sort(key=lambda row: (int(row["depth"]), row["steps"]))
    return rows


def shortest_static_distances(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, int]:
    ids = [str(row.get("id", "")) for row in nodes if str(row.get("id", ""))]
    incoming = Counter(str(row.get("to", "")) for row in edges)
    entry_terms = ("main", "home", "onboard", "launch", "root")
    roots = [
        node_id
        for node_id in ids
        if any(term in node_id.lower() for term in entry_terms)
    ]
    if not roots:
        roots = [node_id for node_id in ids if incoming[node_id] == 0][:4]
    adjacency: dict[str, list[str]] = defaultdict(list)
    for row in edges:
        source = str(row.get("from", ""))
        target = str(row.get("to", ""))
        if source and target and target not in adjacency[source]:
            adjacency[source].append(target)
    distances: dict[str, int] = {}
    frontier = [(root, 0) for root in roots]
    while frontier:
        current, depth = frontier.pop(0)
        if current in distances and distances[current] <= depth:
            continue
        distances[current] = depth
        for target in adjacency.get(current, []):
            frontier.append((target, depth + 1))
    return distances


def build_report(
    app: dict[str, Any],
    behavioral: dict[str, Any],
    journey: dict[str, Any] | None,
) -> dict[str, Any]:
    static_nodes, static_edges = static_graph(app)
    states, transitions = runtime_graph(journey)
    journeys = observed_journeys(states)
    static_distances = shortest_static_distances(static_nodes, static_edges)

    matched_surfaces = {
        str(row.get("id", ""))
        for row in behavioral.get("runtime_matched_surfaces", [])
        if isinstance(row, dict)
    }

    runtime_result = (
        str(journey.get("result", "NOT_OBSERVED"))
        if isinstance(journey, dict)
        else "NOT_OBSERVED"
    )

    changed = [row for row in transitions if bool(row.get("state_changed"))]
    no_change = [row for row in transitions if str(row.get("status", "")) == "NO_CHANGE"]
    failures = [row for row in transitions if str(row.get("status", "")) == "FAIL"]
    repeat_targets = [
        row
        for row in transitions
        if bool(row.get("target_seen_before")) and row.get("to") != row.get("from")
    ]
    dead_ends = [
        row
        for row in states
        if bool(row.get("safe_dead_end_candidate"))
    ]

    findings: list[dict[str, Any]] = []

    for row in failures:
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        findings.append(
            {
                "kind": "JOURNEY_RUNTIME_FAILURE",
                "severity": "HIGH_REVIEW",
                "confidence": "HIGH",
                "subject": str(action.get("label", "")),
                "message": "A safe multi-step journey action caused a trusted runtime failure.",
                "evidence": [],
                "state_id": str(row.get("from", "")),
            }
        )

    for row in no_change:
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        evidence = []
        if row.get("ui_hierarchy"):
            evidence.append(str(row.get("ui_hierarchy")))
        if row.get("screenshot"):
            evidence.append(str(row.get("screenshot")))
        findings.append(
            {
                "kind": "JOURNEY_ACTION_NO_STATE_CHANGE",
                "severity": "REVIEW",
                "confidence": "MEDIUM",
                "subject": str(action.get("label", "")),
                "message": "A safe journey action produced no observed UI-state change.",
                "evidence": evidence,
                "state_id": str(row.get("from", "")),
            }
        )

    for row in repeat_targets:
        action = row.get("action") if isinstance(row.get("action"), dict) else {}
        findings.append(
            {
                "kind": "JOURNEY_LOOP_CANDIDATE",
                "severity": "INFO",
                "confidence": "MEDIUM",
                "subject": str(action.get("label", "")),
                "message": "A safe journey transition returned to a previously observed runtime state.",
                "evidence": [
                    value
                    for value in (
                        str(row.get("ui_hierarchy", "")),
                        str(row.get("screenshot", "")),
                    )
                    if value
                ],
                "state_id": str(row.get("from", "")),
                "target_state_id": str(row.get("to", "")),
            }
        )

    for row in dead_ends:
        findings.append(
            {
                "kind": "SAFE_JOURNEY_DEAD_END_CANDIDATE",
                "severity": "INFO",
                "confidence": "LOW",
                "subject": str(row.get("id", "")),
                "message": (
                    "No eligible safe navigation control was found in this observed state. "
                    "Unsafe/unknown controls are intentionally excluded, so this does not prove a product dead end."
                ),
                "evidence": [
                    value
                    for value in (
                        str(row.get("ui_hierarchy", "")),
                        str(row.get("screenshot", "")),
                    )
                    if value
                ],
                "state_id": str(row.get("id", "")),
            }
        )

    if len(static_nodes) >= 3 and not changed:
        findings.append(
            {
                "kind": "STATIC_RUNTIME_JOURNEY_COVERAGE_GAP",
                "severity": "REVIEW",
                "confidence": "MEDIUM",
                "subject": "product-flow",
                "message": (
                    "The static product graph contains multiple surfaces, but no multi-step "
                    "trusted runtime state transition was observed."
                ),
                "evidence": [str(row.get("id", "")) for row in static_nodes[:8]],
            }
        )

    unobserved_static = [
        str(row.get("id", ""))
        for row in static_nodes
        if str(row.get("id", "")) not in matched_surfaces
    ]
    for surface in unobserved_static[:20]:
        findings.append(
            {
                "kind": "STATIC_SURFACE_JOURNEY_UNVERIFIED",
                "severity": "INFO",
                "confidence": "LOW",
                "subject": surface,
                "message": "Static product surface was not matched in bounded trusted runtime journey evidence.",
                "evidence": [surface],
                "static_distance": static_distances.get(surface),
            }
        )

    findings.sort(
        key=lambda row: (
            {"HIGH_REVIEW": 0, "REVIEW": 1, "INFO": 2}.get(str(row.get("severity")), 9),
            str(row.get("kind", "")),
            str(row.get("subject", "")),
        )
    )

    max_depth = max((int(row.get("depth", 0) or 0) for row in states), default=0)
    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "runtime_result": runtime_result,
        "runtime_graph": {
            "state_count": len(states),
            "transition_count": len(transitions),
            "changed_transition_count": len(changed),
            "no_change_transition_count": len(no_change),
            "repeat_target_count": len(repeat_targets),
            "safe_dead_end_candidate_count": len(dead_ends),
            "max_observed_depth": max_depth,
            "states": states,
            "transitions": transitions,
        },
        "static_graph": {
            "node_count": len(static_nodes),
            "edge_count": len(static_edges),
            "runtime_matched_surface_count": len(matched_surfaces),
            "runtime_unmatched_surface_count": len(unobserved_static),
            "runtime_unmatched_surfaces": unobserved_static,
            "shortest_distances": static_distances,
        },
        "journeys": journeys,
        "findings": findings,
        "summary": {
            "journeys_observed": len(journeys),
            "states_observed": len(states),
            "transitions_observed": len(transitions),
            "max_observed_depth": max_depth,
            "runtime_failures": len(failures),
            "no_change_actions": len(no_change),
            "loop_candidates": len(repeat_targets),
            "safe_dead_end_candidates": len(dead_ends),
            "unverified_static_surfaces": len(unobserved_static),
            "review_signals": sum(
                1
                for row in findings
                if row.get("severity") in {"HIGH_REVIEW", "REVIEW"}
            ),
        },
        "guardrails": {
            "runtime_journeys_require_trusted_crawler_evidence": True,
            "safe_dead_end_is_not_product_dead_end": True,
            "unobserved_surface_is_not_unreachable": True,
            "bounded_depth_is_explicit": True,
            "no_numeric_journey_score": True,
            "no_release_verdict": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# AppLab User Journey Intelligence",
        "",
        f"- Runtime result: **{report['runtime_result']}**",
        f"- Journeys observed: **{summary['journeys_observed']}**",
        f"- States / transitions: **{summary['states_observed']} / {summary['transitions_observed']}**",
        f"- Max observed depth: **{summary['max_observed_depth']}**",
        f"- No-change actions: **{summary['no_change_actions']}**",
        f"- Loop candidates: **{summary['loop_candidates']}**",
        f"- Review signals: **{summary['review_signals']}**",
        "",
        "## Observed journeys",
        "",
    ]
    for row in report["journeys"][:20]:
        lines.append(
            f"- depth {row['depth']} · " + " → ".join(row.get("steps", []))
        )
    if report["findings"]:
        lines.extend(["", "## Findings", ""])
        for row in report["findings"][:30]:
            lines.append(
                f"- **{row.get('severity','INFO')} / {row.get('kind','')}** · "
                f"{row.get('subject','')} — {row.get('message','')}"
            )
    return "\n".join(lines)


def self_test() -> None:
    app = {
        "product_flow_graph": {
            "nodes": [
                {"id": "lib/home_screen.dart"},
                {"id": "lib/settings_screen.dart"},
                {"id": "lib/profile_screen.dart"},
            ],
            "edges": [
                {"from": "lib/home_screen.dart", "to": "lib/settings_screen.dart"},
                {"from": "lib/settings_screen.dart", "to": "lib/profile_screen.dart"},
            ],
        }
    }
    behavioral = {
        "runtime_matched_surfaces": [
            {"id": "lib/settings_screen.dart"},
            {"id": "lib/profile_screen.dart"},
        ]
    }
    journey = {
        "result": "PASS",
        "states": [
            {
                "id": "root",
                "depth": 0,
                "path_labels": [],
                "safe_candidate_count": 1,
                "safe_dead_end_candidate": False,
            },
            {
                "id": "settings",
                "depth": 1,
                "path_labels": ["Settings"],
                "safe_candidate_count": 1,
                "safe_dead_end_candidate": False,
            },
            {
                "id": "profile",
                "depth": 2,
                "path_labels": ["Settings", "Profile"],
                "safe_candidate_count": 0,
                "safe_dead_end_candidate": True,
                "ui_hierarchy": "journey/profile.xml",
            },
        ],
        "transitions": [
            {
                "from": "root",
                "to": "settings",
                "status": "CHANGED",
                "state_changed": True,
                "target_seen_before": False,
                "action": {"label": "Settings"},
            },
            {
                "from": "settings",
                "to": "profile",
                "status": "CHANGED",
                "state_changed": True,
                "target_seen_before": False,
                "action": {"label": "Profile"},
            },
        ],
    }
    report = build_report(app, behavioral, journey)
    assert report["summary"]["journeys_observed"] == 2
    assert report["summary"]["max_observed_depth"] == 2
    assert report["summary"]["safe_dead_end_candidates"] == 1
    assert report["static_graph"]["shortest_distances"]["lib/profile_screen.dart"] == 2
    print("AppLab User Journey Intelligence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-intelligence")
    parser.add_argument("--behavioral")
    parser.add_argument("--journey-crawl")
    parser.add_argument("--output-dir", default="applab-user-journey")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    app = load_json(Path(args.app_intelligence)) if args.app_intelligence else None
    behavioral = load_json(Path(args.behavioral)) if args.behavioral else None
    if app is None or behavioral is None:
        raise SystemExit("--app-intelligence and --behavioral are required")
    journey = load_json(Path(args.journey_crawl)) if args.journey_crawl else None
    report = build_report(app, behavioral, journey)
    write_report(Path(args.output_dir), "user-journey", report, markdown(report))
    print(json.dumps({"lab_version": LAB_VERSION, **report["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
