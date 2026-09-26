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
SCHEMA_VERSION = 2
MAX_CHANGED_FILES = 500
MAX_DIFF_BYTES = 1_500_000
MAX_INSPECT_BYTES = 1_000_000

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

SOURCE_SUFFIXES = {".kt", ".java", ".dart", ".xml", ".gradle", ".kts", ".toml", ".json", ".yaml", ".yml"}
CODE_SUFFIXES = {".kt", ".java", ".dart"}
DOC_NAMES = {"readme", "changelog", "contributing", "license", "notice", "roadmap"}
BUILD_FILES = {
    "pubspec.yaml", "pubspec.lock", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "gradle.properties",
    "gradle-wrapper.properties", "libs.versions.toml",
}
STATIC_CONFIG = {"analysis_options.yaml", ".editorconfig", "lint.xml", "detekt.yml", "detekt.yaml"}

RULES: dict[str, tuple[str, ...]] = {
    "system": (
        r"androidmanifest\.xml$", r"permissions?", r"notification", r"deeplink", r"intent",
        r"biometric", r"camera", r"location", r"bluetooth", r"foreground.?service",
    ),
    "performance": (
        r"(^|/)(lib|src|app)/", r"build\.gradle", r"pubspec\.yaml$", r"gradle\.properties$",
        r"render", r"image", r"list", r"animation", r"compose", r"widget",
    ),
    "network": (
        r"network", r"http", r"api", r"retrofit", r"dio", r"ktor", r"websocket", r"sync",
        r"remote", r"repository", r"connectivity", r"graphql", r"socket",
    ),
    "persistence": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref", r"datastore",
        r"storage", r"cache", r"sqlite", r"repository", r"model", r"drift", r"hive",
    ),
    "configuration": (
        r"activity", r"fragment", r"compose", r"widget", r"screen", r"page", r"view", r"layout",
        r"theme", r"orientation", r"resource", r"res/", r"lib/.*\.dart$",
    ),
    "resource_pressure": (
        r"service", r"worker", r"background", r"cache", r"image", r"bitmap", r"camera",
        r"media", r"memory", r"process", r"stream",
    ),
    "background": (
        r"service", r"worker", r"workmanager", r"background", r"alarm", r"job", r"notification",
        r"battery", r"doze", r"sync", r"foreground",
    ),
    "storage": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref", r"datastore",
        r"storage", r"file", r"sqlite", r"backup", r"cache", r"drift", r"hive",
    ),
    "upgrade": (
        r"database", r"migration", r"schema", r"androidmanifest\.xml$", r"build\.gradle",
        r"pubspec\.yaml$", r"version", r"applicationid", r"minsdk", r"targetsdk",
        r"settings\.gradle", r"libs\.versions\.toml",
    ),
}

CONTENT_SIGNALS: dict[str, tuple[str, ...]] = {
    "system": (
        "android.permission.", "notificationchannel", "pendingintent", "biometricprompt",
        "startforeground", "foregroundservicetype", "intentfilter",
    ),
    "network": (
        "http://", "https://", "retrofit", "okhttp", "dio(", "httpclient", "ktor",
        "websocket", "graphql", "connectivity",
    ),
    "persistence": (
        "@database", "@entity", "@dao", "roomdatabase", "migration(", "sqflite",
        "sharedpreferences", "datastore", "driftdatabase", "hive.",
    ),
    "background": (
        "workmanager", "worker", "alarmmanager", "jobscheduler", "startforeground",
        "foregroundservice", "doze", "batteryoptimization",
    ),
    "storage": (
        "openfile", "file(", "directory(", "getdatabasedirectory", "sqlite",
        "roomdatabase", "drift", "sharedpreferences",
    ),
    "resource_pressure": (
        "bitmap", "bytearray", "imagestream", "camera", "mediaplayer", "cache",
        "ontrimmemory", "processlifecycle",
    ),
    "configuration": (
        "configuration", "orientation", "savedstate", "viewmodel", "rememberSaveable".lower(),
        "lifecycle", "widget", "@composable",
    ),
    "performance": (
        "lazycolumn", "lazyrow", "listview", "image.", "bitmap", "animation",
        "recompose", "compute(", "isolates", "dispatcher",
    ),
}

