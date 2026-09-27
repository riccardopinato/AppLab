#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LABS = (
    "system", "performance", "network", "persistence", "configuration",
    "resource_pressure", "background", "storage", "upgrade",
)
LAB_FIELDS = {
    "system": "system_lab",
    "performance": "performance_lab",
    "network": "network_lab",
    "persistence": "persistence_lab",
    "configuration": "configuration_lab",
    "resource_pressure": "resource_pressure_lab",
    "background": "background_lab",
    "storage": "storage_lab",
    "upgrade": "upgrade_lab",
}
LANE_BUDGETS = {
    "NO_RUNTIME_CHANGE": 120,
    "STATIC_ONLY": 300,
    "FAST_RUNTIME": 900,
    "FULL_RUNTIME": 1800,
    "CERTIFICATION": 2400,
}
EXECUTED = {"PASS", "WARN", "FAIL", "ERROR"}
PLAYBOOK_REQUIRED_LABS = {
    "DATABASE_MIGRATION_PLAYBOOK": ("persistence", "storage", "upgrade"),
    "UI_REDESIGN_PLAYBOOK": ("configuration", "performance"),
    "RELEASE_PLAYBOOK": ("configuration", "performance", "upgrade"),
    "QA_CYCLE_PLAYBOOK": (),
    "DOCUMENTATION_PLAYBOOK": (),
    "NEW_FEATURE_OR_BUG_FIX_PLAYBOOK": (),
}


def _percentile(values: list[float], percentile: float) -> float | None:
    clean = sorted(float(v) for v in values if isinstance(v, (int, float)) and v >= 0)
    if not clean:
        return None
    if len(clean) == 1:
        return round(clean[0], 3)
    position = (len(clean) - 1) * percentile
    lower = int(position)
    upper = min(len(clean) - 1, lower + 1)
    weight = position - lower
    return round(clean[lower] * (1 - weight) + clean[upper] * weight, 3)


def history_rows(
    history_file: str,
    repository: str = "",
    history_key: str = "",
    source_ref: str = "",
    limit: int = 300,
) -> list[dict[str, Any]]:
    if not history_file or not Path(history_file).is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw in Path(history_file).read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if repository and str(item.get("repository", "")).strip() != repository:
            continue
        if history_key and str(item.get("history_key", "")).strip() not in {"", history_key}:
            continue
        item_ref = str(item.get("requested_ref", item.get("ref", ""))).strip()
        if source_ref and item_ref and item_ref != source_ref and len(item_ref) != 40:
            continue
        rows.append(item)
    return rows


def _cross_project_signals(history_file: str) -> list[dict[str, Any]]:
    rows = history_rows(history_file, limit=500)
    signals: list[dict[str, Any]] = []
    for lab in LABS:
        by_repo: dict[str, list[str]] = {}
        field = LAB_FIELDS[lab]
        for item in rows:
            repo = str(item.get("repository", "")).strip()
            outcome = str(item.get(field, "")).upper()
            if repo and outcome in EXECUTED:
                by_repo.setdefault(repo, []).append(outcome)
        affected = 0
        executed = 0
        issues = 0
        for outcomes in by_repo.values():
            local_issues = sum(value in {"WARN", "FAIL", "ERROR"} for value in outcomes)
            executed += len(outcomes)
            issues += local_issues
            if len(outcomes) >= 3 and local_issues:
                affected += 1
        if affected >= 3 and executed >= 10:
            signals.append({
                "lab": lab,
                "repositories": affected,
                "executed": executed,
                "issue_rate": round(issues / max(1, executed), 4),
                "policy": "advisory-only; project evidence remains authoritative",
            })
    return signals


