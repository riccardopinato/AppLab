#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = "0.9.0"
MAX_CHANGED_FILES = 500
MAX_GRAPH_FILES = 7000
MAX_DIFF_BYTES = 300_000

DOC_PREFIXES = ("docs/", ".github/", ".vscode/", ".idea/")
DOC_NAMES = {"readme.md", "license", "license.md", "changelog.md", "contributing.md", "code_of_conduct.md"}
STATIC_CONFIG_NAMES = {"analysis_options.yaml", "lint.xml", "detekt.yml", "detekt.yaml"}
BUILD_FILES = {
    "pubspec.yaml", "pubspec.lock", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "gradle.properties",
    "gradle-wrapper.properties", "libs.versions.toml",
}
SOURCE_SUFFIXES = {".dart", ".kt", ".java", ".xml", ".gradle", ".kts", ".toml", ".yaml", ".yml", ".json"}

DOMAIN_PATTERNS: dict[str, tuple[str, ...]] = {
    "system": (
        r"androidmanifest\.xml$", r"permission", r"notification", r"deeplink", r"intent",
        r"biometric", r"camera", r"location", r"bluetooth", r"foreground.?service",
    ),
    "performance": (
        r"(^|/)(lib|src|app)/", r"render", r"image", r"bitmap", r"list", r"animation",
        r"compose", r"widget", r"screen", r"page", r"view",
    ),
    "network": (
        r"network", r"http", r"api", r"retrofit", r"dio", r"ktor", r"websocket",
        r"sync", r"remote", r"connectivity", r"graphql", r"firebase", r"supabase",
    ),
    "persistence": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref",
        r"datastore", r"sqlite", r"repository", r"model", r"drift", r"hive", r"isar",
    ),
    "configuration": (
        r"activity", r"fragment", r"compose", r"widget", r"screen", r"page", r"view",
        r"layout", r"theme", r"orientation", r"resource", r"res/", r"lib/.*\.dart$",
    ),
    "resource_pressure": (
        r"service", r"worker", r"background", r"cache", r"image", r"bitmap", r"camera",
        r"media", r"memory", r"process",
    ),
    "background": (
        r"service", r"worker", r"workmanager", r"background", r"alarm", r"job",
        r"notification", r"battery", r"doze", r"sync", r"foreground.?service",
    ),
    "storage": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref",
        r"datastore", r"storage", r"file", r"sqlite", r"backup", r"cache", r"drift",
    ),
    "upgrade": (
        r"database", r"migration", r"schema", r"androidmanifest\.xml$", r"build\.gradle",
        r"pubspec\.yaml$", r"version", r"applicationid", r"minsdk", r"targetsdk",
        r"namespace", r"gradle-wrapper", r"libs\.versions",
    ),
    "security": (
        r"signing", r"keystore", r"certificate", r"auth", r"token", r"crypto", r"secret",
        r"proguard", r"r8", r"network.?security",
    ),
}

CRITICAL_PATTERNS = (
    r"migration", r"schema", r"applicationid", r"signing", r"keystore",
    r"androidmanifest\.xml$", r"permission", r"minsdk", r"targetsdk",
)
HIGH_PATTERNS = (
    r"pubspec\.ya?ml$", r"gradle", r"workmanager", r"foreground.?service",
    r"alarm", r"database", r"room", r"sqlite", r"network.?security",
)

def run_git(root: Path, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )

def head_sha(root: Path) -> str:
    result = run_git(root, ["rev-parse", "HEAD"], 15)
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else ""

def baseline_state(root: Path, baseline_sha: str) -> tuple[str, str]:
    baseline = baseline_sha.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", baseline):
        return "missing", "baseline SHA is absent or invalid"
    exists = run_git(root, ["cat-file", "-e", f"{baseline}^{{commit}}"], 15)
    if exists.returncode != 0:
        return "missing", "baseline commit is unavailable in the checkout"
    ancestor = run_git(root, ["merge-base", "--is-ancestor", baseline, "HEAD"], 15)
    if ancestor.returncode != 0:
        return "non_ancestor", "baseline is not an ancestor of HEAD"
    return "trusted", ""

def parse_name_status(root: Path, baseline: str) -> list[dict[str, Any]]:
    result = run_git(root, ["diff", "--name-status", "--find-renames", f"{baseline}..HEAD"], 30)
    if result.returncode != 0:
        raise RuntimeError("git diff --name-status failed")
    records: list[dict[str, Any]] = []
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        status_raw = parts[0]
        status = status_raw[0]
        if status == "R" and len(parts) >= 3:
            records.append({"status": "R", "previous_path": parts[1], "path": parts[2]})
        elif len(parts) >= 2:
            records.append({"status": status, "path": parts[1]})
    return records