RISK_PATTERNS: tuple[tuple[int, str, str], ...] = (
    (60, r"(migration|schema|database|room|drift|sqlite)", "database/schema"),
    (40, r"(androidmanifest\.xml|applicationid|minsdk|targetsdk|signing|proguard|r8)", "platform/build identity"),
    (35, r"(workmanager|worker|service|alarm|notification|foreground)", "background/system"),
    (30, r"(network|api|retrofit|dio|ktor|websocket|graphql|sync)", "network/sync"),
    (28, r"(pubspec\.ya?ml|build\.gradle|settings\.gradle|libs\.versions|gradle\.properties)", "dependency/build configuration"),
    (22, r"(router|navigation|deeplink|auth|login)", "navigation/auth"),
    (15, r"(screen|page|widget|compose|layout|theme)", "UI"),
)

def run_git(repo_root: Path, args: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
        return result.returncode, result.stdout
    except (OSError, subprocess.SubprocessError):
        return 2, ""

def valid_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value.strip().lower()))

def baseline_state(repo_root: Path, baseline_sha: str) -> dict[str, Any]:
    baseline = baseline_sha.strip().lower()
    if not valid_sha(baseline):
        return {"sha": baseline, "trusted": False, "ancestor": False, "reason": "missing-or-invalid-baseline"}
    code, _ = run_git(repo_root, ["cat-file", "-e", f"{baseline}^{{commit}}"], timeout=15)
    if code != 0:
        return {"sha": baseline, "trusted": False, "ancestor": False, "reason": "baseline-unavailable"}
    code, _ = run_git(repo_root, ["merge-base", "--is-ancestor", baseline, "HEAD"], timeout=15)
    if code != 0:
        return {"sha": baseline, "trusted": False, "ancestor": False, "reason": "baseline-not-ancestor"}
    return {"sha": baseline, "trusted": True, "ancestor": True, "reason": "trusted"}

def _parse_name_status(text: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        status = parts[0].strip()
        if status.startswith(("R", "C")) and len(parts) >= 3:
            changes.append({"status": status[0], "score": status[1:] or "", "old_path": parts[1], "path": parts[2]})
        elif len(parts) >= 2:
            changes.append({"status": status[:1], "old_path": "", "path": parts[1]})
    return changes

def _numstat(repo_root: Path, baseline: str) -> dict[str, tuple[int, int, bool]]:
    code, text = run_git(repo_root, ["diff", "--numstat", "--find-renames", f"{baseline}..HEAD"])
    if code != 0:
        return {}
    result: dict[str, tuple[int, int, bool]] = {}
    for raw in text.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        a, d, path = parts
        binary = a == "-" or d == "-"
        additions = 0 if binary else int(a or 0)
        deletions = 0 if binary else int(d or 0)
        result[path] = (additions, deletions, binary)
    return result

def git_diff_evidence(repo_root: Path, baseline_sha: str) -> dict[str, Any]:
    state = baseline_state(repo_root, baseline_sha)
    if not state["trusted"]:
        return {
            "baseline": state, "changes": [], "patch": "", "diff_truncated": False,
            "oversized": False, "total_additions": 0, "total_deletions": 0,
        }
    baseline = state["sha"]
    code, text = run_git(repo_root, ["diff", "--name-status", "--find-renames", f"{baseline}..HEAD"])
    if code != 0:
        state = {**state, "trusted": False, "reason": "diff-failed"}
        return {
            "baseline": state, "changes": [], "patch": "", "diff_truncated": False,
            "oversized": False, "total_additions": 0, "total_deletions": 0,
        }
    changes = _parse_name_status(text)
    stats = _numstat(repo_root, baseline)
    total_additions = total_deletions = 0
    for item in changes:
        stat = stats.get(item["path"], (0, 0, False))
        item["additions"], item["deletions"], item["binary"] = stat
        total_additions += item["additions"]
        total_deletions += item["deletions"]
    patch_code, patch = run_git(repo_root, ["diff", "--unified=0", "--no-ext-diff", "--no-color", f"{baseline}..HEAD"], timeout=45)
    diff_truncated = False
    if patch_code != 0:
        patch = ""
    encoded = patch.encode("utf-8", errors="ignore")
    if len(encoded) > MAX_DIFF_BYTES:
        patch = encoded[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
        diff_truncated = True
    return {
        "baseline": state,
        "changes": changes,
        "patch": patch,
        "diff_truncated": diff_truncated,
        "oversized": len(changes) > MAX_CHANGED_FILES,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
    }

def git_changed_files(repo_root: Path, baseline_sha: str = "") -> list[str]:
    evidence = git_diff_evidence(repo_root, baseline_sha)
    if not evidence["baseline"]["trusted"]:
        return []
    return sorted({str(x["path"]).replace("\\", "/") for x in evidence["changes"] if x.get("path")})

def is_doc(path: str) -> bool:
    p = Path(path.lower())
    stem = p.stem
    return p.parts[:1] == ("docs",) or stem in DOC_NAMES or p.name in {"code_of_conduct.md", "security.md"} or (len(p.parts) == 1 and p.suffix in {".md", ".rst"})

def is_test(path: str) -> bool:
    lower = f"/{path.lower()}/"
    name = Path(path.lower()).name
    return any(token in lower for token in ("/test/", "/tests/", "/androidtest/")) or name.endswith(("_test.dart", "test.kt", "tests.kt", "test.java"))

def is_generated(path: str) -> bool:
    lower = path.lower()
    return any(token in lower for token in ("/generated/", ".g.dart", ".freezed.dart", "/build/"))

def module_for(path: str) -> str:
    parts = Path(path).parts
    if "lib" in parts:
        i = parts.index("lib")
        if len(parts) > i + 2 and parts[i + 1] in {"features", "feature"}:
            return "/".join(parts[i:i+3])
        return "lib"
    if "src" in parts:
        i = parts.index("src")
        return "/".join(parts[:i]) or "."
    if parts and parts[0] not in {".github", "docs"}:
        return parts[0]
    return "."

def inspect_content(repo_root: Path, changes: list[dict[str, Any]], patch: str) -> tuple[dict[str, list[str]], list[str], int]:
    signals: dict[str, list[str]] = defaultdict(list)
    imports: list[str] = []
    budget = MAX_INSPECT_BYTES
    corpus = patch.lower()
    for item in changes:
        path = repo_root / item["path"]
        if budget <= 0 or not path.is_file() or path.is_symlink() or path.stat().st_size > 256_000:
            continue
        try:
            raw = path.read_bytes()[: min(path.stat().st_size, budget)]
            budget -= len(raw)
            text = raw.decode("utf-8", errors="ignore")
        except OSError:
            continue
        corpus += "\n" + text.lower()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "export ", "part ")):
                imports.append(stripped[:300])
    for lab, tokens in CONTENT_SIGNALS.items():
        for token in tokens:
            if token.lower() in corpus:
                signals[lab].append(token)
    return dict(signals), sorted(set(imports))[:200], MAX_INSPECT_BYTES - budget

