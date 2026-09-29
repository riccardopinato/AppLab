#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from interaction_crawler import (
    Candidate,
    ObservationError,
    adb_capture,
    app_crashed,
    hierarchy_signature,
    parse_candidates,
    relaunch,
    run,
)

SCHEMA_VERSION = 1
CRAWLER_VERSION = "3.3.0"


def stable_signature(path: Path, package_id: str) -> dict[str, Any]:
    raw = hierarchy_signature(path, package_id)
    normalized_texts: list[str] = []
    for text in raw.get("texts", []):
        value = "".join("#" if char.isdigit() else char for char in str(text))
        value = " ".join(value.split())
        if value and value not in normalized_texts:
            normalized_texts.append(value)
    return {
        "clickable": int(raw.get("clickable", 0) or 0),
        "texts": normalized_texts[:60],
    }


def state_id(signature: dict[str, Any]) -> str:
    payload = json.dumps(signature, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def step_key(step: dict[str, str]) -> tuple[str, str]:
    return (str(step.get("label", "")).strip().lower(), str(step.get("class_name", "")).strip())


def select_candidate(candidates: list[Candidate], step: dict[str, str]) -> Candidate | None:
    wanted_label, wanted_class = step_key(step)
    for candidate in candidates:
        if candidate.label.strip().lower() == wanted_label and (
            not wanted_class or candidate.class_name == wanted_class
        ):
            return candidate
    for candidate in candidates:
        if candidate.label.strip().lower() == wanted_label:
            return candidate
    return None


def replay_path(
    package_id: str,
    path: list[dict[str, str]],
    settle: float,
) -> tuple[bool, str]:
    relaunch(package_id, settle)
    crashed, reason = app_crashed(package_id)
    if crashed:
        return False, reason
    if not path:
        return True, ""

    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        for index, step in enumerate(path, start=1):
            try:
                _, xml = adb_capture(temp, f"replay-{index:02d}")
            except ObservationError as exc:
                return False, str(exc)
            candidates = parse_candidates(xml, package_id, max_candidates=20)
            candidate = select_candidate(candidates, step)
            if candidate is None:
                return False, f"unable to replay safe action: {step.get('label','')}"
            run(
                "adb",
                "shell",
                "input",
                "tap",
                str(candidate.x),
                str(candidate.y),
                check=False,
            )
            time.sleep(settle)
            crashed, reason = app_crashed(package_id)
            if crashed:
                return False, reason
    return True, ""


def path_labels(path: list[dict[str, str]]) -> list[str]:
    return [str(step.get("label", "")) for step in path]


def crawl_journeys(
    package_id: str,
    report_dir: Path,
    *,
    max_depth: int,
    max_states: int,
    max_transitions: int,
    max_actions_per_state: int,
    settle: float,
) -> dict[str, Any]:
    evidence = report_dir / "journey-crawl"
    evidence.mkdir(parents=True, exist_ok=True)

    queue: deque[dict[str, Any]] = deque()
    states: dict[str, dict[str, Any]] = {}
    transitions: list[dict[str, Any]] = []
    explored: set[str] = set()
    transition_keys: set[tuple[str, str, str]] = set()
    failures = 0
    warnings = 0
    counter = 0

    ok, reason = replay_path(package_id, [], settle)
    if not ok:
        return {
            "schema_version": SCHEMA_VERSION,
            "journey_crawler_version": CRAWLER_VERSION,
            "result": "FAIL",
            "package_id": package_id,
            "reason": reason,
            "states": [],
            "transitions": [],
            "failures": 1,
            "warnings": 0,
            "guardrails": {
                "safe_actions_only": True,
                "bounded_depth": max_depth,
                "bounded_states": max_states,
                "bounded_transitions": max_transitions,
            },
        }

    try:
        root_screen, root_xml = adb_capture(evidence, "state-000-root")
    except ObservationError as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "journey_crawler_version": CRAWLER_VERSION,
            "result": "WARN",
            "package_id": package_id,
            "reason": str(exc),
            "states": [],
            "transitions": [],
            "failures": 0,
            "warnings": 1,
            "guardrails": {
                "safe_actions_only": True,
                "bounded_depth": max_depth,
                "bounded_states": max_states,
                "bounded_transitions": max_transitions,
            },
        }

    root_sig = stable_signature(root_xml, package_id)
    root_id = state_id(root_sig)
    root_candidates = parse_candidates(root_xml, package_id, max_candidates=20)
    root_state = {
        "id": root_id,
        "depth": 0,
        "path": [],
        "path_labels": [],
        "safe_candidate_count": len(root_candidates),
        "screenshot": str(root_screen.relative_to(report_dir)),
        "ui_hierarchy": str(root_xml.relative_to(report_dir)),
        "signature": root_sig,
        "first_seen_order": 0,
    }
    states[root_id] = root_state
    queue.append({"state_id": root_id, "depth": 0, "path": []})

    while queue and len(transitions) < max_transitions:
        current = queue.popleft()
        source_id = str(current["state_id"])
        depth = int(current["depth"])
        path = list(current["path"])
        if source_id in explored:
            continue
        explored.add(source_id)

        ok, reason = replay_path(package_id, path, settle)
        if not ok:
            warnings += 1
            states[source_id]["replay_warning"] = reason
            continue

        try:
            _, source_xml = adb_capture(evidence, f"explore-{len(explored):03d}-source")
        except ObservationError as exc:
            warnings += 1
            states[source_id]["capture_warning"] = str(exc)
            continue

        source_sig = stable_signature(source_xml, package_id)
        actual_source_id = state_id(source_sig)
        if actual_source_id != source_id:
            warnings += 1
            states[source_id]["stability_warning"] = (
                f"replayed state changed from {source_id} to {actual_source_id}"
            )

        all_candidates = parse_candidates(source_xml, package_id, max_candidates=20)
        states[source_id]["safe_candidate_count"] = len(all_candidates)
        states[source_id]["safe_dead_end_candidate"] = len(all_candidates) == 0

        if depth >= max_depth:
            states[source_id]["depth_boundary_reached"] = True
            continue

        for candidate in all_candidates[:max_actions_per_state]:
            if len(transitions) >= max_transitions:
                break

            action = {
                "label": candidate.label,
                "class_name": candidate.class_name,
            }
            key = (source_id, candidate.label.lower(), candidate.class_name)
            if key in transition_keys:
                continue
            transition_keys.add(key)

            ok, reason = replay_path(package_id, path, settle)
            if not ok:
                warnings += 1
                transitions.append(
                    {
                        "from": source_id,
                        "to": None,
                        "depth": depth + 1,
                        "action": action,
                        "status": "REPLAY_WARN",
                        "state_changed": False,
                        "reason": reason,
                        "screenshot": None,
                        "ui_hierarchy": None,
                        "target_seen_before": False,
                    }
                )
                continue

            with tempfile.TemporaryDirectory() as raw:
                temp = Path(raw)
                try:
                    _, current_xml = adb_capture(temp, "before-action")
                except ObservationError as exc:
                    warnings += 1
                    transitions.append(
                        {
                            "from": source_id,
                            "to": None,
                            "depth": depth + 1,
                            "action": action,
                            "status": "OBSERVATION_WARN",
                            "state_changed": False,
                            "reason": str(exc),
                            "screenshot": None,
                            "ui_hierarchy": None,
                            "target_seen_before": False,
                        }
                    )
                    continue
                current_candidates = parse_candidates(current_xml, package_id, max_candidates=20)
                selected = select_candidate(current_candidates, action)
                if selected is None:
                    warnings += 1
                    transitions.append(
                        {
                            "from": source_id,
                            "to": None,
                            "depth": depth + 1,
                            "action": action,
                            "status": "REPLAY_WARN",
                            "state_changed": False,
                            "reason": "safe action not reproducible after replay",
                            "screenshot": None,
                            "ui_hierarchy": None,
                            "target_seen_before": False,
                        }
                    )
                    continue

            run(
                "adb",
                "shell",
                "input",
                "tap",
                str(selected.x),
                str(selected.y),
                check=False,
            )
            time.sleep(settle)
            crashed, crash_reason = app_crashed(package_id)
            counter += 1
            if crashed:
                failures += 1
                transitions.append(
                    {
                        "from": source_id,
                        "to": None,
                        "depth": depth + 1,
                        "action": action,
                        "status": "FAIL",
                        "state_changed": False,
                        "reason": crash_reason,
                        "screenshot": None,
                        "ui_hierarchy": None,
                        "target_seen_before": False,
                    }
                )
                break

            try:
                screenshot, target_xml = adb_capture(
                    evidence,
                    f"transition-{counter:03d}-after",
                )
            except ObservationError as exc:
                warnings += 1
                transitions.append(
                    {
                        "from": source_id,
                        "to": None,
                        "depth": depth + 1,
                        "action": action,
                        "status": "OBSERVATION_WARN",
                        "state_changed": False,
                        "reason": str(exc),
                        "screenshot": None,
                        "ui_hierarchy": None,
                        "target_seen_before": False,
                    }
                )
                continue

            target_sig = stable_signature(target_xml, package_id)
            target_id = state_id(target_sig)
            changed_state = target_id != source_id
            seen_before = target_id in states
            target_candidates = parse_candidates(target_xml, package_id, max_candidates=20)
            target_path = path + [action]

            transitions.append(
                {
                    "from": source_id,
                    "to": target_id,
                    "depth": depth + 1,
                    "action": action,
                    "status": "CHANGED" if changed_state else "NO_CHANGE",
                    "state_changed": changed_state,
                    "reason": None,
                    "screenshot": str(screenshot.relative_to(report_dir)),
                    "ui_hierarchy": str(target_xml.relative_to(report_dir)),
                    "target_seen_before": seen_before,
                }
            )

            if changed_state and not seen_before and len(states) < max_states:
                states[target_id] = {
                    "id": target_id,
                    "depth": depth + 1,
                    "path": target_path,
                    "path_labels": path_labels(target_path),
                    "safe_candidate_count": len(target_candidates),
                    "safe_dead_end_candidate": len(target_candidates) == 0,
                    "screenshot": str(screenshot.relative_to(report_dir)),
                    "ui_hierarchy": str(target_xml.relative_to(report_dir)),
                    "signature": target_sig,
                    "first_seen_order": len(states),
                }
                queue.append(
                    {
                        "state_id": target_id,
                        "depth": depth + 1,
                        "path": target_path,
                    }
                )

        if failures:
            break

    state_rows = sorted(
        states.values(),
        key=lambda row: (int(row.get("depth", 0)), int(row.get("first_seen_order", 0))),
    )
    if failures:
        result = "FAIL"
    elif warnings:
        result = "WARN"
    elif transitions:
        result = "PASS"
    else:
        result = "SKIPPED"

    return {
        "schema_version": SCHEMA_VERSION,
        "journey_crawler_version": CRAWLER_VERSION,
        "result": result,
        "package_id": package_id,
        "reason": None,
        "root_state": root_id,
        "max_depth": max_depth,
        "max_states": max_states,
        "max_transitions": max_transitions,
        "states": state_rows,
        "transitions": transitions,
        "summary": {
            "states_observed": len(state_rows),
            "transitions_observed": len(transitions),
            "changed_transitions": sum(1 for row in transitions if row.get("state_changed")),
            "no_change_transitions": sum(1 for row in transitions if row.get("status") == "NO_CHANGE"),
            "repeat_targets": sum(1 for row in transitions if row.get("target_seen_before")),
            "safe_dead_end_candidates": sum(
                1 for row in state_rows if row.get("safe_dead_end_candidate")
            ),
            "max_observed_depth": max(
                (int(row.get("depth", 0)) for row in state_rows),
                default=0,
            ),
        },
        "failures": failures,
        "warnings": warnings,
        "guardrails": {
            "safe_actions_only": True,
            "destructive_purchase_send_actions_denied": True,
            "replay_uses_safe_labels": True,
            "bounded_depth": max_depth,
            "bounded_states": max_states,
            "bounded_transitions": max_transitions,
            "safe_dead_end_does_not_prove_product_dead_end": True,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# AppLab Safe Journey Crawler",
        "",
        f"- Result: **{report.get('result','UNKNOWN')}**",
        f"- States observed: **{summary.get('states_observed',0)}**",
        f"- Transitions observed: **{summary.get('transitions_observed',0)}**",
        f"- Max observed depth: **{summary.get('max_observed_depth',0)}**",
        f"- No-change transitions: **{summary.get('no_change_transitions',0)}**",
        f"- Safe dead-end candidates: **{summary.get('safe_dead_end_candidates',0)}**",
        "",
        "## Observed paths",
        "",
    ]
    for state in report.get("states", [])[:20]:
        if not isinstance(state, dict) or not state.get("path_labels"):
            continue
        lines.append(
            f"- depth {state.get('depth',0)} · " + " → ".join(state.get("path_labels", []))
        )
    return "\n".join(lines)


def self_test() -> None:
    sig_a = {"clickable": 2, "texts": ["home", "settings"]}
    sig_b = {"clickable": 2, "texts": ["settings", "home"]}
    assert state_id(sig_a) != state_id(sig_b)
    candidates = [
        Candidate("Settings", "android.widget.Button", (0, 0, 100, 100), 50, 50),
        Candidate("Profile", "android.widget.Button", (0, 100, 100, 200), 50, 150),
    ]
    assert select_candidate(
        candidates,
        {"label": "Settings", "class_name": "android.widget.Button"},
    ) == candidates[0]
    assert select_candidate(candidates, {"label": "Missing", "class_name": ""}) is None
    assert path_labels(
        [
            {"label": "Settings", "class_name": "A"},
            {"label": "Profile", "class_name": "B"},
        ]
    ) == ["Settings", "Profile"]
    print("AppLab Safe Journey Crawler self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id")
    parser.add_argument("--report-dir")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--max-states", type=int, default=8)
    parser.add_argument("--max-transitions", type=int, default=12)
    parser.add_argument("--max-actions-per-state", type=int, default=3)
    parser.add_argument("--settle-seconds", type=float, default=1.2)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.package_id or not args.report_dir:
        raise SystemExit("--package-id and --report-dir are required")

    report = crawl_journeys(
        args.package_id,
        Path(args.report_dir),
        max_depth=max(1, min(args.max_depth, 3)),
        max_states=max(2, min(args.max_states, 12)),
        max_transitions=max(2, min(args.max_transitions, 20)),
        max_actions_per_state=max(1, min(args.max_actions_per_state, 4)),
        settle=max(0.5, min(args.settle_seconds, 4.0)),
    )
    report_dir = Path(args.report_dir)
    (report_dir / "journey-crawl.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "journey-crawl.md").write_text(
        markdown(report).rstrip() + "\n",
        encoding="utf-8",
    )
    print(f"AppLab Safe Journey Crawler: {report['result']}")
    return 2 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