def parse_numstat(root: Path, baseline: str) -> dict[str, tuple[int, int]]:
    result = run_git(root, ["diff", "--numstat", "--find-renames", f"{baseline}..HEAD"], 30)
    stats: dict[str, tuple[int, int]] = {}
    if result.returncode != 0:
        return stats
    for raw in result.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        try:
            additions = 0 if parts[0] == "-" else int(parts[0])
            deletions = 0 if parts[1] == "-" else int(parts[1])
        except ValueError:
            additions = deletions = 0
        path = parts[-1].replace("\\", "/")
        stats[path] = (additions, deletions)
    return stats

def diff_text(root: Path, baseline: str) -> str:
    result = run_git(root, ["diff", "--unified=0", "--find-renames", f"{baseline}..HEAD"], 30)
    if result.returncode != 0:
        return ""
    data = result.stdout
    if len(data.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
        return data[:MAX_DIFF_BYTES]
    return data

def tracked_files(root: Path) -> list[str]:
    result = run_git(root, ["ls-files"], 30)
    if result.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]

def domains_for_text(value: str) -> set[str]:
    lower = value.lower()
    found: set[str] = set()
    for domain, patterns in DOMAIN_PATTERNS.items():
        if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in patterns):
            found.add(domain)
    return found

def is_docs_only(path: str) -> bool:
    lower = path.lower()
    name = Path(lower).name
    return (
        lower.startswith(DOC_PREFIXES)
        or name in DOC_NAMES
        or lower.endswith((".md", ".rst", ".adoc"))
    )

def is_test_path(path: str) -> bool:
    lower = "/" + path.lower().lstrip("/")
    return (
        "/test/" in lower or "/tests/" in lower or "/androidtest/" in lower
        or lower.endswith("_test.dart") or lower.endswith("test.kt") or lower.endswith("test.java")
    )

def is_static_config(path: str) -> bool:
    return Path(path.lower()).name in STATIC_CONFIG_NAMES

def is_build_file(path: str) -> bool:
    lower = path.lower()
    name = Path(lower).name
    return name in BUILD_FILES or lower.endswith((".gradle", ".gradle.kts"))

def module_for(path: str) -> str:
    normalized = path.replace("\\", "/")
    if "/src/" in normalized:
        prefix = normalized.split("/src/", 1)[0].strip("/")
        return prefix or "app"
    if normalized.startswith("android/") and "/src/" in normalized[8:]:
        prefix = normalized[8:].split("/src/", 1)[0].strip("/")
        return prefix or "app"
    return ""

def lightweight_dependency_impact(root: Path, changed_paths: set[str], files: list[str]) -> tuple[list[str], bool]:
    source_files = [p for p in files if Path(p).suffix.lower() in {".dart", ".kt", ".java"}]
    truncated = len(source_files) > MAX_GRAPH_FILES
    source_files = source_files[:MAX_GRAPH_FILES]

    package_to_file: dict[str, str] = {}
    contents: dict[str, str] = {}
    for rel in source_files:
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        contents[rel] = text
        if rel.endswith((".kt", ".java")):
            match = re.search(r"(?m)^\s*package\s+([A-Za-z0-9_.]+)", text)
            if match:
                package_to_file[f"{match.group(1)}.{Path(rel).stem}"] = rel

    changed_dart = {p for p in changed_paths if p.endswith(".dart")}
    changed_jvm = {p for p in changed_paths if p.endswith((".kt", ".java"))}
    changed_jvm_symbols = {key for key, value in package_to_file.items() if value in changed_jvm}
    impacted: set[str] = set()

    for rel, text in contents.items():
        if rel in changed_paths:
            continue
        if rel.endswith(".dart") and changed_dart:
            for match in re.finditer(r"(?m)^\s*import\s+['\"]([^'\"]+)['\"]", text):
                imp = match.group(1)
                if imp.startswith("package:") and "/" in imp:
                    suffix = "lib/" + imp.split("/", 1)[1]
                    if suffix in changed_dart:
                        impacted.add(rel)
                        break
                elif imp.startswith("."):
                    candidate = (Path(rel).parent / imp).as_posix()
                    try:
                        normalized = Path(candidate).resolve().relative_to(root.resolve()).as_posix()
                    except Exception:
                        normalized = candidate
                    if normalized in changed_dart or any(normalized.endswith(Path(p).name) for p in changed_dart):
                        impacted.add(rel)
                        break
        elif rel.endswith((".kt", ".java")) and changed_jvm_symbols:
            imports = set(re.findall(r"(?m)^\s*import\s+([A-Za-z0-9_.*]+)", text))
            if any(
                symbol in imports
                or any(item.endswith(".*") and symbol.startswith(item[:-1]) for item in imports)
                for symbol in changed_jvm_symbols
            ):
                impacted.add(rel)

    return sorted(impacted), truncated