def tracked_source_files(repo_root: Path) -> list[str]:
    code, raw = run_git(repo_root, ["ls-files", "-z", "*.dart", "*.kt", "*.java"], timeout=30)
    if code != 0:
        return []
    return [item.replace("\\", "/") for item in raw.split("\0") if item][:5000]

def dependency_impact(repo_root: Path, changed_paths: list[str]) -> dict[str, Any]:
    sources = tracked_source_files(repo_root)
    changed = {p for p in changed_paths if Path(p).suffix.lower() in CODE_SUFFIXES}
    if not changed or not sources:
        return {"dependents": [], "edges": [], "scanned_files": len(sources), "truncated": False}

    identifiers: dict[str, set[str]] = {}
    total_bytes = 0
    max_bytes = 8_000_000
    truncated = False

    def file_ids(path: str, text: str) -> set[str]:
        ids = {Path(path).stem.lower()}
        normalized = path.replace("\\", "/")
        if "/lib/" in "/" + normalized:
            rel = normalized.split("/lib/", 1)[-1]
            ids.add(rel.lower())
            ids.add(rel.removesuffix(".dart").lower())
        elif normalized.startswith("lib/"):
            rel = normalized[4:]
            ids.add(rel.lower())
            ids.add(rel.removesuffix(".dart").lower())
        package = re.search(r"(?m)^\s*package\s+([A-Za-z0-9_.]+)", text)
        if package:
            ids.add((package.group(1) + "." + Path(path).stem).lower())
        return {x for x in ids if len(x) >= 3}

    texts: dict[str, str] = {}
    for path in sources:
        source = repo_root / path
        try:
            size = source.stat().st_size
        except OSError:
            continue
        if size > 300_000 or total_bytes + size > max_bytes:
            truncated = True
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        total_bytes += size
        texts[path] = text
        identifiers[path] = file_ids(path, text)

    frontier = set(changed)
    dependents: set[str] = set()
    edges: list[dict[str, str]] = []
    for _ in range(2):
        tokens = set()
        for path in frontier:
            tokens.update(identifiers.get(path, {Path(path).stem.lower()}))
        if not tokens:
            break
        next_frontier: set[str] = set()
        for path, text in texts.items():
            if path in changed or path in dependents:
                continue
            import_lines = "\n".join(
                line.strip().lower()
                for line in text.splitlines()
                if line.strip().startswith(("import ", "export ", "part "))
            )
            if not import_lines:
                continue
            matched = next((token for token in tokens if token in import_lines), "")
            if matched:
                dependents.add(path)
                next_frontier.add(path)
                edges.append({"from": path, "to_token": matched})
        frontier = next_frontier
        if not frontier:
            break

    return {
        "dependents": sorted(dependents)[:500],
        "edges": edges[:1000],
        "scanned_files": len(texts),
        "truncated": truncated,
        "scanned_bytes": total_bytes,
    }