def build_learning_profile(
    history_file: str,
    repository: str = "",
    history_key: str = "",
    source_ref: str = "",
) -> dict[str, Any]:
    rows = history_rows(history_file, repository, history_key, source_ref)
    lab_stats: dict[str, dict[str, Any]] = {}
    unstable_labs: list[str] = []
    elevated_labs: list[str] = []

    for lab in LABS:
        outcomes = [
            str(item.get(LAB_FIELDS[lab], "")).upper()
            for item in rows
            if str(item.get(LAB_FIELDS[lab], "")).upper() in EXECUTED
        ]
        counts = {state: outcomes.count(state) for state in ("PASS", "WARN", "FAIL", "ERROR")}
        executed = len(outcomes)
        failures = counts["FAIL"] + counts["ERROR"]
        bad = failures + counts["WARN"]
        transitions = sum(1 for before, after in zip(outcomes, outcomes[1:]) if before != after)
        transition_rate = round(transitions / max(1, executed - 1), 4) if executed > 1 else 0.0
        failure_rate = round(failures / executed, 4) if executed else 0.0
        warning_rate = round(counts["WARN"] / executed, 4) if executed else 0.0
        issue_rate = round(bad / executed, 4) if executed else 0.0
        unstable = (
            executed >= 5
            and transition_rate >= 0.35
            and "PASS" in outcomes
            and any(value in {"WARN", "FAIL", "ERROR"} for value in outcomes)
        )
        elevated = executed >= 5 and issue_rate >= 0.20
        if unstable:
            unstable_labs.append(lab)
        if elevated:
            elevated_labs.append(lab)
        lab_stats[lab] = {
            "executed": executed,
            "pass": counts["PASS"],
            "warn": counts["WARN"],
            "fail": counts["FAIL"],
            "error": counts["ERROR"],
            "failure_rate": failure_rate,
            "warning_rate": warning_rate,
            "issue_rate": issue_rate,
            "transition_rate": transition_rate,
            "unstable": unstable,
            "elevated": elevated,
        }

    lane_timings: dict[str, list[float]] = {}
    for item in rows:
        metrics = item.get("pipeline_metrics")
        if not isinstance(metrics, dict):
            continue
        lane = str(item.get("analysis_lane") or metrics.get("lane") or "").strip()
        wall = metrics.get("wall_clock_seconds")
        if lane and isinstance(wall, (int, float)) and wall >= 0:
            lane_timings.setdefault(lane, []).append(float(wall))

    lane_metrics = {}
    for lane, values in sorted(lane_timings.items()):
        p95 = _percentile(values, 0.95)
        budget = LANE_BUDGETS.get(lane)
        lane_metrics[lane] = {
            "sample_count": len(values),
            "wall_clock_p50_seconds": _percentile(values, 0.50),
            "wall_clock_p95_seconds": p95,
            "budget_seconds": budget,
            "budget_pressure": bool(budget and p95 is not None and p95 > budget),
        }

    return {
        "schema_version": 1,
        "sample_count": len(rows),
        "repository": repository,
        "history_key": history_key,
        "source_ref": source_ref,
        "lab_stats": lab_stats,
        "unstable_labs": unstable_labs,
        "elevated_labs": elevated_labs,
        "lane_metrics": lane_metrics,
        "cross_project_signals": _cross_project_signals(history_file),
        "learning_ready": len(rows) >= 5,
    }


def classify_change_playbook(changed_files: list[str]) -> dict[str, Any]:
    paths = [str(path).replace("\\", "/").lower() for path in changed_files]
    if not paths:
        category, playbook = "unknown", "QA_CYCLE_PLAYBOOK"
    elif all(
        path.startswith(("docs/", "documentation/", ".github/issue", ".github/pull"))
        or path.rsplit("/", 1)[-1] in {"readme.md", "changelog.md", "license", "license.md"}
        for path in paths
    ):
        category, playbook = "documentation", "DOCUMENTATION_PLAYBOOK"
    elif all(any(part in {"test", "tests", "androidtest"} for part in path.split("/")) for path in paths):
        category, playbook = "tests", "QA_CYCLE_PLAYBOOK"
    elif any("migration" in path or "schema" in path or "database" in path or "/dao" in path for path in paths):
        category, playbook = "database_migration", "DATABASE_MIGRATION_PLAYBOOK"
    elif any(
        token in path
        for path in paths
        for token in ("/ui/", "/screen", "/page", "/widget", "/compose", "/layout", "theme", "design")
    ):
        category, playbook = "ui_change", "UI_REDESIGN_PLAYBOOK"
    elif any(path.startswith(".github/workflows/") or "release" in path or "certification" in path for path in paths):
        category, playbook = "release_ops", "RELEASE_PLAYBOOK"
    else:
        category, playbook = "general_code_change", "NEW_FEATURE_OR_BUG_FIX_PLAYBOOK"
    return {
        "category": category,
        "recommended_playbook": playbook,
        "confidence": 0.95 if category not in {"unknown", "general_code_change"} else 0.70,
    }