def historical_domain_risk(history_file: str, repository: str) -> dict[str, int]:
    counts = defaultdict(int)
    if not history_file:
        return {}
    path = Path(history_file)
    if not path.is_file():
        return {}
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and str(item.get("repository", "")) == repository:
            rows.append(item)
    for item in rows[-30:]:
        for domain in DOMAIN_PATTERNS:
            key = f"{domain}_lab"
            value = str(item.get(key, "")).upper()
            if value in {"FAIL", "ERROR", "WARN"}:
                counts[domain] += 1
        if str(item.get("result", "")).upper() == "FAIL":
            counts["generic_failure"] += 1
    return dict(counts)

def risk_level(score: int) -> str:
    if score >= 85:
        return "CRITICAL"
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"

def targeted_scopes(files: list[str], changed_paths: set[str], impacted: list[str]) -> dict[str, Any]:
    dart = sorted({p for p in changed_paths | set(impacted) if p.endswith(".dart") and not is_test_path(p)})
    analyze_targets: set[str] = set()
    for path in dart:
        parts = Path(path).parts
        if len(parts) >= 3 and parts[0] == "lib" and parts[1] in {"features", "feature"}:
            analyze_targets.add("/".join(parts[:3]))
        elif path.startswith("lib/"):
            analyze_targets.add(path)
    tracked_tests = [p for p in files if is_test_path(p)]
    stems = {Path(p).stem.replace("_test", "").lower() for p in dart}
    test_targets = sorted({
        p for p in tracked_tests
        if any(stem and stem in Path(p).stem.lower() for stem in stems)
    })
    modules = sorted({module_for(p) for p in changed_paths | set(impacted) if module_for(p)})
    return {
        "flutter_analyze_targets": sorted(analyze_targets)[:50],
        "flutter_test_targets": test_targets[:80],
        "android_modules": modules[:30],
    }

