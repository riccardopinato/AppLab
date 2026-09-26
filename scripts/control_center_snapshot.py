#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def build_snapshot(
    watchlist: dict[str, Any],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    configured = {
        str(item.get("repository")): item
        for item in watchlist.get("repositories", [])
        if isinstance(item, dict) and item.get("enabled", True)
    }

    latest: dict[str, dict[str, Any]] = {}
    latest_release: dict[str, dict[str, Any]] = {}
    latest_certification: dict[str, dict[str, Any]] = {}
    for item in history:
        repository = str(item.get("repository", "")).strip()
        if not repository:
            continue
        current = latest.get(repository)
        if current is None or str(item.get("recorded_at", "")) >= str(
            current.get("recorded_at", "")
        ):
            latest[repository] = item
        certification_status = str(item.get("certification_status", "")).strip()
        if certification_status in {"CERTIFIED", "BLOCKED", "NOT_CERTIFIED"}:
            previous_certification = latest_certification.get(repository)
            if previous_certification is None or str(item.get("recorded_at", "")) >= str(
                previous_certification.get("recorded_at", "")
            ):
                latest_certification[repository] = item

        release = item.get("release")
        if isinstance(release, dict) and release.get("artifact_url"):
            previous_release = latest_release.get(repository)
            if previous_release is None or str(item.get("recorded_at", "")) >= str(
                previous_release.get("recorded_at", "")
            ):
                latest_release[repository] = item

    repositories = sorted(set(configured) | set(latest))
    projects: list[dict[str, Any]] = []
    for repository in repositories:
        config = configured.get(repository, {})
        result = latest.get(repository, {})
        certification_result = latest_certification.get(repository, {})
        raw_certification_status = certification_result.get(
            "certification_status", "NOT_REQUESTED"
        )
        certified_sha = str(certification_result.get("resolved_sha", ""))
        latest_sha = str(result.get("resolved_sha", ""))
        if raw_certification_status == "CERTIFIED":
            certification_display_status = (
                "CERTIFIED_CURRENT"
                if certified_sha and latest_sha and certified_sha == latest_sha
                else "CERTIFIED_STALE"
            )
        else:
            certification_display_status = raw_certification_status

        projects.append(
            {
                "repository": repository,
                "key": config.get("key", result.get("history_key", "")),
                "engine": config.get("engine", result.get("engine", "unknown")),
                "ref": config.get("ref", result.get("ref", "main")),
                "enabled": bool(config.get("enabled", True)),
                "resolved_sha": result.get("resolved_sha", ""),
                "result": result.get("result", "NOT_RUN"),
                "maestro": result.get("maestro", "—"),
                "visual_qa": result.get("visual_qa", "—"),
                "visual_regression": result.get("visual_regression", "—"),
                "visual_journey": result.get("visual_journey", "—"),
                "interaction_crawl": result.get("interaction_crawl", "—"),
                "system_lab": result.get("system_lab", "—"),
                "network_lab": result.get("network_lab", "—"),
                "persistence_lab": result.get("persistence_lab", "—"),
                "configuration_lab": result.get("configuration_lab", "—"),
                "resource_pressure_lab": result.get("resource_pressure_lab", "—"),
                "background_lab": result.get("background_lab", "—"),
                "storage_lab": result.get("storage_lab", "—"),
                "upgrade_lab": result.get("upgrade_lab", "—"),
                "performance_lab": result.get("performance_lab", "—"),
                "performance": result.get("performance", {}),
                "applab_version": result.get("applab_version", ""),
                "analysis_mode": result.get("analysis_mode", "full"),
                "analysis_lane": result.get("analysis_lane", ""),
                "risk_score": result.get("risk_score"),
                "risk_level": result.get("risk_level", ""),
                "confidence": result.get("confidence"),
                "shadow_full": bool(result.get("shadow_full", False)),
                "shadow_calibration": result.get("shadow_calibration", {}),
                "runtime_changed": result.get("runtime_changed"),
                "certification_status": raw_certification_status,
                "certification_display_status": certification_display_status,
                "certification": certification_result.get("certification", {}),
                "certified_sha": certified_sha,
                "recorded_at": result.get("recorded_at", ""),
                "watcher_run_id": result.get("watcher_run_id", ""),
                "watcher_run_url": result.get("watcher_run_url", ""),
                "release": result.get("release", {}) or latest_release.get(repository, {}).get("release", {}),
            }
        )

    pass_count = sum(1 for item in projects if item["result"] == "PASS")
    fail_count = sum(1 for item in projects if item["result"] == "FAIL")
    not_run_count = len(projects) - pass_count - fail_count
    certified_count = sum(
        1 for item in projects if item["certification_status"] == "CERTIFIED"
    )
    certified_current_count = sum(
        1 for item in projects if item["certification_display_status"] == "CERTIFIED_CURRENT"
    )
    certified_stale_count = sum(
        1 for item in projects if item["certification_display_status"] == "CERTIFIED_STALE"
    )
    certification_blocked_count = sum(
        1 for item in projects if item["certification_status"] == "BLOCKED"
    )
    not_certified_count = sum(
        1 for item in projects if item["certification_status"] == "NOT_CERTIFIED"
    )
    fast_runtime_count = sum(1 for item in projects if item.get("analysis_lane") == "FAST_RUNTIME")
    full_runtime_count = sum(1 for item in projects if item.get("analysis_lane") == "FULL_RUNTIME")
    source_only_count = sum(1 for item in projects if item.get("analysis_lane") == "NO_RUNTIME_CHANGE")
    static_only_count = sum(1 for item in projects if item.get("analysis_lane") == "STATIC_ONLY")
    shadow_sample_count = sum(1 for item in projects if item.get("shadow_full"))

    recent = sorted(
        (
            {
                key: value
                for key, value in item.items()
                if key
                in {
                    "recorded_at",
                    "repository",
                    "resolved_sha",
                    "result",
                    "engine",
                    "maestro",
                    "visual_qa",
                    "visual_regression",
                    "visual_journey",
                    "interaction_crawl",
                    "system_lab",
                    "network_lab",
                    "persistence_lab",
                    "configuration_lab",
                    "resource_pressure_lab",
                    "background_lab",
                    "storage_lab",
                    "upgrade_lab",
                    "performance_lab",
                    "performance",
                    "watcher_run_id",
                    "watcher_run_url",
                    "applab_version",
                    "analysis_mode",
                    "analysis_lane",
                    "risk_score",
                    "risk_level",
                    "confidence",
                    "shadow_full",
                    "shadow_calibration",
                    "runtime_changed",
                    "certification_status",
                    "certification",
                    "release",
                }
            }
            for item in history
        ),
        key=lambda item: str(item.get("recorded_at", "")),
        reverse=True,
    )[:50]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "projects": len(projects),
            "pass": pass_count,
            "fail": fail_count,
            "not_run": not_run_count,
            "certified": certified_count,
            "certified_current": certified_current_count,
            "certified_stale": certified_stale_count,
            "certification_blocked": certification_blocked_count,
            "not_certified": not_certified_count,
            "fast_runtime": fast_runtime_count,
            "full_runtime": full_runtime_count,
            "source_only": source_only_count,
            "static_only": static_only_count,
            "shadow_samples": shadow_sample_count,
        },
        "projects": projects,
        "recent": recent,
    }