def selected_labs_for(paths: list[str], content_signals: dict[str, list[str]]) -> tuple[dict[str, bool], dict[str, list[str]]]:
    selected = {lab: False for lab in LABS}
    reasons: dict[str, list[str]] = {lab: [] for lab in LABS}
    for path in paths:
        lower = path.lower()
        suffix = Path(lower).suffix
        for lab, patterns in RULES.items():
            if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in patterns):
                selected[lab] = True
                reasons[lab].append(path)
        if suffix in SOURCE_SUFFIXES and ("/src/" in f"/{lower}" or lower.startswith(("lib/", "app/"))):
            selected["performance"] = True
            if path not in reasons["performance"]:
                reasons["performance"].append(path)
    for lab, tokens in content_signals.items():
        if tokens:
            selected[lab] = True
            reasons[lab].append("content:" + ",".join(tokens[:8]))
    return selected, reasons

def load_history_risk(path: str, repository: str, selected: dict[str, bool]) -> dict[str, Any]:
    result = {"records": 0, "recent_failures": 0, "lab_failures": {}, "risk_bonus": 0}
    if not path or not repository:
        return result
    source = Path(path)
    if not source.is_file():
        return result
    rows: list[dict[str, Any]] = []
    for raw in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and str(row.get("repository", "")) == repository:
            rows.append(row)
    rows = rows[-30:]
    result["records"] = len(rows)
    for row in rows:
        if str(row.get("result", "")).upper() == "FAIL":
            result["recent_failures"] += 1
        for lab in LABS:
            if selected.get(lab) and str(row.get(f"{lab}_lab" if lab != "system" else "system_lab", "")).upper() in {"FAIL", "ERROR"}:
                result["lab_failures"][lab] = int(result["lab_failures"].get(lab, 0)) + 1
    bonus = min(20, result["recent_failures"] * 3 + sum(result["lab_failures"].values()) * 4)
    result["risk_bonus"] = bonus
    return result

def risk_and_confidence(evidence: dict[str, Any], selected: dict[str, bool], history: dict[str, Any]) -> tuple[int, str, float, list[str]]:
    changes = evidence["changes"]
    score = 0
    reasons: list[str] = []
    paths = [str(x.get("path", "")) for x in changes]
    joined = "\n".join(paths).lower()
    for points, pattern, label in RISK_PATTERNS:
        if re.search(pattern, joined, re.IGNORECASE):
            score += points
            reasons.append(label)
    deletes = sum(1 for x in changes if x.get("status") == "D")
    renames = sum(1 for x in changes if x.get("status") == "R")
    churn = evidence["total_additions"] + evidence["total_deletions"]
    if deletes:
        score += min(20, deletes * 5)
        reasons.append(f"{deletes} deletion(s)")
    if renames:
        score += min(12, renames * 3)
        reasons.append(f"{renames} rename(s)")
    if len(changes) >= 20:
        score += 15
        reasons.append("broad change-set")
    if churn >= 800:
        score += 20
        reasons.append("high line churn")
    elif churn >= 250:
        score += 10
        reasons.append("medium line churn")
    score += int(history.get("risk_bonus", 0))
    if history.get("risk_bonus"):
        reasons.append("historical failures in affected area")
    score = min(100, score)

    if score >= 75:
        level = "CRITICAL"
    elif score >= 50:
        level = "HIGH"
    elif score >= 25:
        level = "MEDIUM"
    else:
        level = "LOW"

    confidence = 0.98
    if evidence["diff_truncated"]:
        confidence -= 0.25
    if evidence["oversized"]:
        confidence -= 0.40
    if not evidence["baseline"]["trusted"]:
        confidence = 0.0
    if len(changes) >= 100:
        confidence -= 0.15
    if not any(selected.values()) and any(Path(p).suffix.lower() in CODE_SUFFIXES for p in paths):
        confidence -= 0.20
    confidence = max(0.0, min(1.0, round(confidence, 2)))
    return score, level, confidence, reasons

