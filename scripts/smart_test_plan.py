#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import impact_engine

VERSION = "0.9.0"
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

DOMAIN_TO_LABS: dict[str, set[str]] = {
    "system": {"system", "upgrade"},
    "performance": {"performance"},
    "network": {"network"},
    "persistence": {"persistence", "storage", "upgrade"},
    "configuration": {"configuration", "performance"},
    "resource_pressure": {"resource_pressure"},
    "background": {"background", "resource_pressure", "system"},
    "storage": {"storage", "persistence"},
    "upgrade": {"upgrade"},
    "security": {"system", "upgrade"},
}

def git_changed_files(repo_root: Path, baseline_sha: str = "") -> list[str]:
    state, _ = impact_engine.baseline_state(repo_root, baseline_sha)
    if state != "trusted":
        return []
    try:
        return sorted({str(item["path"]) for item in impact_engine.parse_name_status(repo_root, baseline_sha)})
    except RuntimeError:
        return []

def labs_for_domains(domains: set[str]) -> set[str]:
    selected: set[str] = set()
    for domain in domains:
        selected.update(DOMAIN_TO_LABS.get(domain, set()))
    return selected

def _path_only_impact(files: list[str], mode: str, baseline_sha: str, assume_trusted_baseline: bool) -> dict[str, Any]:
    requested = mode.strip().lower()
    if requested not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")

    if requested == "certification":
        lane = "CERTIFICATION"
        risk = 100
        confidence = 1.0
    elif requested == "full":
        lane = "FULL_RUNTIME"
        risk = 80
        confidence = 1.0
    elif not files and not assume_trusted_baseline:
        lane = "FULL_RUNTIME"
        risk = 80
        confidence = 0.0
    else:
        docs_only = bool(files) and all(impact_engine.is_docs_only(p) for p in files)
        static_only = bool(files) and all(
            impact_engine.is_docs_only(p) or impact_engine.is_test_path(p) or impact_engine.is_static_config(p)
            for p in files
        )
        critical = any(any(re.search(pattern, p.lower()) for pattern in impact_engine.CRITICAL_PATTERNS) for p in files)
        high = any(impact_engine.is_build_file(p) for p in files) or any(
            any(re.search(pattern, p.lower()) for pattern in impact_engine.HIGH_PATTERNS) for p in files
        )
        if docs_only:
            lane, risk = "NO_RUNTIME_CHANGE", 5
        elif static_only:
            lane, risk = "STATIC_ONLY", 25
        elif critical or high:
            lane, risk = "FULL_RUNTIME", 80 if critical else 72
        else:
            lane, risk = "FAST_RUNTIME", 35
        confidence = 0.90 if files else 0.98

    domains: set[str] = set()
    for path in files:
        domains.update(impact_engine.domains_for_text(path))

    return {
        "schema_version": 2,
        "engine_version": VERSION,
        "requested_mode": requested,
        "effective_mode": "certification" if lane == "CERTIFICATION" else ("full" if lane == "FULL_RUNTIME" else "fast"),
        "lane": lane,
        "baseline_sha": baseline_sha.strip().lower(),
        "baseline_state": "trusted" if assume_trusted_baseline else ("missing" if not baseline_sha else "unverified"),
        "head_sha": "",
        "fallback_full": requested == "fast" and lane == "FULL_RUNTIME",
        "changed_files": [{"path": p, "status": "M", "additions": 0, "deletions": 0, "domains": sorted(impact_engine.domains_for_text(p))} for p in files],
        "changed_file_count": len(files),
        "churn": 0,
        "domains": sorted(domains),
        "dependency_impacted_files": [],
        "dependency_graph_truncated": False,
        "risk_score": risk,
        "risk_level": impact_engine.risk_level(risk),
        "confidence": confidence,
        "reasons": ["path-only compatibility classification"],
        "historical_risk": {},
        "shadow_full": False,
        "runtime_changed": lane in {"FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"},
        "static_targets": {
            "flutter_analyze_targets": [],
            "flutter_test_targets": [],
            "android_modules": [],
        },
        "planner_duration_ms": 0,
    }