def self_test() -> None:
    watchlist = {
        "repositories": [
            {
                "key": "one",
                "repository": "owner/one",
                "engine": "flutter",
                "enabled": True,
            },
            {
                "key": "two",
                "repository": "owner/two",
                "engine": "auto",
                "enabled": True,
            },
        ]
    }
    history = [
        {
            "repository": "owner/one",
            "recorded_at": "2026-01-01T00:00:00Z",
            "result": "FAIL",
            "resolved_sha": "old",
        },
        {
            "repository": "owner/one",
            "recorded_at": "2026-01-02T00:00:00Z",
            "result": "PASS",
            "resolved_sha": "full",
            "applab_version": "0.9.0",
            "analysis_mode": "certification",
            "certification_status": "CERTIFIED",
            "certification": {
                "status": "CERTIFIED",
                "certified": True,
                "matrix": [{"api_level": "35", "emulator_profile": "pixel_7_pro"}],
            },
            "release": {"artifact_url": "https://example.test/artifact"},
            "network_lab": "PASS",
            "persistence_lab": "PASS",
            "configuration_lab": "PASS",
            "resource_pressure_lab": "PASS",
            "background_lab": "PASS",
            "storage_lab": "PASS",
            "upgrade_lab": "PASS",
            "performance_lab": "PASS",
            "performance": {
                "startup": {"cold": {"total_time_ms": 850}},
                "memory": {"pss_kb": 123456},
            },
        },
        {
            "repository": "owner/one",
            "recorded_at": "2026-01-03T00:00:00Z",
            "result": "PASS",
            "resolved_sha": "fast",
            "applab_version": "0.9.0",
            "analysis_mode": "fast",
            "analysis_lane": "FAST_RUNTIME",
            "risk_score": 32,
            "risk_level": "LOW",
            "confidence": 0.94,
            "shadow_full": False,
            "runtime_changed": True,
            "network_lab": "SKIPPED",
            "persistence_lab": "SKIPPED",
            "configuration_lab": "PASS",
            "resource_pressure_lab": "SKIPPED",
            "background_lab": "SKIPPED",
            "storage_lab": "SKIPPED",
            "upgrade_lab": "NO_BASELINE",
            "performance_lab": "PASS"
        },
    ]
    snapshot = build_snapshot(watchlist, history)
    assert snapshot["summary"] == {
        "projects": 2,
        "pass": 1,
        "fail": 0,
        "not_run": 1,
        "certified": 1,
        "certified_current": 0,
        "certified_stale": 1,
        "certification_blocked": 0,
        "not_certified": 0,
        "fast_runtime": 1,
        "full_runtime": 0,
        "source_only": 0,
        "static_only": 0,
        "shadow_samples": 0,
    }
    first = next(
        item for item in snapshot["projects"] if item["repository"] == "owner/one"
    )
    assert first["resolved_sha"] == "fast"
    assert first["analysis_mode"] == "fast"
    assert first["analysis_lane"] == "FAST_RUNTIME"
    assert first["risk_score"] == 32
    assert first["confidence"] == 0.94
    assert first["certification_status"] == "CERTIFIED"
    assert first["certification_display_status"] == "CERTIFIED_STALE"
    assert first["certified_sha"] == "full"
    assert first["release"]["artifact_url"] == "https://example.test/artifact"
    assert first["network_lab"] == "SKIPPED"
    assert first["persistence_lab"] == "SKIPPED"
    assert first["configuration_lab"] == "PASS"
    assert first["resource_pressure_lab"] == "SKIPPED"
    assert first["background_lab"] == "SKIPPED"
    assert first["storage_lab"] == "SKIPPED"
    assert first["upgrade_lab"] == "NO_BASELINE"
    assert first["performance_lab"] == "PASS"
    assert first["analysis_mode"] == "fast"
    assert first["release"]["artifact_url"] == "https://example.test/artifact"
    print("AppLab Control Center snapshot self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist")
    parser.add_argument("--history-file")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.watchlist or not args.history_file or not args.output:
        raise SystemExit("--watchlist, --history-file and --output are required")

    watchlist = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    snapshot = build_snapshot(watchlist, read_history(Path(args.history_file)))
    Path(args.output).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"AppLab Control Center snapshot: "
        f"{snapshot['summary']['projects']} projects"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