def static_plan(repo_root: Path, paths: list[str], engine: str, working_directory: str = ".") -> dict[str, Any]:
    prefix = working_directory.strip().strip("/")
    scoped: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if prefix and prefix != ".":
            marker = prefix + "/"
            if not normalized.startswith(marker):
                continue
            normalized = normalized[len(marker):]
        scoped.append(normalized)
    project_root = repo_root / prefix if prefix and prefix != "." else repo_root
    dart = [p for p in scoped if p.lower().endswith(".dart") and not is_generated(p)]
    analyze_targets: set[str] = set()
    test_targets: set[str] = set()
    for p in dart:
        if p.startswith("lib/"):
            parts = Path(p).parts
            if len(parts) >= 3 and parts[1] in {"features", "feature"}:
                analyze_targets.add("/".join(parts[:3]))
            else:
                analyze_targets.add("lib")
            candidate = Path("test") / Path(*parts[1:])
            candidate = candidate.with_name(candidate.stem + "_test.dart")
            if (project_root / candidate).is_file():
                test_targets.add(candidate.as_posix())
        if is_test(p):
            test_targets.add(p)
    modules = sorted({module_for(p) for p in scoped if Path(p).suffix.lower() in SOURCE_SUFFIXES})
    return {
        "engine": engine,
        "targeted": bool(paths),
        "flutter_analyze_targets": sorted(analyze_targets),
        "flutter_test_targets": sorted(test_targets),
        "native_modules": modules,
    }

def deterministic_shadow(head_sha: str, lane: str, requested_mode: str) -> bool:
    if requested_mode != "fast" or lane != "FAST_RUNTIME" or not valid_sha(head_sha):
        return False
    return int(head_sha[:8], 16) % 10 == 0

def current_head(repo_root: Path) -> str:
    code, value = run_git(repo_root, ["rev-parse", "HEAD"], timeout=10)
    value = value.strip().lower()
    return value if code == 0 and valid_sha(value) else ""

