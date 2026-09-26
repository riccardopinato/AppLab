#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import smart_test_plan
import contract_fingerprint

MAX_CHANGED_FILES = 500
RUNTIME_SUFFIXES = {
    ".dart", ".kt", ".java", ".xml", ".gradle", ".kts", ".toml", ".properties",
    ".json", ".yaml", ".yml", ".proto", ".aidl", ".c", ".cc", ".cpp", ".h",
}
DOC_PREFIXES = ("docs/", ".github/issue_template/", ".github/pull_request_template")
DOC_NAMES = {
    "readme", "readme.md", "readme.txt", "license", "license.md", "changelog.md",
    "roadmap.md", "contributing.md", "code_of_conduct.md", "notice.md",
}
TEST_MARKERS = ("/test/", "/tests/", "/androidtest/", "/test_", "_test.", "test/")
HIGH_RISK_PATTERNS = (
    r"androidmanifest\.xml$", r"migration", r"schema", r"database", r"room", r"dao",
    r"workmanager", r"worker", r"background", r"foreground.?service", r"background.?service", r"alarm", r"notification", r"permission",
    r"build\.gradle", r"settings\.gradle", r"gradle\.properties", r"pubspec\.yaml$",
    r"applicationid", r"minsdk", r"targetsdk", r"sign", r"keystore",
)
CRITICAL_PATTERNS = (
    r"migration", r"schema", r"sign", r"keystore", r"applicationid",
    r"proguard", r"r8", r"androidmanifest\.xml$",
)
STATIC_CONFIG_PATTERNS = (
    r"analysis_options\.yaml$", r"lint", r"detekt", r"ktlint", r"test", r"spec",
)
IMPORT_RE = re.compile(
    r"^\s*(?:import|export)\s+[\"']([^\"']+)[\"']|"
    r"^\s*import\s+([A-Za-z0-9_.*]+)",
    re.MULTILINE,
)

def run(repo: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )

def valid_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value.strip().lower()))

def baseline_state(repo: Path, baseline_sha: str) -> tuple[bool, str]:
    baseline = baseline_sha.strip().lower()
    if not valid_sha(baseline):
        return False, "missing_or_invalid_baseline"
    exists = run(repo, "cat-file", "-e", f"{baseline}^{{commit}}", timeout=15)
    if exists.returncode != 0:
        return False, "baseline_not_available"
    ancestor = run(repo, "merge-base", "--is-ancestor", baseline, "HEAD", timeout=15)
    if ancestor.returncode != 0:
        return False, "baseline_not_ancestor"
    return True, "ok"

def diff_records(repo: Path, baseline_sha: str) -> tuple[list[dict[str, Any]], str]:
    ok, reason = baseline_state(repo, baseline_sha)
    if not ok:
        return [], reason
    baseline = baseline_sha.strip().lower()
    names = run(repo, "diff", "--name-status", "--find-renames", f"{baseline}..HEAD")
    nums = run(repo, "diff", "--numstat", "--find-renames", f"{baseline}..HEAD")
    if names.returncode != 0 or nums.returncode != 0:
        return [], "diff_failed"

    stats: dict[str, tuple[int | None, int | None]] = {}
    for line in nums.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path = parts[-1].strip().replace("\\", "/")
        try:
            adds = int(parts[0]) if parts[0] != "-" else None
            dels = int(parts[1]) if parts[1] != "-" else None
        except ValueError:
            adds = dels = None
        stats[path] = (adds, dels)

    records: list[dict[str, Any]] = []
    for raw in names.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        path = parts[-1].strip().replace("\\", "/")
        previous = parts[-2].strip().replace("\\", "/") if status.startswith("R") and len(parts) >= 3 else ""
        adds, dels = stats.get(path, (None, None))
        records.append({
            "status": status,
            "path": path,
            "previous_path": previous,
            "additions": adds,
            "deletions": dels,
        })
    return sorted(records, key=lambda x: x["path"]), "ok"

def is_doc(path: str) -> bool:
    p = path.lower()
    name = Path(p).name
    return name in DOC_NAMES or p.startswith(DOC_PREFIXES) or p.endswith((".md", ".rst", ".adoc"))

def is_test(path: str) -> bool:
    p = "/" + path.lower().strip("/") + "/"
    return any(marker in p for marker in TEST_MARKERS)

def runtime_candidate(path: str) -> bool:
    p = path.lower()
    if is_doc(path) or is_test(path):
        return False
    return Path(p).suffix in RUNTIME_SUFFIXES