def plan_from_impact(impact: dict[str, Any]) -> dict[str, Any]:
    impact_engine.validate(impact)
    lane = str(impact["lane"])
    domains = set(str(x) for x in impact.get("domains", []))

    if lane in {"FULL_RUNTIME", "CERTIFICATION"}:
        selected = {lab: True for lab in LABS}
    elif lane in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}:
        selected = {lab: False for lab in LABS}
    else:
        enabled = labs_for_domains(domains)
        if impact.get("changed_file_count", 0) and not enabled:
            enabled.update({"configuration", "performance"})
        selected = {lab: lab in enabled for lab in LABS}

    reasons: dict[str, list[str]] = {lab: [] for lab in LABS}
    for lab in LABS:
        if selected[lab]:
            if lane in {"FULL_RUNTIME", "CERTIFICATION"}:
                reasons[lab].append(f"{lane} requires complete specialist coverage")
            else:
                matching = sorted(domain for domain in domains if lab in DOMAIN_TO_LABS.get(domain, set()))
                reasons[lab].extend(matching or ["generic runtime-code coverage"])
        else:
            reasons[lab].append(f"{lane}: lab not required by trusted impact evidence")

    changed_paths: list[str] = []
    for item in impact.get("changed_files", []):
        if isinstance(item, dict):
            path = item.get("path")
            if isinstance(path, str):
                changed_paths.append(path)
        elif isinstance(item, str):
            changed_paths.append(item)

    return {
        "schema_version": 2,
        "planner_version": VERSION,
        "mode": str(impact.get("effective_mode", "full")),
        "requested_mode": str(impact.get("requested_mode", "fast")),
        "lane": lane,
        "baseline_sha": str(impact.get("baseline_sha", "")),
        "baseline_state": str(impact.get("baseline_state", "")),
        "head_sha": str(impact.get("head_sha", "")),
        "changed_files": changed_paths,
        "changed_file_details": impact.get("changed_files", []),
        "selected_labs": selected,
        "reasons": reasons,
        "fallback_full": bool(impact.get("fallback_full")),
        "risk_score": int(impact.get("risk_score", 0)),
        "risk_level": str(impact.get("risk_level", "LOW")),
        "confidence": float(impact.get("confidence", 0)),
        "domains": sorted(domains),
        "dependency_impacted_files": impact.get("dependency_impacted_files", []),
        "dependency_graph_truncated": bool(impact.get("dependency_graph_truncated")),
        "historical_risk": impact.get("historical_risk", {}),
        "shadow_full": bool(impact.get("shadow_full")),
        "runtime_changed": bool(impact.get("runtime_changed")),
        "static_targets": impact.get("static_targets", {}),
        "planner_duration_ms": int(impact.get("planner_duration_ms", 0)),
        "churn": int(impact.get("churn", 0)),
    }

def plan_repository(
    repo_root: Path,
    mode: str,
    baseline_sha: str = "",
    repository: str = "",
    history_file: str = "",
    historical_risk: dict[str, int] | None = None,
) -> dict[str, Any]:
    impact = impact_engine.analyze_repository(
        repo_root, mode, baseline_sha, repository=repository, history_file=history_file,
        historical_risk=historical_risk,
    )
    return plan_from_impact(impact)

def classify(
    files: list[str],
    mode: str,
    baseline_sha: str = "",
    assume_trusted_baseline: bool = False,
) -> dict[str, Any]:
    return plan_from_impact(_path_only_impact(files, mode, baseline_sha, assume_trusted_baseline))

def validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("invalid analysis plan schema")
    mode = str(payload.get("mode", "")).lower()
    requested = str(payload.get("requested_mode", mode)).lower()
    if mode not in {"fast", "full", "certification"} or requested not in {"fast", "full", "certification"}:
        raise ValueError("invalid analysis plan mode")
    lane = str(payload.get("lane", ""))
    if lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY", "FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}:
        raise ValueError("invalid analysis plan lane")
    baseline_sha = str(payload.get("baseline_sha", "")).strip().lower()
    if baseline_sha and not re.fullmatch(r"[0-9a-f]{40}", baseline_sha):
        raise ValueError("invalid analysis plan baseline SHA")
    selected = payload.get("selected_labs")
    if not isinstance(selected, dict) or set(selected) != set(LABS):
        raise ValueError("analysis plan selected_labs mismatch")
    if not all(isinstance(selected[k], bool) for k in LABS):
        raise ValueError("analysis plan lab values must be booleans")
    files = payload.get("changed_files", [])
    if not isinstance(files, list) or len(files) > impact_engine.MAX_CHANGED_FILES:
        raise ValueError("invalid changed_files in analysis plan")
    for path in files:
        if not isinstance(path, str) or len(path) > 500 or "\n" in path or "\r" in path:
            raise ValueError("invalid changed file path")
    score = payload.get("risk_score")
    confidence = payload.get("confidence")
    if not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("invalid analysis plan risk score")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("invalid analysis plan confidence")
    return payload

def self_test() -> None:
    docs = classify(["README.md"], "fast", "a" * 40, assume_trusted_baseline=True)
    assert docs["lane"] == "NO_RUNTIME_CHANGE"
    assert not any(docs["selected_labs"].values())

    db = classify(["app/src/main/java/x/AppDatabase.kt"], "fast", "a" * 40, assume_trusted_baseline=True)
    assert db["selected_labs"]["storage"]
    assert db["selected_labs"]["persistence"]

    ui = classify(["lib/screens/home_page.dart"], "fast", "a" * 40, assume_trusted_baseline=True)
    assert ui["lane"] == "FAST_RUNTIME"
    assert ui["selected_labs"]["configuration"]
    assert ui["selected_labs"]["performance"]

    full = classify([], "fast", "")
    assert full["mode"] == "full" and full["fallback_full"]

    cert = classify(["README.md"], "certification", "a" * 40, assume_trusted_baseline=True)
    assert cert["mode"] == "certification"
    assert all(cert["selected_labs"].values())

    validate_plan(db)
    validate_plan(cert)

    import tempfile
    import subprocess
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "applab@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "AppLab"], check=True)
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
        baseline = impact_engine.head_sha(root)

        db_file = root / "app" / "src" / "main" / "java" / "x" / "Migration_4_5.kt"
        db_file.parent.mkdir(parents=True)
        db_file.write_text("class Migration_4_5\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "migration"], check=True)
        (root / "README.md").write_text("later docs\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "docs"], check=True)

        plan = plan_repository(root, "fast", baseline)
        assert "app/src/main/java/x/Migration_4_5.kt" in plan["changed_files"]
        assert plan["lane"] == "FULL_RUNTIME"
        assert plan["selected_labs"]["upgrade"]

        missing = plan_repository(root, "fast", "f" * 40)
        assert missing["mode"] == "full" and missing["fallback_full"]

    print("AppLab v0.9 Smart Test Planner self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode", choices=("fast", "full", "certification"), default="full")
    parser.add_argument("--baseline-sha", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--history-file", default="")
    parser.add_argument("--historical-risk-json", default="")
    parser.add_argument("--output")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.output:
        raise SystemExit("--repo-root and --output are required")
    historical_risk = {}
    if args.historical_risk_json:
        value = json.loads(args.historical_risk_json)
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, int) and v >= 0 for k, v in value.items()
        ):
            raise SystemExit("--historical-risk-json must be an object of non-negative integer counts")
        historical_risk = value
    payload = plan_repository(
        Path(args.repo_root).resolve(), args.mode, args.baseline_sha,
        repository=args.repository, history_file=args.history_file,
        historical_risk=historical_risk,
    )
    validate_plan(payload)
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"lane={payload['lane']}\n")
            handle.write(f"effective_mode={payload['mode']}\n")
            handle.write(f"risk_score={payload['risk_score']}\n")
            handle.write(f"confidence={payload['confidence']}\n")
            handle.write(f"shadow_full={'true' if payload['shadow_full'] else 'false'}\n")
            handle.write(f"runtime_changed={'true' if payload['runtime_changed'] else 'false'}\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