def build_plan(
    repo_root: Path,
    mode: str,
    baseline_sha: str = "",
    engine: str = "unknown",
    history_file: str = "",
    repository: str = "",
    working_directory: str = ".",
) -> dict[str, Any]:
    requested = mode.lower().strip()
    if requested not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")
    head_sha = current_head(repo_root)

    if requested in {"full", "certification"}:
        selected = {lab: True for lab in LABS}
        reasons = {lab: [requested.upper() + " mode"] for lab in LABS}
        lane = "CERTIFICATION" if requested == "certification" else "FULL_RUNTIME"
        return {
            "schema_version": SCHEMA_VERSION,
            "planner_version": VERSION,
            "requested_mode": requested,
            "mode": requested,
            "lane": lane,
            "head_sha": head_sha,
            "baseline_sha": baseline_sha.strip().lower(),
            "baseline": {"sha": baseline_sha.strip().lower(), "trusted": True, "ancestor": True, "reason": "not-required"},
            "changed_files": [],
            "changes": [],
            "selected_labs": selected,
            "reasons": reasons,
            "impacted_modules": [],
            "dependency_signals": {},
            "imports": [],
            "risk": {"score": 100 if requested == "certification" else 75, "level": "CRITICAL" if requested == "certification" else "HIGH", "reasons": [requested + " explicitly requested"]},
            "confidence": 1.0,
            "static_plan": static_plan(repo_root, [], engine, working_directory),
            "run": {"static": True, "build": True, "runtime": True, "full_static": True},
            "fallback_full": False,
            "fallback_reason": "",
            "shadow_full": False,
            "history_risk": {},
            "diff": {"files": 0, "additions": 0, "deletions": 0, "truncated": False, "oversized": False},
        }

    evidence = git_diff_evidence(repo_root, baseline_sha)
    if not evidence["baseline"]["trusted"]:
        plan = build_plan(repo_root, "full", baseline_sha, engine, history_file, repository, working_directory)
        plan.update({
            "requested_mode": "fast",
            "fallback_full": True,
            "fallback_reason": evidence["baseline"]["reason"],
            "baseline": evidence["baseline"],
            "mode": "full",
            "lane": "FULL_RUNTIME",
        })
        for lab in LABS:
            plan["reasons"][lab] = ["FAST fail-safe: " + evidence["baseline"]["reason"]]
        return plan

    changes = evidence["changes"]
    paths = sorted({str(x["path"]).replace("\\", "/") for x in changes})
    if not paths:
        selected = {lab: False for lab in LABS}
        return {
            "schema_version": SCHEMA_VERSION, "planner_version": VERSION,
            "requested_mode": "fast", "mode": "fast", "lane": "NO_RUNTIME_CHANGE",
            "head_sha": head_sha, "baseline_sha": baseline_sha.strip().lower(), "baseline": evidence["baseline"],
            "changed_files": [], "changes": [], "selected_labs": selected,
            "reasons": {lab: [] for lab in LABS}, "impacted_modules": [], "dependency_signals": {}, "imports": [],
            "risk": {"score": 0, "level": "LOW", "reasons": ["no source changes"]},
            "confidence": 1.0, "static_plan": static_plan(repo_root, [], engine, working_directory),
            "run": {"static": False, "build": False, "runtime": False, "full_static": False},
            "fallback_full": False, "fallback_reason": "", "shadow_full": False, "history_risk": {},
            "diff": {"files": 0, "additions": 0, "deletions": 0, "truncated": evidence["diff_truncated"], "oversized": evidence["oversized"]},
        }

    content_signals, imports, inspected = inspect_content(repo_root, changes, evidence["patch"])
    dependency = dependency_impact(repo_root, paths)
    impact_paths = sorted(set(paths) | set(dependency.get("dependents", [])))
    selected, reasons = selected_labs_for(impact_paths, content_signals)
    for lab in LABS:
        transitive = [p for p in dependency.get("dependents", []) if p in reasons[lab]]
        if transitive:
            reasons[lab].append("transitive-dependency-impact")
    history = load_history_risk(history_file, repository, selected)
    risk_score, risk_level, confidence, risk_reasons = risk_and_confidence(evidence, selected, history)
    if dependency.get("truncated"):
        confidence = max(0.0, round(confidence - 0.10, 2))
        risk_reasons.append("dependency graph scan truncated")
    if len(dependency.get("dependents", [])) >= 20:
        risk_score = min(100, risk_score + 10)
        if risk_score >= 75:
            risk_level = "CRITICAL"
        elif risk_score >= 50:
            risk_level = "HIGH"
        elif risk_score >= 25:
            risk_level = "MEDIUM"
        risk_reasons.append("broad transitive dependency impact")

    non_docs = [p for p in paths if not is_doc(p)]
    only_docs = not non_docs
    only_tests_or_static = bool(non_docs) and all(is_test(p) or Path(p).name.lower() in STATIC_CONFIG or p.startswith(".github/") for p in non_docs)

    fallback = False
    fallback_reason = ""
    if evidence["oversized"]:
        fallback = True
        fallback_reason = "changed-file set exceeds safe selective limit"
    elif evidence["diff_truncated"]:
        fallback = True
        fallback_reason = "diff exceeds inspection budget"
    elif confidence < 0.75:
        fallback = True
        fallback_reason = "impact confidence below safety threshold"
    elif risk_level in {"HIGH", "CRITICAL"}:
        fallback = True
        fallback_reason = "high-risk change requires complete runtime coverage"

    if fallback:
        lane = "FULL_RUNTIME"
        effective_mode = "full"
        selected = {lab: True for lab in LABS}
        for lab in LABS:
            reasons[lab] = list(dict.fromkeys(reasons[lab] + ["FAST escalation: " + fallback_reason]))
        run = {"static": True, "build": True, "runtime": True, "full_static": True}
    elif only_docs:
        lane = "NO_RUNTIME_CHANGE"
        effective_mode = "fast"
        selected = {lab: False for lab in LABS}
        run = {"static": False, "build": False, "runtime": False, "full_static": False}
    elif only_tests_or_static:
        lane = "STATIC_ONLY"
        effective_mode = "fast"
        selected = {lab: False for lab in LABS}
        run = {"static": True, "build": False, "runtime": False, "full_static": False}
    else:
        lane = "FAST_RUNTIME"
        effective_mode = "fast"
        code_files = [p for p in paths if Path(p).suffix.lower() in CODE_SUFFIXES]
        if code_files and not any(selected.values()):
            selected["configuration"] = True
            selected["performance"] = True
            reasons["configuration"].append("generic application-code change")
            reasons["performance"].append("generic application-code change")
        run = {"static": True, "build": True, "runtime": True, "full_static": False}

    shadow = deterministic_shadow(head_sha, lane, requested)
    return {
        "schema_version": SCHEMA_VERSION,
        "planner_version": VERSION,
        "requested_mode": requested,
        "mode": effective_mode,
        "lane": lane,
        "head_sha": head_sha,
        "baseline_sha": baseline_sha.strip().lower(),
        "baseline": evidence["baseline"],
        "changed_files": paths,
        "changes": changes[:MAX_CHANGED_FILES],
        "selected_labs": selected,
        "reasons": reasons,
        "impacted_modules": sorted({module_for(p) for p in impact_paths}),
        "dependency_signals": content_signals,
        "dependency_graph": dependency,
        "imports": imports,
        "risk": {"score": risk_score, "level": risk_level, "reasons": risk_reasons},
        "confidence": confidence,
        "static_plan": static_plan(repo_root, impact_paths, engine, working_directory),
        "run": run,
        "fallback_full": fallback,
        "fallback_reason": fallback_reason,
        "shadow_full": shadow,
        "history_risk": history,
        "diff": {
            "files": len(paths), "additions": evidence["total_additions"], "deletions": evidence["total_deletions"],
            "truncated": evidence["diff_truncated"], "oversized": evidence["oversized"], "inspected_bytes": inspected,
        },
    }