def analyze_repository(
    repo_root: Path,
    mode: str,
    baseline_sha: str,
    repository: str = "",
    history_file: str = "",
) -> dict[str, Any]:
    started = time.perf_counter()
    root = repo_root.resolve()
    requested = mode.strip().lower()
    if requested not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")

    head = head_sha(root)
    state, baseline_reason = baseline_state(root, baseline_sha)
    reasons: list[str] = []
    if baseline_reason:
        reasons.append(baseline_reason)

    if requested in {"full", "certification"}:
        lane = "CERTIFICATION" if requested == "certification" else "FULL_RUNTIME"
        payload = {
            "schema_version": 2,
            "engine_version": VERSION,
            "requested_mode": requested,
            "effective_mode": requested,
            "lane": lane,
            "baseline_sha": baseline_sha.strip().lower(),
            "baseline_state": state,
            "head_sha": head,
            "fallback_full": False,
            "changed_files": [],
            "changed_file_count": 0,
            "churn": 0,
            "domains": [],
            "dependency_impacted_files": [],
            "dependency_graph_truncated": False,
            "risk_score": 100 if requested == "certification" else 80,
            "risk_level": "CRITICAL" if requested == "certification" else "HIGH",
            "confidence": 1.0,
            "reasons": [f"{lane} explicitly requested"],
            "historical_risk": historical_domain_risk(history_file, repository),
            "shadow_full": False,
            "runtime_changed": True,
            "static_targets": {
                "flutter_analyze_targets": [],
                "flutter_test_targets": [],
                "android_modules": [],
            },
        }
        payload["planner_duration_ms"] = int((time.perf_counter() - started) * 1000)
        return payload

    if state != "trusted":
        payload = analyze_repository(root, "full", baseline_sha, repository, history_file)
        payload.update({
            "requested_mode": "fast",
            "effective_mode": "full",
            "lane": "FULL_RUNTIME",
            "fallback_full": True,
            "baseline_state": state,
            "reasons": reasons + ["FAST requires a trusted ancestor baseline; fail-safe FULL escalation"],
        })
        payload["planner_duration_ms"] = int((time.perf_counter() - started) * 1000)
        return payload

    try:
        records = parse_name_status(root, baseline_sha)
    except RuntimeError as exc:
        payload = analyze_repository(root, "full", baseline_sha, repository, history_file)
        payload.update({
            "requested_mode": "fast",
            "effective_mode": "full",
            "lane": "FULL_RUNTIME",
            "fallback_full": True,
            "reasons": [str(exc), "diff failure; fail-safe FULL escalation"],
        })
        payload["planner_duration_ms"] = int((time.perf_counter() - started) * 1000)
        return payload

    if len(records) > MAX_CHANGED_FILES:
        payload = analyze_repository(root, "full", baseline_sha, repository, history_file)
        payload.update({
            "requested_mode": "fast",
            "effective_mode": "full",
            "lane": "FULL_RUNTIME",
            "fallback_full": True,
            "changed_file_count": len(records),
            "reasons": [f"changed-file count {len(records)} exceeds safe FAST limit {MAX_CHANGED_FILES}"],
        })
        payload["planner_duration_ms"] = int((time.perf_counter() - started) * 1000)
        return payload

    stats = parse_numstat(root, baseline_sha)
    patch = diff_text(root, baseline_sha)
    patch_domains = domains_for_text(patch)
    changed_paths = {str(item["path"]).replace("\\", "/") for item in records}
    all_files = tracked_files(root)
    impacted, graph_truncated = lightweight_dependency_impact(root, changed_paths, all_files)

    domains: set[str] = set(patch_domains)
    change_items: list[dict[str, Any]] = []
    churn = 0
    unknown_runtime = 0
    critical = False
    high = False

    for item in records:
        path = str(item["path"]).replace("\\", "/")
        additions, deletions = stats.get(path, (0, 0))
        churn += additions + deletions
        item_domains = domains_for_text(path)
        domains.update(item_domains)
        lower = path.lower()
        if any(re.search(p, lower) for p in CRITICAL_PATTERNS):
            critical = True
        if any(re.search(p, lower) for p in HIGH_PATTERNS):
            high = True
        suffix = Path(lower).suffix
        if suffix in SOURCE_SUFFIXES and not item_domains and not is_docs_only(path) and not is_test_path(path):
            unknown_runtime += 1
        change_items.append({
            **item,
            "path": path,
            "additions": additions,
            "deletions": deletions,
            "domains": sorted(item_domains),
        })

    for path in impacted:
        domains.update(domains_for_text(path))

    history = historical_domain_risk(history_file, repository)
    docs_only = bool(records) and all(is_docs_only(str(i["path"])) for i in records)
    static_only = bool(records) and all(
        is_docs_only(str(i["path"])) or is_test_path(str(i["path"])) or is_static_config(str(i["path"]))
        for i in records
    )
    build_change = any(is_build_file(str(i["path"])) for i in records)
    maestro_change = any(str(i["path"]).startswith(".maestro/") for i in records)

    score = 10
    if critical:
        score = max(score, 85)
    if high or build_change:
        score = max(score, 70)
    if "persistence" in domains or "upgrade" in domains:
        score = max(score, 70)
    if "background" in domains or "system" in domains or "security" in domains:
        score = max(score, 65)
    if "network" in domains:
        score = max(score, 50)
    if "configuration" in domains or "performance" in domains:
        score = max(score, 30)
    if any(i["status"] == "D" for i in change_items):
        score += 8
    if any(i["status"] == "R" for i in change_items):
        score += 4
    if len(records) > 50:
        score += 10
    if churn > 1500:
        score += 10
    if unknown_runtime:
        score += min(10, unknown_runtime * 2)
    for domain in domains:
        score += min(12, int(history.get(domain, 0)) * 3)
    score += min(8, int(history.get("generic_failure", 0)))
    score = min(100, score)

    confidence = 0.97
    if graph_truncated:
        confidence -= 0.12
        reasons.append("dependency graph reached safety limit")
    if len(records) > 100:
        confidence -= 0.08
    if unknown_runtime:
        confidence -= min(0.12, unknown_runtime * 0.02)
    if not patch:
        confidence -= 0.05
    confidence = max(0.0, min(1.0, confidence))

    if docs_only:
        lane = "NO_RUNTIME_CHANGE"
        score = min(score, 10)
    elif static_only and not maestro_change:
        lane = "STATIC_ONLY"
        score = min(score, 35)
    elif score >= 70 or confidence < 0.65:
        lane = "FULL_RUNTIME"
    else:
        lane = "FAST_RUNTIME"

    fallback = lane == "FULL_RUNTIME"
    effective = "full" if fallback else "fast"
    runtime_changed = lane in {"FAST_RUNTIME", "FULL_RUNTIME"}
    shadow = bool(
        lane == "FAST_RUNTIME"
        and re.fullmatch(r"[0-9a-f]{40}", head or "")
        and int(head[:8], 16) % 10 == 0
    )

    if docs_only:
        reasons.append("only documentation/CI metadata changed")
    if static_only and not docs_only:
        reasons.append("only tests/static-analysis configuration changed")
    if build_change:
        reasons.append("build/dependency configuration changed")
    if critical:
        reasons.append("critical runtime/release surface changed")
    if score >= 70 and lane == "FULL_RUNTIME":
        reasons.append("risk threshold requires FULL runtime verification")
    if confidence < 0.65:
        reasons.append("planner confidence below safe FAST threshold")
    if shadow:
        reasons.append("deterministic 10% shadow-FULL calibration sample")

    scopes = targeted_scopes(all_files, changed_paths, impacted)
    payload = {
        "schema_version": 2,
        "engine_version": VERSION,
        "requested_mode": "fast",
        "effective_mode": effective,
        "lane": lane,
        "baseline_sha": baseline_sha.strip().lower(),
        "baseline_state": state,
        "head_sha": head,
        "fallback_full": fallback,
        "changed_files": change_items,
        "changed_file_count": len(change_items),
        "churn": churn,
        "domains": sorted(domains),
        "dependency_impacted_files": impacted[:250],
        "dependency_graph_truncated": graph_truncated,
        "risk_score": score,
        "risk_level": risk_level(score),
        "confidence": round(confidence, 3),
        "reasons": reasons,
        "historical_risk": history,
        "shadow_full": shadow,
        "runtime_changed": runtime_changed,
        "static_targets": scopes,
    }
    payload["planner_duration_ms"] = int((time.perf_counter() - started) * 1000)
    return payload