def apply_playbook_policy(plan: dict[str, Any], playbook: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(plan)
    selected = dict(enriched.get("selected_labs", {}))
    reasons = {lab: list(values) for lab, values in (enriched.get("reasons") or {}).items()}
    required = PLAYBOOK_REQUIRED_LABS.get(str(playbook.get("recommended_playbook", "")), ())
    if enriched.get("lane") == "FAST_RUNTIME":
        for lab in required:
            if not selected.get(lab):
                selected[lab] = True
            marker = f"SHOS playbook requires {lab} coverage"
            if marker not in reasons.setdefault(lab, []):
                reasons[lab].append(marker)
        if required:
            enriched["risk_score"] = min(100, int(enriched.get("risk_score", 0) or 0) + len(required) * 2)
    enriched["selected_labs"] = selected
    enriched["reasons"] = reasons
    enriched["playbook"] = {
        **playbook,
        "required_labs": list(required),
    }
    return enriched


def apply_learning_profile(plan: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(plan)
    selected = dict(enriched.get("selected_labs", {}))
    reasons = {lab: list(values) for lab, values in (enriched.get("reasons") or {}).items()}
    lane = str(enriched.get("lane", "FULL_RUNTIME"))
    risk = int(enriched.get("risk_score", 100) or 0)
    confidence = float(enriched.get("confidence", 0.0) or 0.0)
    applied: list[str] = []

    if profile.get("learning_ready") and lane == "FAST_RUNTIME":
        stats = profile.get("lab_stats") or {}
        for lab in LABS:
            stat = stats.get(lab) or {}
            if bool(stat.get("elevated")) or bool(stat.get("unstable")):
                if not selected.get(lab):
                    selected[lab] = True
                    reasons.setdefault(lab, []).append("project learning profile elevated this lab")
                    applied.append(lab)
                risk += 4 if bool(stat.get("elevated")) else 2
                if bool(stat.get("unstable")):
                    confidence -= 0.03

        severe = [
            lab for lab in LABS
            if int((stats.get(lab) or {}).get("executed", 0) or 0) >= 5
            and float((stats.get(lab) or {}).get("failure_rate", 0.0) or 0.0) >= 0.40
        ]
        if len(severe) >= 2 or len(applied) >= 4:
            lane = "FULL_RUNTIME"
            selected = {lab: True for lab in LABS}
            enriched["mode"] = "full"
            enriched["fallback_full"] = True
            enriched["run_static"] = True
            enriched["run_build"] = True
            enriched["run_runtime"] = True
            for lab in LABS:
                reasons.setdefault(lab, []).append("project learning profile escalated verification to FULL")
            risk = max(risk, 72)
            confidence = min(confidence, 0.79)

    risk = max(0, min(100, risk))
    confidence = max(0.0, min(1.0, confidence))
    budget = LANE_BUDGETS.get(lane, 1800)
    observed = ((profile.get("lane_metrics") or {}).get(lane) or {})
    enriched.update(
        {
            "lane": lane,
            "selected_labs": selected,
            "reasons": reasons,
            "risk_score": risk,
            "confidence": round(confidence, 3),
            "learning_profile": profile,
            "learning_applied_labs": sorted(set(applied)),
            "verification_budget_seconds": budget,
            "historical_lane_p95_seconds": observed.get("wall_clock_p95_seconds"),
            "budget_pressure": bool(observed.get("budget_pressure", False)),
        }
    )
    return enriched


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "history.jsonl"
        outcomes = ["PASS", "FAIL", "PASS", "WARN", "PASS", "FAIL"]
        rows = [
            {
                "repository": "owner/app",
                "history_key": "main",
                "requested_ref": "main",
                "network_lab": outcome,
                "analysis_lane": "FAST_RUNTIME",
                "pipeline_metrics": {"wall_clock_seconds": 100 + index * 20},
            }
            for index, outcome in enumerate(outcomes)
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        profile = build_learning_profile(str(path), "owner/app", "main", "main")
        assert profile["learning_ready"]
        assert "network" in profile["unstable_labs"]
        plan = {
            "lane": "FAST_RUNTIME",
            "mode": "fast",
            "selected_labs": {lab: False for lab in LABS},
            "reasons": {lab: [] for lab in LABS},
            "risk_score": 20,
            "confidence": 0.95,
        }
        playbook = classify_change_playbook(["lib/ui/home_screen.dart"])
        plan = apply_playbook_policy(plan, playbook)
        assert plan["selected_labs"]["configuration"]
        assert plan["selected_labs"]["performance"]
        enriched = apply_learning_profile(plan, profile)
        assert enriched["selected_labs"]["network"]
        assert enriched["verification_budget_seconds"] == 900
        assert classify_change_playbook(["lib/ui/home_screen.dart"])["category"] == "ui_change"
    print("AppLab history learning self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-file", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--history-key", default="")
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    profile = build_learning_profile(args.history_file, args.repository, args.history_key, args.source_ref)
    if args.output:
        Path(args.output).write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(profile, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