def classify(files: list[str], mode: str, baseline_sha: str = "") -> dict[str, Any]:
    # Compatibility helper for older callers/self-tests without repository context.
    requested = mode.lower().strip()
    if requested in {"full", "certification"}:
        selected = {lab: True for lab in LABS}
        reasons = {lab: [requested.upper() + " mode"] for lab in LABS}
        return {
            "schema_version": SCHEMA_VERSION, "planner_version": VERSION, "requested_mode": requested,
            "mode": requested, "lane": "CERTIFICATION" if requested == "certification" else "FULL_RUNTIME",
            "baseline_sha": baseline_sha, "changed_files": files, "changes": [],
            "selected_labs": selected, "reasons": reasons, "fallback_full": False,
            "risk": {"score": 75, "level": "HIGH", "reasons": []}, "confidence": 1.0,
            "run": {"static": True, "build": True, "runtime": True, "full_static": True},
            "shadow_full": False, "static_plan": {}, "diff": {"files": len(files)},
        }
    if not files:
        selected = {lab: True for lab in LABS}
        return {
            "schema_version": SCHEMA_VERSION, "planner_version": VERSION, "requested_mode": "fast",
            "mode": "full", "lane": "FULL_RUNTIME", "baseline_sha": baseline_sha, "changed_files": [],
            "changes": [], "selected_labs": selected,
            "reasons": {lab: ["no reliable changed-file set; safe FULL fallback"] for lab in LABS},
            "fallback_full": True, "fallback_reason": "no reliable changed-file set",
            "risk": {"score": 75, "level": "HIGH", "reasons": []}, "confidence": 0.0,
            "run": {"static": True, "build": True, "runtime": True, "full_static": True},
            "shadow_full": False, "static_plan": {}, "diff": {"files": 0},
        }
    selected, reasons = selected_labs_for(files, {})
    if all(is_doc(p) for p in files):
        selected = {lab: False for lab in LABS}
        lane = "NO_RUNTIME_CHANGE"
    elif all(is_test(p) or Path(p).name.lower() in STATIC_CONFIG or p.startswith(".github/") for p in files):
        selected = {lab: False for lab in LABS}
        lane = "STATIC_ONLY"
    else:
        lane = "FAST_RUNTIME"
    return {
        "schema_version": SCHEMA_VERSION, "planner_version": VERSION, "requested_mode": "fast",
        "mode": "fast", "lane": lane, "baseline_sha": baseline_sha, "changed_files": files,
        "changes": [], "selected_labs": selected, "reasons": reasons, "fallback_full": False,
        "fallback_reason": "", "risk": {"score": 10, "level": "LOW", "reasons": []}, "confidence": 0.9,
        "run": {"static": lane != "NO_RUNTIME_CHANGE", "build": lane == "FAST_RUNTIME", "runtime": lane == "FAST_RUNTIME", "full_static": False},
        "shadow_full": False, "static_plan": {}, "diff": {"files": len(files)},
    }

def validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid analysis plan schema")
    mode = str(payload.get("mode", "")).lower()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("invalid analysis plan mode")
    lane = str(payload.get("lane", ""))
    if lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY", "FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}:
        raise ValueError("invalid analysis lane")
    selected = payload.get("selected_labs")
    if not isinstance(selected, dict) or set(selected) != set(LABS) or not all(isinstance(selected[k], bool) for k in LABS):
        raise ValueError("analysis plan selected_labs mismatch")
    files = payload.get("changed_files", [])
    if not isinstance(files, list):
        raise ValueError("changed_files must be an array")
    for path in files[:MAX_CHANGED_FILES]:
        if not isinstance(path, str) or len(path) > 500 or "\n" in path or "\r" in path:
            raise ValueError("invalid changed file path")
    confidence = payload.get("confidence", 0)
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("invalid confidence")
    run = payload.get("run", {})
    if not isinstance(run, dict) or not all(isinstance(run.get(k), bool) for k in ("static", "build", "runtime", "full_static")):
        raise ValueError("invalid run plan")
    return payload

def write_github_output(path: Path, plan: dict[str, Any]) -> None:
    run = plan["run"]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"lane={plan['lane']}\n")
        handle.write(f"effective_mode={plan['mode']}\n")
        handle.write(f"risk_level={plan['risk']['level']}\n")
        handle.write(f"risk_score={plan['risk']['score']}\n")
        handle.write(f"confidence={plan['confidence']}\n")
        handle.write(f"run_static={str(run['static']).lower()}\n")
        handle.write(f"run_build={str(run['build']).lower()}\n")
        handle.write(f"run_runtime={str(run['runtime']).lower()}\n")
        handle.write(f"full_static={str(run['full_static']).lower()}\n")
        handle.write(f"shadow_full={str(bool(plan.get('shadow_full'))).lower()}\n")
        handle.write(f"fallback_full={str(bool(plan.get('fallback_full'))).lower()}\n")

def self_test() -> None:
    import tempfile
    docs = classify(["README.md"], "fast", "a" * 40)
    assert docs["lane"] == "NO_RUNTIME_CHANGE"
    db = classify(["app/src/main/java/x/AppDatabase.kt"], "fast", "a" * 40)
    assert db["selected_labs"]["storage"] and db["selected_labs"]["persistence"]
    cert = classify(["README.md"], "certification", "a" * 40)
    assert cert["lane"] == "CERTIFICATION" and all(cert["selected_labs"].values())

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "applab@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "AppLab Self Test"], check=True)
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
        baseline = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        base_branch = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()

        db_file = root / "app" / "src" / "main" / "java" / "x" / "AppDatabase.kt"
        db_file.parent.mkdir(parents=True)
        db_file.write_text("import androidx.room.Database\nclass AppDatabase\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "database change"], check=True)
        (root / "README.md").write_text("docs-only final commit\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "docs change"], check=True)

        plan = build_plan(root, "fast", baseline, "native_android")
        assert plan["baseline"]["ancestor"] is True
        assert plan["selected_labs"]["persistence"] and plan["selected_labs"]["storage"]
        assert plan["lane"] == "FULL_RUNTIME"  # database change is intentionally high risk
        assert plan["fallback_full"]

        unrelated = "f" * 40
        fallback = build_plan(root, "fast", unrelated, "native_android")
        assert fallback["mode"] == "full" and fallback["fallback_full"]

        # Diverged baseline must never reduce coverage.
        subprocess.run(["git", "-C", str(root), "checkout", "-qb", "other", baseline], check=True)
        (root / "other.txt").write_text("other\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "other branch"], check=True)
        other_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run(["git", "-C", str(root), "checkout", "-q", base_branch], check=True)
        diverged = build_plan(root, "fast", other_sha, "native_android")
        assert diverged["fallback_full"] and diverged["fallback_reason"] == "baseline-not-ancestor"

    print("AppLab Adaptive Impact Planner self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode", choices=("fast", "full", "certification"), default="full")
    parser.add_argument("--baseline-sha", default="")
    parser.add_argument("--engine", default="unknown")
    parser.add_argument("--history-file", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--working-directory", default=".")
    parser.add_argument("--output")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.output:
        raise SystemExit("--repo-root and --output are required")
    started = time.perf_counter()
    plan = build_plan(
        Path(args.repo_root).resolve(), args.mode, args.baseline_sha,
        args.engine, args.history_file, args.repository, args.working_directory,
    )
    plan["planner_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    validate_plan(plan)
    Path(args.output).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.github_output:
        write_github_output(Path(args.github_output), plan)
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