def validate(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 2:
        raise ValueError("invalid impact schema")
    if payload.get("lane") not in {
        "NO_RUNTIME_CHANGE", "STATIC_ONLY", "FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"
    }:
        raise ValueError("invalid impact lane")
    if not isinstance(payload.get("risk_score"), int) or not 0 <= payload["risk_score"] <= 100:
        raise ValueError("invalid risk score")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("invalid confidence")
    changed = payload.get("changed_files")
    if not isinstance(changed, list):
        raise ValueError("changed_files must be a list")
    return payload

def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "applab@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "AppLab"], check=True)
        (root / "README.md").write_text("base\n", encoding="utf-8")
        (root / "lib").mkdir()
        (root / "lib" / "main.dart").write_text("void main() {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
        base = head_sha(root)

        (root / "README.md").write_text("docs only\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "docs"], check=True)
        docs = analyze_repository(root, "fast", base)
        assert docs["lane"] == "NO_RUNTIME_CHANGE"
        assert docs["baseline_state"] == "trusted"

        base2 = head_sha(root)
        db = root / "lib" / "database"
        db.mkdir()
        (db / "migration.dart").write_text("class Migration {}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "migration"], check=True)
        risky = analyze_repository(root, "fast", base2)
        assert risky["lane"] == "FULL_RUNTIME"
        assert risky["risk_score"] >= 70

        missing = analyze_repository(root, "fast", "f" * 40)
        assert missing["lane"] == "FULL_RUNTIME" and missing["fallback_full"]

        full = analyze_repository(root, "full", base2)
        assert full["lane"] == "FULL_RUNTIME"
        cert = analyze_repository(root, "certification", base2)
        assert cert["lane"] == "CERTIFICATION"
        validate(risky)

    print("AppLab v0.9 Impact Engine self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode", choices=("fast", "full", "certification"), default="fast")
    parser.add_argument("--baseline-sha", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--history-file", default="")
    parser.add_argument("--output")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.repo_root:
        raise SystemExit("--repo-root is required")
    payload = analyze_repository(
        Path(args.repo_root), args.mode, args.baseline_sha,
        repository=args.repository, history_file=args.history_file,
    )
    validate(payload)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"lane={payload['lane']}\n")
            handle.write(f"effective_mode={payload['effective_mode']}\n")
            handle.write(f"risk_score={payload['risk_score']}\n")
            handle.write(f"confidence={payload['confidence']}\n")
            handle.write(f"shadow_full={'true' if payload['shadow_full'] else 'false'}\n")
            handle.write(f"runtime_changed={'true' if payload['runtime_changed'] else 'false'}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
