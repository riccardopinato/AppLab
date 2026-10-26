#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

RETRYABLE_KINDS = {"INFRA_ERROR", "FLAKY_SUSPECT"}
METRIC_FIELDS = ("wall_clock_seconds", "runtime_seconds", "quality_seconds")
INFRA_SIGNATURES = (
    ("WEBRTC_NO_FRAME", ("webrtc", "no decoded", "no frame", "non-black")),
    ("EMULATOR_STARTUP", ("emulator", "boot", "avd")),
    ("ADB_CONNECTION", ("adb", "device offline", "connection")),
    ("RUNNER_INFRA", ("runner", "hosted runner", "kvm")),
    ("NETWORK_INFRA", ("network", "connection reset", "service unavailable", "rate limit")),
    ("CACHE_ARTIFACT", ("cache", "artifact download")),
    ("HOST_STORAGE", ("no space left", "disk")),
)


def read_history(path: Path, max_records: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_records:]:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((percent / 100.0) * len(ordered)))
    return round(float(ordered[rank - 1]), 3)


def failure_kind(row: dict[str, Any]) -> str:
    if str(row.get("result", "")).upper() == "PASS":
        return "NONE"
    failure = row.get("failure_intelligence")
    if not isinstance(failure, dict):
        return "UNKNOWN_FAILURE"
    kind = str(failure.get("kind", "")).strip().upper()
    return kind or "UNKNOWN_FAILURE"


def retry_allowed(row: dict[str, Any]) -> bool:
    failure = row.get("failure_intelligence")
    if not isinstance(failure, dict):
        return False
    return (
        failure_kind(row) in RETRYABLE_KINDS
        and failure.get("retryable") is True
    )


def normalized_signature(row: dict[str, Any]) -> str:
    kind = failure_kind(row)
    if kind == "NONE":
        return "NONE"
    failure = row.get("failure_intelligence")
    failure = failure if isinstance(failure, dict) else {}
    labs = failure.get("failed_labs")
    labs = sorted(str(x) for x in labs) if isinstance(labs, list) else []
    if labs:
        return kind + ":" + ",".join(labs)
    reason = " ".join(
        str(x or "")
        for x in (
            failure.get("reason"),
            row.get("reason"),
            row.get("error"),
            row.get("build_error"),
        )
    ).lower()
    if kind in RETRYABLE_KINDS:
        for name, needles in INFRA_SIGNATURES:
            if any(needle in reason for needle in needles):
                return kind + ":" + name
    return kind + ":GENERAL"


def metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    by_lane: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        metrics = row.get("pipeline_metrics")
        if not isinstance(metrics, dict):
            continue
        lane = str(row.get("analysis_lane", "") or "UNKNOWN")
        for field in METRIC_FIELDS:
            raw = metrics.get(field)
            if not isinstance(raw, (int, float)) or float(raw) < 0:
                continue
            values[field].append(float(raw))
            by_lane[lane][field].append(float(raw))

    def summarize(bucket: dict[str, list[float]]) -> dict[str, Any]:
        return {
            field: {
                "samples": len(bucket.get(field, [])),
                "p50": percentile(bucket.get(field, []), 50),
                "p95": percentile(bucket.get(field, []), 95),
            }
            for field in METRIC_FIELDS
        }

    return {
        "overall": summarize(values),
        "by_lane": {
            lane: summarize(bucket)
            for lane, bucket in sorted(by_lane.items())
        },
    }


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [row for row in rows if failure_kind(row) != "NONE"]
    kind_counts = Counter(failure_kind(row) for row in failures)
    signature_counts = Counter(normalized_signature(row) for row in failures)
    retryable = sum(1 for row in failures if retry_allowed(row))
    unclassified = sum(1 for row in failures if failure_kind(row) == "UNKNOWN_FAILURE")
    recurrent = [
        {"signature": signature, "count": count}
        for signature, count in signature_counts.most_common()
        if count >= 2
    ]
    return {
        "schema_version": 1,
        "authority": "DIAGNOSTIC_ONLY",
        "policy": {
            "auto_retry_kinds": sorted(RETRYABLE_KINDS),
            "unknown_retry": False,
            "failed_attempt_remains_evidence": True,
            "assertions_may_be_weakened": False,
        },
        "summary": {
            "samples": len(rows),
            "failures": len(failures),
            "retryable_failures": retryable,
            "non_retryable_failures": len(failures) - retryable,
            "unknown_failures": unclassified,
            "recurrent_signatures": len(recurrent),
        },
        "failure_kinds": dict(sorted(kind_counts.items())),
        "recurrent_signatures": recurrent[:20],
        "timings": metric_summary(rows),
        "boundaries": [
            "diagnostic classification cannot convert FAIL to PASS",
            "runtime/emulator evidence is not physical-device evidence",
            "physical-device evidence is not distribution/store evidence",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# AppLab v5.6A Runtime Stability",
        "",
        f"- Samples: {s['samples']}",
        f"- Failures: {s['failures']}",
        f"- Targeted-retry eligible: {s['retryable_failures']}",
        f"- Unknown/non-auto-retry: {s['unknown_failures']}",
        f"- Recurrent signatures: {s['recurrent_signatures']}",
        "",
        "## Timing p50 / p95",
        "",
        "| Scope | Metric | Samples | p50 | p95 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    timings = report["timings"]
    for scope, bucket in [("overall", timings["overall"])] + [
        (lane, values) for lane, values in timings["by_lane"].items()
    ]:
        for metric, values in bucket.items():
            lines.append(
                f"| {scope} | {metric} | {values['samples']} | "
                f"{values['p50']} | {values['p95']} |"
            )
    lines += ["", "## Recurrent failure signatures", ""]
    if report["recurrent_signatures"]:
        for row in report["recurrent_signatures"]:
            lines.append(f"- {row['signature']}: {row['count']}")
    else:
        lines.append("- none")
    lines += [
        "",
        "Diagnostic evidence only. This report cannot mint PASS/CERTIFIED or "
        "reinterpret emulator evidence as physical/store evidence.",
        "",
    ]
    return "\n".join(lines)


def self_test() -> None:
    rows = [
        {
            "repository": "owner/app",
            "result": "FAIL",
            "analysis_lane": "FULL_RUNTIME",
            "reason": "Android emulator boot timeout",
            "failure_intelligence": {
                "kind": "INFRA_ERROR",
                "retryable": True,
                "failed_labs": [],
                "reason": "emulator timeout",
            },
            "pipeline_metrics": {"wall_clock_seconds": 100, "runtime_seconds": 60, "quality_seconds": 20},
        },
        {
            "repository": "owner/app",
            "result": "FAIL",
            "analysis_lane": "FULL_RUNTIME",
            "reason": "Android emulator boot timeout",
            "failure_intelligence": {
                "kind": "INFRA_ERROR",
                "retryable": True,
                "failed_labs": [],
                "reason": "emulator timeout",
            },
            "pipeline_metrics": {"wall_clock_seconds": 200, "runtime_seconds": 120, "quality_seconds": 30},
        },
        {
            "repository": "owner/app",
            "result": "FAIL",
            "analysis_lane": "FAST_RUNTIME",
            "reason": "unclassified interruption",
            "pipeline_metrics": {"wall_clock_seconds": 150, "runtime_seconds": 80, "quality_seconds": 25},
        },
        {
            "repository": "owner/app",
            "result": "PASS",
            "analysis_lane": "FAST_RUNTIME",
            "pipeline_metrics": {"wall_clock_seconds": 50, "runtime_seconds": 20, "quality_seconds": 10},
        },
    ]
    report = build_report(rows)
    assert report["summary"]["failures"] == 3
    assert report["summary"]["retryable_failures"] == 2
    assert report["summary"]["unknown_failures"] == 1
    assert report["summary"]["recurrent_signatures"] == 1
    assert report["timings"]["overall"]["wall_clock_seconds"]["p50"] == 100.0
    assert report["timings"]["overall"]["wall_clock_seconds"]["p95"] == 200.0
    assert retry_allowed(rows[2]) is False
    assert report["authority"] == "DIAGNOSTIC_ONLY"
    print("AppLab v5.6A runtime stability self-test PASS")


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
        Path(args.output_json).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
