#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

LAB_FIELDS = (
    "maestro", "visual_qa", "visual_regression", "visual_journey",
    "interaction_crawl", "system_lab", "network_lab", "persistence_lab",
    "configuration_lab", "resource_pressure_lab", "background_lab",
    "storage_lab", "upgrade_lab", "performance_lab",
)

def finalize(
    report_dir: Path,
    impact_plan: Path,
    repository: str,
    ref: str,
    resolved_sha: str,
    history_key: str,
    engine: str,
    run_id: str,
    verification_fingerprint: str = "",
    cache_domains: str = "core",
) -> dict[str, Any]:
    impact = json.loads(impact_plan.read_text(encoding="utf-8"))
    lane = str(impact.get("lane", ""))
    if lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}:
        raise ValueError(f"incremental result cannot finalize runtime lane {lane!r}")
    baseline = str(impact.get("baseline_sha", ""))
    telemetry = dict(impact.get("telemetry", {})) if isinstance(impact.get("telemetry"), dict) else {}
    generated_ms = telemetry.get("plan_generated_unix_ms")
    if isinstance(generated_ms, (int, float)) and generated_ms > 0:
        telemetry["pipeline_after_plan_ms"] = max(0, int(time.time() * 1000 - generated_ms))

    result: dict[str, Any] = {
        "schema_version": 1,
        "applab_version": "0.9.0",
        "repository": repository,
        "ref": ref,
        "resolved_sha": resolved_sha,
        "history_key": history_key,
        "engine": engine,
        "run_id": run_id,
        "result": "PASS",
        "reason": "runtime unchanged; trusted runtime evidence reused" if lane == "NO_RUNTIME_CHANGE"
                  else "static-only change passed targeted quality checks; runtime unchanged",
        "analysis_mode": str(impact.get("effective_mode", "fast")),
        "verification_lane": lane,
        "risk": impact.get("risk", {}),
        "confidence": impact.get("confidence"),
        "runtime_required": False,
        "runtime_evidence_reused": True,
        "runtime_evidence_sha": baseline,
        "shadow_full": bool(impact.get("shadow_full", False)),
        "verification_fingerprint": verification_fingerprint or str(impact.get("domain_contract_fingerprint", "")),
        "cache_domains": impact.get("cache_domains", [x for x in cache_domains.split("-") if x]),
        "historical_failure_count": impact.get("historical_failure_count", 0),
        "impacted_modules": impact.get("impacted_modules", []),
        "targeted": impact.get("targeted", {}),
        "telemetry": telemetry,
        "certification_status": "NOT_REQUESTED",
        "impact_plan": "impact-plan.json",
    }
    for field in LAB_FIELDS:
        result[field] = "SKIPPED"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = [
        "# AppLab v0.9 Incremental Verification",
        "",
        f"- Repository: `{repository}@{resolved_sha}`",
        f"- Lane: **{lane}**",
        f"- Risk: **{impact.get('risk', {}).get('label', 'UNKNOWN')}**",
        f"- Confidence: **{impact.get('confidence', 0)}**",
        f"- Runtime executed: **no**",
        f"- Runtime evidence reused from: `{baseline or 'none'}`",
        "- Specialist runtime labs: **SKIPPED** (runtime-affecting source unchanged)",
        "",
        "A skipped runtime lab is not reported as PASS. The source SHA advances only because the",
        "adaptive impact plan found no runtime-affecting change and required static checks completed.",
    ]
    (report_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return result

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        plan = root / "impact.json"
        plan.write_text(json.dumps({
            "lane": "NO_RUNTIME_CHANGE",
            "baseline_sha": "a" * 40,
            "effective_mode": "fast",
            "risk": {"label": "LOW", "score": 0},
            "confidence": 0.99,
            "shadow_full": False,
        }), encoding="utf-8")
        out = root / "report"
        result = finalize(out, plan, "owner/app", "main", "b" * 40, "app", "flutter", "1")
        assert result["result"] == "PASS"
        assert result["runtime_evidence_reused"] is True
        assert result["performance_lab"] == "SKIPPED"
    print("AppLab incremental result self-test PASS")

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--report-dir")
    p.add_argument("--impact-plan")
    p.add_argument("--repository", default="")
    p.add_argument("--ref", default="")
    p.add_argument("--resolved-sha", default="")
    p.add_argument("--history-key", default="")
    p.add_argument("--engine", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--verification-fingerprint", default="")
    p.add_argument("--cache-domains", default="core")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.report_dir or not args.impact_plan:
        raise SystemExit("--report-dir and --impact-plan are required")
    print(json.dumps(finalize(
        Path(args.report_dir), Path(args.impact_plan), args.repository, args.ref,
        args.resolved_sha, args.history_key, args.engine, args.run_id,
        args.verification_fingerprint, args.cache_domains,
    ), indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
