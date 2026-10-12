#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENGINE_VERSION = "5.3.5"
RECORD_TYPE = "MULTI_PROJECT_DELTA_CALIBRATION"
AUTHORITY = "APPLAB_DELTA_CALIBRATION_ADVISORY"

MIN_REPOSITORIES = 4
MIN_TOTAL_SHADOW_RUNS = 20
MIN_SHADOW_RUNS_PER_REPOSITORY = 3
MIN_CHANGE_CATEGORIES = 3
MIN_LAB_SAFE_OBSERVATIONS = 8
MIN_LAB_REPOSITORIES = 3

LABS = (
    "system",
    "performance",
    "network",
    "persistence",
    "configuration",
    "resource_pressure",
    "background",
    "storage",
    "upgrade",
)
ISSUE_STATES = {"WARN", "FAIL", "ERROR"}
SAFE_STATE = "PASS"
MISSING_BASELINE_STATE = "NO_BASELINE"


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 0


def _shadow_record(row: dict[str, Any]) -> dict[str, Any] | None:
    calibration = row.get("shadow_calibration")
    if not isinstance(calibration, dict):
        return None
    metrics = row.get("pipeline_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    if not bool(row.get("shadow_full", metrics.get("shadow_full", False))):
        return None
    if calibration.get("shadow_full") is not True:
        return None
    return calibration


def _change_category(row: dict[str, Any]) -> str:
    playbook = row.get("playbook")
    if not isinstance(playbook, dict):
        return "unknown"
    value = str(playbook.get("category", "")).strip().lower()
    return value or "unknown"


def _lab_template() -> dict[str, Any]:
    return {
        "skip_observations": 0,
        "safe_pass": 0,
        "warn": 0,
        "fail_or_error": 0,
        "missing_baseline": 0,
        "repositories": set(),
        "change_categories": set(),
    }


def _candidate_state(record: dict[str, Any]) -> str:
    if record["warn"] or record["fail_or_error"]:
        return "UNSAFE"
    if record["missing_baseline"]:
        return "EVIDENCE_INCOMPLETE"
    if (
        record["safe_pass"] >= MIN_LAB_SAFE_OBSERVATIONS
        and len(record["repositories"]) >= MIN_LAB_REPOSITORIES
    ):
        return "EVIDENCE_CANDIDATE"
    return "COLLECTING"


def build_report(history: list[dict[str, Any]]) -> dict[str, Any]:
    repository_runs: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    lab_stats: dict[str, dict[str, Any]] = {lab: _lab_template() for lab in LABS}

    shadow_runs = 0
    false_negatives = 0
    missed_warnings = 0
    missing_baselines = 0
    over_selections = 0

    for row in history:
        if not isinstance(row, dict):
            continue
        calibration = _shadow_record(row)
        if calibration is None:
            continue

        repository = str(row.get("repository", "")).strip()
        if not repository:
            continue
        category = _change_category(row)

        shadow_runs += 1
        repository_runs[repository] += 1
        categories[category] += 1
        false_negatives += _int(calibration.get("false_negative_count"))
        missed_warnings += _int(calibration.get("missed_warning_count"))
        missing_baselines += _int(calibration.get("missing_baseline_count"))
        over_selections += _int(calibration.get("over_selection_count"))

        divergences = calibration.get("divergences")
        if not isinstance(divergences, list):
            continue
        for divergence in divergences:
            if not isinstance(divergence, dict):
                continue
            if divergence.get("kind") != "predicted_skip_but_full_executed":
                continue
            lab = str(divergence.get("lab", "")).strip()
            if lab not in lab_stats:
                continue
            actual = str(divergence.get("actual", "")).strip().upper()
            record = lab_stats[lab]
            record["skip_observations"] += 1
            record["repositories"].add(repository)
            record["change_categories"].add(category)
            if actual == SAFE_STATE:
                record["safe_pass"] += 1
            elif actual == "WARN":
                record["warn"] += 1
            elif actual in {"FAIL", "ERROR"}:
                record["fail_or_error"] += 1
            elif actual == MISSING_BASELINE_STATE:
                record["missing_baseline"] += 1

    qualified_repositories = sorted(
        repository
        for repository, count in repository_runs.items()
        if count >= MIN_SHADOW_RUNS_PER_REPOSITORY
    )
    observed_categories = sorted(
        category for category, count in categories.items() if count > 0 and category != "unknown"
    )

    serialized_labs: dict[str, dict[str, Any]] = {}
    lab_candidates: list[str] = []
    unsafe_labs: list[str] = []
    incomplete_labs: list[str] = []
    for lab in LABS:
        record = lab_stats[lab]
        state = _candidate_state(record)
        if state == "EVIDENCE_CANDIDATE":
            lab_candidates.append(lab)
        elif state == "UNSAFE":
            unsafe_labs.append(lab)
        elif state == "EVIDENCE_INCOMPLETE":
            incomplete_labs.append(lab)
        serialized_labs[lab] = {
            "state": state,
            "skip_observations": record["skip_observations"],
            "safe_pass": record["safe_pass"],
            "warn": record["warn"],
            "fail_or_error": record["fail_or_error"],
            "missing_baseline": record["missing_baseline"],
            "repositories": sorted(record["repositories"]),
            "repository_count": len(record["repositories"]),
            "change_categories": sorted(record["change_categories"]),
        }

    diversity_ready = (
        len(qualified_repositories) >= MIN_REPOSITORIES
        and shadow_runs >= MIN_TOTAL_SHADOW_RUNS
        and len(observed_categories) >= MIN_CHANGE_CATEGORIES
    )
    safety_clear = false_negatives == 0 and missed_warnings == 0
    if not safety_clear:
        state = "UNSAFE"
    elif diversity_ready:
        state = "READY_FOR_EXPERIMENT"
    else:
        state = "COLLECTING"

    readiness = {
        "repository_diversity_ready": len(qualified_repositories) >= MIN_REPOSITORIES,
        "shadow_sample_ready": shadow_runs >= MIN_TOTAL_SHADOW_RUNS,
        "change_diversity_ready": len(observed_categories) >= MIN_CHANGE_CATEGORIES,
        "safety_clear": safety_clear,
        "ready_for_controlled_experiment": state == "READY_FOR_EXPERIMENT",
        "thresholds": {
            "min_repositories": MIN_REPOSITORIES,
            "min_total_shadow_runs": MIN_TOTAL_SHADOW_RUNS,
            "min_shadow_runs_per_repository": MIN_SHADOW_RUNS_PER_REPOSITORY,
            "min_change_categories": MIN_CHANGE_CATEGORIES,
            "min_lab_safe_observations": MIN_LAB_SAFE_OBSERVATIONS,
            "min_lab_repositories": MIN_LAB_REPOSITORIES,
        },
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "record_type": RECORD_TYPE,
        "authority": AUTHORITY,
        "state": state,
        "coverage_reduction_enabled": False,
        "summary": {
            "repositories": len(repository_runs),
            "qualified_repositories": len(qualified_repositories),
            "shadow_runs": shadow_runs,
            "change_categories": len(observed_categories),
            "false_negatives": false_negatives,
            "missed_warnings": missed_warnings,
            "missing_baselines": missing_baselines,
            "over_selections": over_selections,
            "lab_candidates": len(lab_candidates),
            "unsafe_labs": len(unsafe_labs),
            "incomplete_labs": len(incomplete_labs),
        },
        "repository_shadow_runs": dict(sorted(repository_runs.items())),
        "qualified_repositories": qualified_repositories,
        "change_category_runs": dict(sorted(categories.items())),
        "lab_observations": serialized_labs,
        "lab_candidates": lab_candidates,
        "unsafe_labs": unsafe_labs,
        "incomplete_labs": incomplete_labs,
        "readiness": readiness,
        "guardrails": {
            "advisory_only": True,
            "coverage_reduction_enabled": False,
            "smart_test_plan_remains_single_authority": True,
            "fast_full_certification_authority_unchanged": True,
            "shadow_full_evidence_required_for_calibration": True,
            "ready_for_experiment_is_not_permission_to_reduce_coverage": True,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    readiness = report["readiness"]
    candidates = report["lab_candidates"]
    unsafe = report["unsafe_labs"]
    lines = [
        "# AppLab Multi-Project Delta Calibration",
        "",
        f"- State: **{report['state']}**",
        "- Coverage reduction: **DISABLED**",
        f"- Qualified repositories: **{summary['qualified_repositories']}/{summary['repositories']}**",
        f"- Shadow FULL samples: **{summary['shadow_runs']}**",
        f"- Observed change categories: **{summary['change_categories']}**",
        f"- False negatives: **{summary['false_negatives']}**",
        f"- Missed warnings: **{summary['missed_warnings']}**",
        f"- Missing baselines: **{summary['missing_baselines']}**",
        f"- Over-selection observations: **{summary['over_selections']}**",
        "",
        "## Readiness",
        "",
        f"- Repository diversity: **{'READY' if readiness['repository_diversity_ready'] else 'COLLECTING'}**",
        f"- Shadow sample volume: **{'READY' if readiness['shadow_sample_ready'] else 'COLLECTING'}**",
        f"- Change diversity: **{'READY' if readiness['change_diversity_ready'] else 'COLLECTING'}**",
        f"- Safety: **{'CLEAR' if readiness['safety_clear'] else 'UNSAFE'}**",
        "",
        "## Lab evidence",
        "",
        f"- Evidence candidates: **{', '.join(candidates) if candidates else 'none'}**",
        f"- Unsafe labs: **{', '.join(unsafe) if unsafe else 'none'}**",
        "",
        "A READY_FOR_EXPERIMENT state only authorizes a future controlled experiment proposal. "
        "It never changes Smart Test Plan selection or FAST/FULL/CERTIFICATION coverage.",
        "",
    ]
    return "\n".join(lines)


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _fixture_row(repository: str, category: str, actual: str = "PASS") -> dict[str, Any]:
    lab = "network"
    calibration = {
        "schema_version": 2,
        "shadow_full": True,
        "divergences": [
            {"lab": lab, "actual": actual, "kind": "predicted_skip_but_full_executed"}
        ],
        "false_negative_count": 1 if actual in {"FAIL", "ERROR"} else 0,
        "missed_warning_count": 1 if actual == "WARN" else 0,
        "missing_baseline_count": 1 if actual == "NO_BASELINE" else 0,
        "over_selection_count": 0,
    }
    return {
        "repository": repository,
        "shadow_full": True,
        "playbook": {"category": category},
        "shadow_calibration": calibration,
        "pipeline_metrics": {"shadow_full": True},
    }


def self_test() -> None:
    collecting = build_report(
        [_fixture_row("owner/one", "ui_change") for _ in range(5)]
        + [_fixture_row("owner/two", "database_migration") for _ in range(5)]
    )
    assert collecting["state"] == "COLLECTING"
    assert collecting["coverage_reduction_enabled"] is False

    rows: list[dict[str, Any]] = []
    categories = ("ui_change", "database_migration", "general_code_change", "release_ops")
    for repo_index in range(4):
        repository = f"owner/app-{repo_index}"
        for run_index in range(5):
            rows.append(_fixture_row(repository, categories[(repo_index + run_index) % len(categories)]))
    ready = build_report(rows)
    assert ready["state"] == "READY_FOR_EXPERIMENT"
    assert ready["readiness"]["ready_for_controlled_experiment"] is True
    assert ready["coverage_reduction_enabled"] is False
    assert ready["lab_observations"]["network"]["state"] == "EVIDENCE_CANDIDATE"

    unsafe_rows = rows + [_fixture_row("owner/app-0", "ui_change", "WARN")]
    unsafe = build_report(unsafe_rows)
    assert unsafe["state"] == "UNSAFE"
    assert unsafe["summary"]["missed_warnings"] == 1
    assert unsafe["lab_observations"]["network"]["state"] == "UNSAFE"

    incomplete_rows = rows + [_fixture_row("owner/app-0", "ui_change", "NO_BASELINE")]
    incomplete = build_report(incomplete_rows)
    assert incomplete["lab_observations"]["network"]["state"] == "EVIDENCE_INCOMPLETE"
    assert incomplete["lab_observations"]["network"]["safe_pass"] == 20

    with tempfile.TemporaryDirectory(prefix="applab-delta-calibration-") as raw:
        history = Path(raw) / "history.jsonl"
        history.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
            encoding="utf-8",
        )
        from_file = build_report(read_history(history))
        assert from_file == ready

    print("AppLab v5.3.5 multi-project delta calibration self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-file", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.history_file:
        raise SystemExit("--history-file is required")

    report = build_report(read_history(Path(args.history_file)))
    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.output_md:
        Path(args.output_md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