def extract_imports(repo: Path, records: list[dict[str, Any]]) -> list[str]:
    imports: set[str] = set()
    for record in records[:100]:
        path = repo / record["path"]
        if not path.is_file() or path.stat().st_size > 512_000:
            continue
        if path.suffix.lower() not in {".dart", ".kt", ".java"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in IMPORT_RE.finditer(text):
            value = (match.group(1) or match.group(2) or "").strip()
            if value:
                imports.add(value)
    return sorted(imports)[:300]

def impacted_modules(records: list[dict[str, Any]], engine: str) -> list[str]:
    result: set[str] = set()
    for item in records:
        parts = Path(item["path"]).parts
        if engine == "flutter":
            if len(parts) >= 3 and parts[0] == "lib":
                if parts[1] in {"features", "feature", "modules", "module"}:
                    result.add("/".join(parts[:3]))
                else:
                    result.add("/".join(parts[:2]))
        else:
            for idx, part in enumerate(parts):
                if part == "src" and idx > 0:
                    result.add("/".join(parts[:idx]))
                    break
            if not result and parts:
                result.add(parts[0])
    return sorted(x for x in result if x and x != ".")

def risk_score(records: list[dict[str, Any]], imports: list[str], historical_failures: int) -> tuple[int, list[str]]:
    score = min(max(historical_failures, 0), 5) * 4
    reasons: list[str] = []
    total_churn = 0
    runtime_files = 0
    deleted = 0
    for item in records:
        path = item["path"].lower()
        if runtime_candidate(path):
            runtime_files += 1
        if str(item["status"]).startswith("D"):
            deleted += 1
        if isinstance(item.get("additions"), int):
            total_churn += int(item["additions"])
        if isinstance(item.get("deletions"), int):
            total_churn += int(item["deletions"])
        if any(re.search(p, path, re.I) for p in CRITICAL_PATTERNS):
            score += 60
            reasons.append(f"critical:{item['path']}")
        elif any(re.search(p, path, re.I) for p in HIGH_RISK_PATTERNS):
            score += 35
            reasons.append(f"high:{item['path']}")
    if runtime_files >= 12:
        score += 15
        reasons.append("broad_runtime_change")
    elif runtime_files >= 5:
        score += 8
        reasons.append("multi_file_runtime_change")
    if total_churn >= 1500:
        score += 20
        reasons.append("large_churn")
    elif total_churn >= 500:
        score += 10
        reasons.append("medium_churn")
    if deleted:
        score += min(12, deleted * 3)
        reasons.append("file_deletion")
    import_text = " ".join(imports).lower()
    if any(x in import_text for x in ("android.app.service", "androidx.work", "workmanager")):
        score += 35
        reasons.append("high_runtime_dependency_import")
    elif any(x in import_text for x in ("http", "dio", "retrofit", "room", "sqlite", "firebase")):
        score += 5
        reasons.append("sensitive_dependency_import")
    if historical_failures > 0:
        reasons.append(f"historical_failures:{historical_failures}")
    return min(score, 100), reasons[:50]

def risk_label(score: int) -> str:
    if score >= 60:
        return "CRITICAL"
    if score >= 35:
        return "HIGH"
    if score >= 15:
        return "MEDIUM"
    return "LOW"

def confidence(records: list[dict[str, Any]], diff_reason: str, modules: list[str]) -> float:
    if diff_reason != "ok":
        return 0.0
    value = 0.97
    if not records:
        return 0.65
    unknown = sum(1 for x in records if Path(x["path"]).suffix.lower() not in RUNTIME_SUFFIXES and not is_doc(x["path"]))
    value -= min(0.25, unknown * 0.02)
    if len(records) > 150:
        value -= 0.12
    if not modules and any(runtime_candidate(x["path"]) for x in records):
        value -= 0.08
    return round(max(0.0, min(0.99, value)), 2)

def choose_lane(
    requested_mode: str,
    records: list[dict[str, Any]],
    diff_reason: str,
    risk: str,
    conf: float,
) -> tuple[str, str, list[str]]:
    if requested_mode == "certification":
        return "CERTIFICATION", "certification", ["explicit_certification"]
    if requested_mode == "full":
        return "FULL_RUNTIME", "full", ["explicit_full"]
    if diff_reason != "ok":
        return "FULL_RUNTIME", "full", [f"unsafe_diff:{diff_reason}"]
    if len(records) > MAX_CHANGED_FILES:
        return "FULL_RUNTIME", "full", ["diff_too_large"]
    if not records:
        return "NO_RUNTIME_CHANGE", "fast", ["no_changes"]
    if all(is_doc(x["path"]) for x in records):
        return "NO_RUNTIME_CHANGE", "fast", ["documentation_only"]
    if all(is_doc(x["path"]) or is_test(x["path"]) or any(re.search(p, x["path"], re.I) for p in STATIC_CONFIG_PATTERNS) for x in records):
        return "STATIC_ONLY", "fast", ["tests_or_static_configuration_only"]
    if risk in {"HIGH", "CRITICAL"} or conf < 0.75:
        return "FULL_RUNTIME", "full", [f"risk:{risk}", f"confidence:{conf:.2f}"]
    return "FAST_RUNTIME", "fast", [f"risk:{risk}", f"confidence:{conf:.2f}"]

def targeted_scopes(records: list[dict[str, Any]], engine: str) -> dict[str, list[str]]:
    scopes: set[str] = set()
    tests: set[str] = set()
    if engine == "flutter":
        for item in records:
            p = Path(item["path"])
            parts = p.parts
            if parts and parts[0] == "lib":
                scope = "/".join(parts[:3] if len(parts) >= 3 and parts[1] in {"features", "feature", "modules", "module"} else parts[:2])
                if scope:
                    scopes.add(scope)
                if len(parts) >= 3 and parts[1] in {"features", "feature"}:
                    tests.add(f"test/{parts[1]}/{parts[2]}")
            elif parts and parts[0] in {"test", "integration_test"}:
                tests.add("/".join(parts[: min(len(parts), 3)]))
    else:
        modules = impacted_modules(records, engine)
        scopes.update(modules)
        for module in modules:
            if module and module != ".":
                tests.add(module)
    return {"analysis_scopes": sorted(scopes), "test_scopes": sorted(tests)}

def shadow_decision(head_sha: str, lane: str, sample_percent: int) -> bool:
    if lane != "FAST_RUNTIME" or sample_percent <= 0:
        return False
    if not valid_sha(head_sha):
        return False
    bucket = int(hashlib.sha256(head_sha.encode()).hexdigest()[:8], 16) % 100
    return bucket < min(sample_percent, 100)

def make_plan(repo: Path, engine: str, requested_mode: str, baseline_sha: str, historical_failures: int, shadow_percent: int) -> dict[str, Any]:
    records, diff_reason = diff_records(repo, baseline_sha)
    head = run(repo, "rev-parse", "HEAD", timeout=10).stdout.strip().lower()
    paths = [x["path"] for x in records]
    imports = extract_imports(repo, records)
    modules = impacted_modules(records, engine)
    score, risk_reasons = risk_score(records, imports, historical_failures)
    label = risk_label(score)
    conf = confidence(records, diff_reason, modules)
    lane, effective_mode, lane_reasons = choose_lane(requested_mode, records, diff_reason, label, conf)

    if len(records) > MAX_CHANGED_FILES:
        effective_mode = "full"
        lane = "FULL_RUNTIME"
        lane_reasons = ["diff_too_large"]

    specialist = smart_test_plan.classify(paths, effective_mode, baseline_sha)
    predicted_selected_labs = dict(specialist["selected_labs"])
    predicted_lab_reasons = {k: list(v) for k, v in specialist["reasons"].items()}
    shadow = shadow_decision(head, lane, shadow_percent)
    calibration_from_lane = ""
    if shadow:
        calibration_from_lane = lane
        lane = "FULL_RUNTIME"
        effective_mode = "full"
        specialist = smart_test_plan.classify(paths, "full", baseline_sha)
        lane_reasons.append("shadow_full_calibration")

    if lane in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}:
        specialist["selected_labs"] = {key: False for key in smart_test_plan.LABS}
        for key in specialist["reasons"]:
            specialist["reasons"][key] = [f"{lane.lower()} lane"]

    scopes = targeted_scopes(records, engine)
    runtime_required = lane in {"FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}
    run_build = runtime_required
    run_static = lane != "NO_RUNTIME_CHANGE"
    run_tests = lane != "NO_RUNTIME_CHANGE"
    cache_domains = ["core"] + sorted(k for k, v in specialist["selected_labs"].items() if v)
    if effective_mode == "certification":
        cache_domains.append("certification")

    return {
        "schema_version": 1,
        "planner_version": "0.9.0",
        "requested_mode": requested_mode,
        "effective_mode": effective_mode,
        "lane": lane,
        "baseline_sha": baseline_sha.strip().lower(),
        "head_sha": head,
        "diff_state": diff_reason,
        "changed_file_count": len(records),
        "changes": records[:MAX_CHANGED_FILES],
        "risk": {"score": score, "label": label, "reasons": risk_reasons},
        "confidence": conf,
        "imports": imports,
        "impacted_modules": modules,
        "targeted": scopes,
        "selected_labs": specialist["selected_labs"],
        "lab_reasons": specialist["reasons"],
        "predicted_selected_labs": predicted_selected_labs,
        "predicted_lab_reasons": predicted_lab_reasons,
        "calibration_from_lane": calibration_from_lane,
        "run_static_analysis": run_static,
        "run_tests": run_tests,
        "run_build": run_build,
        "runtime_required": runtime_required,
        "shadow_full": shadow,
        "shadow_sample_percent": shadow_percent,
        "cache_domains": sorted(set(cache_domains)),
        "reasons": lane_reasons,
        "historical_failure_count": max(0, historical_failures),
    }

def validate(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("schema_version") != 1:
        raise ValueError("invalid impact plan schema")
    if plan.get("lane") not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY", "FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}:
        raise ValueError("invalid lane")
    if plan.get("effective_mode") not in {"fast", "full", "certification"}:
        raise ValueError("invalid effective mode")
    if not isinstance(plan.get("confidence"), (int, float)):
        raise ValueError("invalid confidence")
    if not isinstance(plan.get("selected_labs"), dict):
        raise ValueError("invalid selected_labs")
    return plan

def emit_outputs(path: Path, plan: dict[str, Any], output_file: Path) -> None:
    values = {
        "lane": plan["lane"],
        "effective_mode": plan["effective_mode"],
        "run_static_analysis": str(plan["run_static_analysis"]).lower(),
        "run_tests": str(plan["run_tests"]).lower(),
        "run_build": str(plan["run_build"]).lower(),
        "runtime_required": str(plan["runtime_required"]).lower(),
        "shadow_full": str(plan["shadow_full"]).lower(),
        "risk": plan["risk"]["label"],
        "confidence": str(plan["confidence"]),
        "plan_file": str(output_file),
        "analysis_scopes_json": json.dumps(plan["targeted"]["analysis_scopes"], separators=(",", ":")),
        "test_scopes_json": json.dumps(plan["targeted"]["test_scopes"], separators=(",", ":")),
        "cache_domains": "-".join(plan["cache_domains"]),
        "domain_contract_fingerprint": str(plan.get("domain_contract_fingerprint", "")),
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")

def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "applab@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "AppLab"], check=True)
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
        baseline = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

        (root / "README.md").write_text("docs\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "commit", "-qam", "docs"], check=True)
        plan = make_plan(root, "flutter", "fast", baseline, 0, 10)
        assert plan["lane"] == "NO_RUNTIME_CHANGE"

        subprocess.run(["git", "-C", str(root), "reset", "--hard", baseline], check=True, stdout=subprocess.DEVNULL)
        db = root / "lib" / "data" / "database.dart"
        db.parent.mkdir(parents=True)
        db.write_text("class Database {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "database"], check=True)
        plan = make_plan(root, "flutter", "fast", baseline, 0, 10)
        assert plan["runtime_required"]
        assert plan["selected_labs"]["storage"]
        assert plan["selected_labs"]["persistence"]

        branch = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run(["git", "-C", str(root), "checkout", "-q", "--orphan", "other"], check=True)
        for p in list(root.iterdir()):
            if p.name != ".git":
                if p.is_dir():
                    import shutil
                    shutil.rmtree(p)
                else:
                    p.unlink()
        (root / "other.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "other"], check=True)
        bad = make_plan(root, "flutter", "fast", branch, 0, 10)
        assert bad["lane"] == "FULL_RUNTIME" and bad["effective_mode"] == "full"
    print("AppLab Adaptive Impact Engine self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--engine", choices=("flutter", "native_android"), required=False, default="flutter")
    parser.add_argument("--mode", choices=("fast", "full", "certification"), default="fast")
    parser.add_argument("--baseline-sha", default="")
    parser.add_argument("--historical-failures", type=int, default=0)
    parser.add_argument("--shadow-percent", type=int, default=10)
    parser.add_argument("--contract-root", default="")
    parser.add_argument("--output")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.output:
        raise SystemExit("--repo-root and --output are required")
    output = Path(args.output)
    started = time.perf_counter()
    plan = validate(make_plan(
        Path(args.repo_root).resolve(),
        args.engine,
        args.mode,
        args.baseline_sha,
        args.historical_failures,
        args.shadow_percent,
    ))
    plan["telemetry"] = {
        "planner_duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "plan_generated_unix_ms": int(time.time() * 1000),
        "changed_file_count": plan.get("changed_file_count", 0),
        "risk_score": plan.get("risk", {}).get("score", 0),
        "confidence": plan.get("confidence", 0),
    }
    if args.contract_root:
        domains = set(plan.get("cache_domains", ["core"]))
        plan["domain_contract_fingerprint"] = contract_fingerprint.compute_selected(
            Path(args.contract_root), domains
        )[:16]
    else:
        plan["domain_contract_fingerprint"] = ""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.github_output:
        emit_outputs(Path(args.github_output), plan, output)
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
