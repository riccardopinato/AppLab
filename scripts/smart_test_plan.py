#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

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

LANES = (
    "no_runtime",
    "static_only",
    "fast_runtime",
    "full_runtime",
    "certification",
)

SOURCE_SUFFIXES = {
    ".kt", ".java", ".dart", ".xml", ".gradle", ".kts", ".toml",
    ".json", ".yaml", ".yml", ".properties",
}
DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc"}
TEST_MARKERS = (
    "/test/", "/tests/", "/androidtest/", "/test_", "_test.", "src/test/",
)
GENERATED_MARKERS = (
    ".g.dart", ".freezed.dart", "/generated/", "/build/", ".gen.",
)

RULES: dict[str, tuple[str, ...]] = {
    "system": (
        r"androidmanifest\.xml$", r"permissions?", r"notification", r"deeplink",
        r"intent", r"biometric", r"camera", r"location", r"bluetooth",
        r"foreground.?service", r"broadcastreceiver", r"appop",
    ),
    "performance": (
        r"(^|/)(lib|src|app)/", r"build\.gradle", r"pubspec\.yaml$",
        r"gradle\.properties$", r"render", r"image", r"list", r"animation",
        r"compose", r"widget",
    ),
    "network": (
        r"network", r"http", r"api", r"retrofit", r"dio", r"ktor",
        r"websocket", r"sync", r"remote", r"repository", r"connectivity",
        r"graphql", r"socket",
    ),
    "persistence": (
        r"database", r"room", r"dao", r"entity", r"migration",
        r"shared.?pref", r"datastore", r"storage", r"cache", r"sqlite",
        r"repository", r"model", r"drift", r"hive", r"isar",
    ),
    "configuration": (
        r"activity", r"fragment", r"compose", r"widget", r"screen", r"page",
        r"view", r"layout", r"theme", r"orientation", r"resource", r"res/",
        r"lib/.*\.dart$",
    ),
    "resource_pressure": (
        r"service", r"worker", r"background", r"cache", r"image", r"bitmap",
        r"camera", r"media", r"memory", r"process", r"stream",
    ),
    "background": (
        r"service", r"worker", r"workmanager", r"background", r"alarm", r"job",
        r"notification", r"battery", r"doze", r"sync", r"receiver",
    ),
    "storage": (
        r"database", r"room", r"dao", r"entity", r"migration",
        r"shared.?pref", r"datastore", r"storage", r"file", r"sqlite",
        r"backup", r"cache", r"drift", r"hive", r"isar",
    ),
    "upgrade": (
        r"database", r"migration", r"schema", r"androidmanifest\.xml$",
        r"build\.gradle", r"pubspec\.yaml$", r"version", r"applicationid",
        r"minsdk", r"targetsdk", r"compileSdk", r"settings\.gradle",
    ),
}

CONTENT_RULES: dict[str, tuple[str, ...]] = {
    "system": (
        r"requestPermissions?", r"NotificationManager", r"PendingIntent",
        r"BiometricPrompt", r"startForeground", r"registerReceiver",
    ),
    "network": (
        r"https?://", r"Retrofit", r"Dio\(", r"HttpClient", r"WebSocket",
        r"Connectivity", r"ktor", r"graphql",
    ),
    "persistence": (
        r"@Database", r"@Entity", r"@Dao", r"Room\.databaseBuilder",
        r"SharedPreferences", r"DataStore", r"sqlite", r"Migration\(",
        r"drift", r"Hive", r"Isar",
    ),
    "background": (
        r"WorkManager", r"CoroutineWorker", r"Worker\(", r"AlarmManager",
        r"JobScheduler", r"ForegroundService", r"startForegroundService",
    ),
    "resource_pressure": (
        r"Bitmap", r"ImageDecoder", r"onTrimMemory", r"ByteArray",
        r"Stream<", r"Flow<", r"Camera", r"MediaPlayer",
    ),
}

CRITICAL_PATH_RULES: tuple[tuple[str, int, str], ...] = (
    (r"androidmanifest\.xml$", 28, "Android manifest changed"),
    (r"(build|settings)\.gradle(\.kts)?$", 22, "Gradle build topology changed"),
    (r"gradle\.properties$", 18, "Gradle runtime configuration changed"),
    (r"pubspec\.yaml$", 22, "Flutter dependency/build manifest changed"),
    (r"pubspec\.lock$", 16, "Flutter dependency lock changed"),
    (r"migration|schema|database", 30, "database/schema surface changed"),
    (r"applicationid|minsdk|targetsdk|compilesdk|versioncode|versionname", 35, "release identity/platform level changed"),
    (r"signing|keystore", 40, "signing configuration changed"),
    (r"service|worker|alarm|receiver|notification", 22, "background/system component changed"),
    (r"network|api|http|sync", 18, "network/sync surface changed"),
)

STATIC_CONFIG_NAMES = {
    "analysis_options.yaml",
    "lint.xml",
    "detekt.yml",
    "detekt.yaml",
    "ktlint.yml",
    "ktlint.yaml",
}

def run_git(repo_root: Path, args: list[str], timeout: int = 30) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )
    return result.returncode, result.stdout

def valid_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value.strip().lower()))

def tracked_files(repo_root: Path) -> list[str]:
    status, output = run_git(repo_root, ["ls-files", "-z"], timeout=30)
    if status != 0:
        return []
    return sorted({item.replace("\\", "/") for item in output.split("\0") if item})

def baseline_is_ancestor(repo_root: Path, baseline_sha: str) -> bool:
    baseline = baseline_sha.strip().lower()
    if not valid_sha(baseline):
        return False
    exists, _ = run_git(repo_root, ["cat-file", "-e", f"{baseline}^{{commit}}"], timeout=15)
    if exists != 0:
        return False
    ancestor, _ = run_git(repo_root, ["merge-base", "--is-ancestor", baseline, "HEAD"], timeout=20)
    return ancestor == 0

def parse_name_status(output: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in output.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            items.append({"status": "R", "old_path": parts[1], "path": parts[2]})
        elif len(parts) >= 2:
            items.append({"status": status[:1], "path": parts[1]})
    return items

def parse_numstat(output: str) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for raw in output.splitlines():
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, path = parts[0], parts[1], parts[-1]
        try:
            added = int(added_raw) if added_raw.isdigit() else 0
            deleted = int(deleted_raw) if deleted_raw.isdigit() else 0
        except ValueError:
            added = deleted = 0
        stats[path] = {"added": added, "deleted": deleted}
    return stats

def git_change_set(repo_root: Path, baseline_sha: str) -> dict[str, Any]:
    baseline = baseline_sha.strip().lower()
    if not baseline_is_ancestor(repo_root, baseline):
        return {
            "trusted": False,
            "reason": "baseline missing, invalid, or not an ancestor of HEAD",
            "baseline_sha": baseline,
            "files": [],
            "changes": [],
            "total_added": 0,
            "total_deleted": 0,
            "too_large": False,
        }

    status1, names = run_git(
        repo_root,
        ["diff", "--name-status", "--find-renames=70%", f"{baseline}..HEAD"],
    )
    status2, nums = run_git(
        repo_root,
        ["diff", "--numstat", "--find-renames=70%", f"{baseline}..HEAD"],
    )
    if status1 != 0 or status2 != 0:
        return {
            "trusted": False,
            "reason": "git diff failed",
            "baseline_sha": baseline,
            "files": [],
            "changes": [],
            "total_added": 0,
            "total_deleted": 0,
            "too_large": False,
        }

    changes = parse_name_status(names)
    stats = parse_numstat(nums)
    for item in changes:
        path = item["path"].replace("\\", "/")
        item["path"] = path
        row = stats.get(path, {"added": 0, "deleted": 0})
        item["added"] = row["added"]
        item["deleted"] = row["deleted"]

    files = sorted({item["path"] for item in changes})
    total_added = sum(int(item.get("added", 0)) for item in changes)
    total_deleted = sum(int(item.get("deleted", 0)) for item in changes)
    return {
        "trusted": True,
        "reason": "",
        "baseline_sha": baseline,
        "files": files,
        "changes": changes,
        "total_added": total_added,
        "total_deleted": total_deleted,
        "too_large": len(files) > 500 or (total_added + total_deleted) > 20000,
    }

def git_changed_files(repo_root: Path, baseline_sha: str = "") -> list[str]:
    return list(git_change_set(repo_root, baseline_sha).get("files", []))

def read_changed_content(repo_root: Path, files: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    budget = 1_500_000
    for rel in files[:250]:
        path = repo_root / rel
        if not path.is_file() or path.is_symlink():
            continue
        if Path(rel.lower()).suffix not in SOURCE_SUFFIXES:
            continue
        try:
            size = path.stat().st_size
            if size > 200_000 or size > budget:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        result[rel] = text
        budget -= len(text.encode("utf-8", errors="ignore"))
        if budget <= 0:
            break
    return result

def extract_import_targets(path: str, text: str) -> set[str]:
    targets: set[str] = set()
    suffix = Path(path).suffix.lower()
    if suffix == ".dart":
        for match in re.finditer(r"^\s*import\s+['\"]([^'\"]+)['\"]", text, re.MULTILINE):
            value = match.group(1)
            if value.startswith("package:") or value.startswith("dart:"):
                continue
            targets.add(value)
    elif suffix in {".kt", ".java"}:
        for match in re.finditer(r"^\s*import\s+([A-Za-z0-9_.*]+)", text, re.MULTILINE):
            targets.add(match.group(1))
    return targets

def build_dependency_impact(repo_root: Path, changed_files: list[str]) -> dict[str, Any]:
    tracked = tracked_files(repo_root)
    source = [
        p for p in tracked
        if Path(p).suffix.lower() in {".dart", ".kt", ".java"}
        and not any(marker in p.lower() for marker in GENERATED_MARKERS)
    ]
    if len(source) > 4000:
        source = source[:4000]

    basename_index: dict[str, set[str]] = defaultdict(set)
    package_index: dict[str, set[str]] = defaultdict(set)
    contents: dict[str, str] = {}
    for rel in source:
        path = repo_root / rel
        try:
            if path.stat().st_size > 120_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        contents[rel] = text
        basename_index[Path(rel).name].add(rel)
        package = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)", text, re.MULTILINE)
        if package:
            package_index[package.group(1)].add(rel)

    reverse: dict[str, set[str]] = defaultdict(set)
    for rel, text in contents.items():
        for target in extract_import_targets(rel, text):
            candidates: set[str] = set()
            if rel.endswith(".dart"):
                target_name = Path(target).name
                candidates |= basename_index.get(target_name, set())
            else:
                if target.endswith(".*"):
                    prefix = target[:-2]
                    for package, values in package_index.items():
                        if package.startswith(prefix):
                            candidates |= values
                else:
                    target_name = target.rsplit(".", 1)[-1] + Path(rel).suffix
                    candidates |= basename_index.get(target_name, set())
            for candidate in candidates:
                reverse[candidate].add(rel)

    impacted: set[str] = set(changed_files)
    queue: deque[tuple[str, int]] = deque((item, 0) for item in changed_files)
    while queue:
        item, depth = queue.popleft()
        if depth >= 2:
            continue
        for dependent in reverse.get(item, set()):
            if dependent not in impacted:
                impacted.add(dependent)
                queue.append((dependent, depth + 1))
        if len(impacted) >= 250:
            break

    return {
        "tracked_source_files": len(contents),
        "direct_changed": len(changed_files),
        "impacted_files": sorted(impacted),
        "transitive_impacted_count": max(0, len(impacted) - len(changed_files)),
    }

def is_docs_only(files: list[str]) -> bool:
    if not files:
        return False
    for path in files:
        lower = path.lower()
        suffix = Path(lower).suffix
        if lower.startswith((".github/", "docs/")):
            continue
        if Path(lower).name.startswith(("readme", "changelog", "license", "contributing")):
            continue
        if suffix in DOC_SUFFIXES:
            continue
        return False
    return True

def is_static_only(files: list[str]) -> bool:
    if not files:
        return False
    non_static = []
    for path in files:
        lower = f"/{path.lower()}"
        name = Path(path).name.lower()
        if any(marker in lower for marker in TEST_MARKERS):
            continue
        if name in STATIC_CONFIG_NAMES:
            continue
        if path.lower().startswith(".github/"):
            continue
        non_static.append(path)
    return not non_static

def historical_risk(history_file: str, repository: str, files: list[str]) -> tuple[int, list[str]]:
    if not history_file or not repository:
        return 0, []
    path = Path(history_file)
    if not path.is_file():
        return 0, []
    tokens = {
        token
        for file in files
        for token in re.split(r"[^a-z0-9]+", file.lower())
        if len(token) >= 5
    }
    failures = 0
    reasons: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-250:]:
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("repository") != repository:
            continue
        if str(row.get("result", "")).upper() != "FAIL":
            continue
        reason = str(row.get("reason", "")).lower()
        if not tokens or any(token in reason for token in tokens):
            failures += 1
    if failures:
        reasons.append(f"{failures} recent related/unknown project failures increase risk")
    return min(18, failures * 3), reasons

def choose_flutter_targets(files: list[str]) -> dict[str, list[str]]:
    analyze: set[str] = set()
    tests: set[str] = set()
    for path in files:
        lower = path.lower()
        p = Path(path)
        if lower.startswith("lib/") and p.suffix == ".dart":
            parts = p.parts
            analyze.add("/".join(parts[: min(3, len(parts) - 1)]) if len(parts) > 2 else "lib")
            stem = p.stem
            for candidate in (
                f"test/{stem}_test.dart",
                f"test/{'/'.join(parts[1:-1])}/{stem}_test.dart" if len(parts) > 2 else "",
            ):
                if candidate:
                    tests.add(candidate.replace("//", "/"))
        elif any(marker in f"/{lower}" for marker in TEST_MARKERS) and p.suffix == ".dart":
            tests.add(path)
    return {"analyze": sorted(analyze), "tests": sorted(tests)}

def choose_android_targets(files: list[str]) -> dict[str, list[str]]:
    modules: set[str] = set()
    tests: set[str] = set()
    for path in files:
        parts = Path(path).parts
        if not parts:
            continue
        if parts[0] not in {".github", "gradle", "buildSrc"}:
            if len(parts) > 1 and parts[1] in {"src", "build.gradle", "build.gradle.kts"}:
                modules.add(parts[0])
            elif parts[0] == "app":
                modules.add("app")
        lower = f"/{path.lower()}"
        if any(marker in lower for marker in TEST_MARKERS):
            tests.add(path)
    return {"modules": sorted(modules), "tests": sorted(tests)}

def score_risk(
    files: list[str],
    changes: list[dict[str, Any]],
    contents: dict[str, str],
    dependency_impact: dict[str, Any],
    historical_score: int,
) -> tuple[int, list[str]]:
    if not files:
        return 100, ["no trustworthy change set"]
    if is_docs_only(files):
        return 2, ["documentation-only change"]

    score = 8
    reasons: list[str] = []
    churn = sum(int(x.get("added", 0)) + int(x.get("deleted", 0)) for x in changes)
    if churn > 5000:
        score += 35
        reasons.append("very large code churn")
    elif churn > 1500:
        score += 25
        reasons.append("large code churn")
    elif churn > 500:
        score += 14
        reasons.append("moderate code churn")
    elif churn > 100:
        score += 6

    if len(files) > 100:
        score += 30
        reasons.append("wide file fan-out")
    elif len(files) > 30:
        score += 16
        reasons.append("multi-area change")
    elif len(files) > 10:
        score += 8

    deleted = sum(1 for x in changes if x.get("status") == "D")
    renamed = sum(1 for x in changes if x.get("status") == "R")
    if deleted:
        score += min(15, deleted * 3)
        reasons.append(f"{deleted} deleted files")
    if renamed > 5:
        score += 6
        reasons.append("multiple renames")

    joined = "\n".join(files).lower()
    content_joined = "\n".join(contents.values())[:900_000]
    for pattern, weight, reason in CRITICAL_PATH_RULES:
        if re.search(pattern, joined, re.IGNORECASE) or re.search(pattern, content_joined, re.IGNORECASE):
            score += weight
            reasons.append(reason)

    transitive = int(dependency_impact.get("transitive_impacted_count", 0))
    if transitive > 80:
        score += 20
        reasons.append("large dependency blast radius")
    elif transitive > 25:
        score += 12
        reasons.append("meaningful dependency blast radius")
    elif transitive > 5:
        score += 5

    score += historical_score
    return min(100, score), reasons

def confidence_for(
    trusted_change_set: bool,
    files: list[str],
    contents: dict[str, str],
    dependency_impact: dict[str, Any],
    too_large: bool,
) -> tuple[float, list[str]]:
    confidence = 1.0
    reasons: list[str] = []
    if not trusted_change_set:
        return 0.0, ["untrusted diff baseline"]
    if too_large:
        return 0.3, ["diff exceeds adaptive-analysis safety limits"]
    source_files = [
        f for f in files
        if Path(f.lower()).suffix in {".dart", ".kt", ".java", ".xml", ".gradle", ".kts"}
    ]
    if source_files and not contents:
        confidence -= 0.22
        reasons.append("changed source content could not be inspected")
    if source_files and int(dependency_impact.get("tracked_source_files", 0)) == 0:
        confidence -= 0.18
        reasons.append("dependency graph unavailable")
    generated = [f for f in files if any(marker in f.lower() for marker in GENERATED_MARKERS)]
    if generated and len(generated) >= max(2, len(files) // 2):
        confidence -= 0.15
        reasons.append("generated-code-heavy change")
    return max(0.0, min(1.0, confidence)), reasons

def classify(
    files: list[str],
    mode: str,
    baseline_sha: str = "",
    *,
    change_set: dict[str, Any] | None = None,
    contents: dict[str, str] | None = None,
    dependency_impact: dict[str, Any] | None = None,
    history_score: int = 0,
    history_reasons: list[str] | None = None,
    resolved_sha: str = "",
    shadow_rate: int = 10,
    history_risk_bias: int = 0,
) -> dict[str, Any]:
    mode = mode.lower().strip()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")

    selected = {lab: True for lab in LABS}
    reasons: dict[str, list[str]] = {lab: [] for lab in LABS}
    change_set = change_set or {
        "trusted": bool(files),
        "reason": "",
        "changes": [{"status": "M", "path": x, "added": 0, "deleted": 0} for x in files],
        "total_added": 0,
        "total_deleted": 0,
        "too_large": False,
    }
    contents = contents or {}
    dependency_impact = dependency_impact or {
        "tracked_source_files": 0,
        "direct_changed": len(files),
        "impacted_files": files,
        "transitive_impacted_count": 0,
    }
    history_reasons = history_reasons or []

    if mode == "certification":
        for lab in LABS:
            reasons[lab].append("CERTIFICATION mode")
        return {
            "schema_version": 2,
            "planner_version": "0.9.0",
            "mode": "certification",
            "requested_mode": mode,
            "lane": "certification",
            "baseline_sha": baseline_sha,
            "changed_files": files,
            "change_summary": change_set,
            "dependency_impact": dependency_impact,
            "risk": {"score": 100, "level": "critical", "reasons": ["production certification"]},
            "confidence": {"score": 1.0, "reasons": []},
            "selected_labs": selected,
            "reasons": reasons,
            "fallback_full": False,
            "runtime_required": True,
            "build_required": True,
            "static_required": True,
            "shadow_full": False,
            "targets": {"flutter": choose_flutter_targets(files), "android": choose_android_targets(files)},
        }

    if mode == "full":
        for lab in LABS:
            reasons[lab].append("FULL mode")
        return {
            "schema_version": 2,
            "planner_version": "0.9.0",
            "mode": "full",
            "requested_mode": mode,
            "lane": "full_runtime",
            "baseline_sha": baseline_sha,
            "changed_files": files,
            "change_summary": change_set,
            "dependency_impact": dependency_impact,
            "risk": {"score": 100, "level": "critical", "reasons": ["explicit FULL mode"]},
            "confidence": {"score": 1.0, "reasons": []},
            "selected_labs": selected,
            "reasons": reasons,
            "fallback_full": False,
            "runtime_required": True,
            "build_required": True,
            "static_required": True,
            "shadow_full": False,
            "targets": {"flutter": choose_flutter_targets(files), "android": choose_android_targets(files)},
        }

    trusted = bool(change_set.get("trusted", False))
    too_large = bool(change_set.get("too_large", False))
    confidence, confidence_reasons = confidence_for(
        trusted, files, contents, dependency_impact, too_large
    )
    risk_score, risk_reasons = score_risk(
        files,
        list(change_set.get("changes", [])),
        contents,
        dependency_impact,
        history_score,
    )
    risk_reasons.extend(history_reasons)

    if not trusted or too_large or not files:
        risk_score = max(risk_score, 90)
        confidence = min(confidence, 0.3)
        risk_reasons.append(
            str(change_set.get("reason") or "unsafe or oversized diff; safe FULL fallback")
        )
        for lab in LABS:
            reasons[lab].append("safe FULL fallback")
        lane = "full_runtime"
        effective_mode = "full"
        fallback_full = True
    elif is_docs_only(files):
        selected = {lab: False for lab in LABS}
        lane = "no_runtime"
        effective_mode = "fast"
        fallback_full = False
    elif is_static_only(files):
        selected = {lab: False for lab in LABS}
        lane = "static_only"
        effective_mode = "fast"
        fallback_full = False
    else:
        selected = {lab: False for lab in LABS}
        impacted_files = list(dependency_impact.get("impacted_files", files))
        classification_surface = sorted(set(files + impacted_files[:250]))
        for path in classification_surface:
            lower = path.lower()
            suffix = Path(lower).suffix
            text = contents.get(path, "")
            for lab, patterns in RULES.items():
                if any(re.search(pattern, lower, flags=re.IGNORECASE) for pattern in patterns):
                    selected[lab] = True
                    if path in files and path not in reasons[lab]:
                        reasons[lab].append(path)
            if text:
                for lab, patterns in CONTENT_RULES.items():
                    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
                        selected[lab] = True
                        marker = f"{path} (content signal)"
                        if marker not in reasons[lab]:
                            reasons[lab].append(marker)
            if suffix in SOURCE_SUFFIXES and (
                "/src/" in f"/{lower}" or lower.startswith(("lib/", "app/"))
            ):
                selected["performance"] = True
                if path in files and path not in reasons["performance"]:
                    reasons["performance"].append(path)

        if any(re.search(r"migration|schema|database|room|drift|sqlite", p, re.I) for p in files):
            for lab in ("persistence", "storage", "upgrade"):
                selected[lab] = True
                reasons[lab].append("database/schema risk escalation")
        if any(re.search(r"service|worker|alarm|receiver|notification", p, re.I) for p in files):
            for lab in ("system", "background", "resource_pressure"):
                selected[lab] = True
                reasons[lab].append("background/system risk escalation")

        if not any(selected.values()):
            selected["configuration"] = True
            selected["performance"] = True
            reasons["configuration"].append("generic runtime-code change")
            reasons["performance"].append("generic runtime-code change")

        if risk_score >= 75 or confidence < 0.65:
            lane = "full_runtime"
            effective_mode = "full"
            fallback_full = True
            for lab in LABS:
                selected[lab] = True
                reasons[lab].append(
                    "risk/confidence escalation to FULL "
                    f"(risk={risk_score}, confidence={confidence:.2f})"
                )
        else:
            lane = "fast_runtime"
            effective_mode = "fast"
            fallback_full = False

    if risk_score >= 85:
        risk_level = "critical"
    elif risk_score >= 65:
        risk_level = "high"
    elif risk_score >= 35:
        risk_level = "medium"
    else:
        risk_level = "low"

    stable_sha = resolved_sha.strip().lower()
    shadow_full = False
    if lane == "fast_runtime" and 0 < shadow_rate <= 100 and valid_sha(stable_sha):
        bucket = int(hashlib.sha256(stable_sha.encode()).hexdigest()[:8], 16) % 100
        shadow_full = bucket < shadow_rate

    return {
        "schema_version": 2,
        "planner_version": "0.9.0",
        "mode": effective_mode,
        "requested_mode": "fast",
        "lane": lane,
        "baseline_sha": baseline_sha,
        "changed_files": files,
        "change_summary": change_set,
        "dependency_impact": dependency_impact,
        "risk": {"score": risk_score, "level": risk_level, "reasons": sorted(set(risk_reasons))},
        "confidence": {"score": round(confidence, 3), "reasons": confidence_reasons},
        "selected_labs": selected,
        "reasons": reasons,
        "fallback_full": fallback_full,
        "runtime_required": lane in {"fast_runtime", "full_runtime"},
        "build_required": lane in {"fast_runtime", "full_runtime"},
        "static_required": lane != "no_runtime",
        "shadow_full": shadow_full,
        "targets": {"flutter": choose_flutter_targets(files), "android": choose_android_targets(files)},
    }

def plan_repository(
    repo_root: Path,
    mode: str,
    baseline_sha: str = "",
    *,
    history_file: str = "",
    repository: str = "",
    resolved_sha: str = "",
    shadow_rate: int = 10,
) -> dict[str, Any]:
    if mode in {"full", "certification"}:
        return classify(
            [],
            mode,
            baseline_sha,
            change_set={"trusted": True, "reason": "", "changes": [], "too_large": False},
            resolved_sha=resolved_sha,
            shadow_rate=shadow_rate,
        )

    change_set = git_change_set(repo_root, baseline_sha)
    files = list(change_set.get("files", []))
    contents = read_changed_content(repo_root, files)
    dependency_impact = build_dependency_impact(repo_root, files) if change_set.get("trusted") else {
        "tracked_source_files": 0,
        "direct_changed": len(files),
        "impacted_files": files,
        "transitive_impacted_count": 0,
    }
    history_score, history_reasons = historical_risk(history_file, repository, files)
    if history_risk_bias:
        history_score += max(0, min(25, int(history_risk_bias)))
        history_reasons.append(f"watcher historical risk bias +{max(0, min(25, int(history_risk_bias)))}")
    return classify(
        files,
        mode,
        baseline_sha,
        change_set=change_set,
        contents=contents,
        dependency_impact=dependency_impact,
        history_score=history_score,
        history_reasons=history_reasons,
        resolved_sha=resolved_sha,
        shadow_rate=shadow_rate,
    )

def validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
        raise ValueError("invalid analysis plan schema")
    mode = str(payload.get("mode", "")).lower()
    baseline_sha = str(payload.get("baseline_sha", "")).strip().lower()
    if baseline_sha and not valid_sha(baseline_sha):
        raise ValueError("invalid analysis plan baseline SHA")
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("invalid analysis plan mode")
    selected = payload.get("selected_labs")
    if not isinstance(selected, dict) or set(selected) != set(LABS):
        raise ValueError("analysis plan selected_labs mismatch")
    if not all(isinstance(selected[k], bool) for k in LABS):
        raise ValueError("analysis plan lab values must be booleans")
    files = payload.get("changed_files", [])
    if not isinstance(files, list) or len(files) > 5000:
        raise ValueError("invalid changed_files in analysis plan")
    for path in files:
        if not isinstance(path, str) or len(path) > 500 or "\n" in path or "\r" in path:
            raise ValueError("invalid changed file path")
    if payload.get("schema_version") == 2:
        lane = str(payload.get("lane", ""))
        if lane not in LANES:
            raise ValueError("invalid adaptive analysis lane")
        risk = payload.get("risk", {})
        confidence = payload.get("confidence", {})
        if not isinstance(risk, dict) or not (0 <= int(risk.get("score", -1)) <= 100):
            raise ValueError("invalid adaptive risk score")
        score = float(confidence.get("score", -1))
        if not isinstance(confidence, dict) or not (0.0 <= score <= 1.0):
            raise ValueError("invalid adaptive confidence score")
    return payload

def emit_github_output(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"effective_mode={payload['mode']}\n")
        handle.write(f"lane={payload.get('lane', 'full_runtime')}\n")
        handle.write(f"runtime_required={'true' if payload.get('runtime_required', True) else 'false'}\n")
        handle.write(f"build_required={'true' if payload.get('build_required', True) else 'false'}\n")
        handle.write(f"static_required={'true' if payload.get('static_required', True) else 'false'}\n")
        handle.write(f"fallback_full={'true' if payload.get('fallback_full', False) else 'false'}\n")
        handle.write(f"shadow_full={'true' if payload.get('shadow_full', False) else 'false'}\n")
        handle.write(f"risk_score={int(payload.get('risk', {}).get('score', 100))}\n")
        handle.write(f"risk_level={payload.get('risk', {}).get('level', 'critical')}\n")
        handle.write(f"confidence={float(payload.get('confidence', {}).get('score', 0.0)):.3f}\n")
        flutter = payload.get("targets", {}).get("flutter", {})
        android = payload.get("targets", {}).get("android", {})
        handle.write("flutter_analyze_targets=" + json.dumps(flutter.get("analyze", []), separators=(",", ":")) + "\n")
        handle.write("flutter_test_targets=" + json.dumps(flutter.get("tests", []), separators=(",", ":")) + "\n")
        handle.write("android_modules=" + json.dumps(android.get("modules", []), separators=(",", ":")) + "\n")

def regression_corpus() -> None:
    cases = [
        (["README.md"], "no_runtime", ()),
        (["test/home_test.dart"], "static_only", ()),
        (["app/src/main/AndroidManifest.xml"], "fast_runtime", ("system", "upgrade")),
        (["lib/data/api_client.dart"], "fast_runtime", ("network", "performance")),
        (["app/src/main/java/x/SyncWorker.kt"], "fast_runtime", ("background", "resource_pressure")),
        (["app/src/main/java/x/AppDatabase.kt"], "fast_runtime", ("persistence", "storage", "upgrade")),
        (["lib/screens/home_page.dart"], "fast_runtime", ("configuration", "performance")),
        (["lib/services/NotificationService.dart"], "fast_runtime", ("system", "background")),
        (["lib/cache/image_cache.dart"], "fast_runtime", ("performance", "resource_pressure", "storage")),
    ]
    for files, expected_lane, expected_labs in cases:
        change_set = {
            "trusted": True,
            "changes": [{"status": "M", "path": path, "added": 8, "deleted": 2} for path in files],
            "too_large": False,
        }
        payload = classify(files, "fast", "a" * 40, change_set=change_set)
        assert payload["lane"] == expected_lane, (files, payload["lane"], expected_lane)
        for lab in expected_labs:
            assert payload["selected_labs"][lab], (files, lab, payload["selected_labs"])

    huge = classify(
        [f"lib/generated/file_{i}.dart" for i in range(501)],
        "fast",
        "a" * 40,
        change_set={
            "trusted": True,
            "changes": [{"status": "M", "path": f"lib/generated/file_{i}.dart", "added": 1, "deleted": 1} for i in range(501)],
            "too_large": True,
        },
    )
    assert huge["lane"] == "full_runtime" and huge["fallback_full"]


def self_test() -> None:
    regression_corpus()
    docs = classify(
        ["README.md"],
        "fast",
        "a" * 40,
        change_set={"trusted": True, "changes": [{"status": "M", "path": "README.md"}], "too_large": False},
    )
    assert docs["lane"] == "no_runtime"
    assert not any(docs["selected_labs"].values())

    db = classify(
        ["app/src/main/java/x/AppDatabase.kt"],
        "fast",
        "a" * 40,
        change_set={
            "trusted": True,
            "changes": [{"status": "M", "path": "app/src/main/java/x/AppDatabase.kt", "added": 10, "deleted": 2}],
            "too_large": False,
        },
        contents={"app/src/main/java/x/AppDatabase.kt": "@Database class AppDatabase"},
    )
    assert db["selected_labs"]["storage"]
    assert db["selected_labs"]["persistence"]
    assert db["selected_labs"]["upgrade"]

    tests = classify(
        ["test/home_test.dart"],
        "fast",
        "a" * 40,
        change_set={"trusted": True, "changes": [{"status": "M", "path": "test/home_test.dart"}], "too_large": False},
    )
    assert tests["lane"] == "static_only"

    unsafe = classify(
        [],
        "fast",
        "f" * 40,
        change_set={"trusted": False, "reason": "missing ancestor", "changes": [], "too_large": False},
    )
    assert unsafe["mode"] == "full" and unsafe["fallback_full"]
    assert unsafe["lane"] == "full_runtime"

    cert = classify([], "certification", "a" * 40)
    assert cert["mode"] == "certification"
    assert all(cert["selected_labs"].values())

    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "applab@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "AppLab Self Test"], check=True)

        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
        baseline = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()

        db_file = root / "app" / "src" / "main" / "java" / "x" / "AppDatabase.kt"
        db_file.parent.mkdir(parents=True)
        db_file.write_text("@Database class AppDatabase\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "database change"], check=True)

        (root / "README.md").write_text("docs-only final commit\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "docs change"], check=True)

        resolved = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        plan = plan_repository(root, "fast", baseline, resolved_sha=resolved)
        assert "README.md" in plan["changed_files"]
        assert "app/src/main/java/x/AppDatabase.kt" in plan["changed_files"]
        assert plan["selected_labs"]["persistence"]
        assert plan["selected_labs"]["storage"]
        assert plan["selected_labs"]["upgrade"]

        other = root / "orphan"
        other.mkdir()
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        subprocess.run(["git", "-C", str(other), "config", "user.email", "a@b.test"], check=True)
        subprocess.run(["git", "-C", str(other), "config", "user.name", "Other"], check=True)
        (other / "x.txt").write_text("x")
        subprocess.run(["git", "-C", str(other), "add", "."], check=True)
        subprocess.run(["git", "-C", str(other), "commit", "-qm", "x"], check=True)
        orphan_sha = subprocess.check_output(
            ["git", "-C", str(other), "rev-parse", "HEAD"], text=True
        ).strip()
        fallback = plan_repository(root, "fast", orphan_sha)
        assert fallback["lane"] == "full_runtime"
        assert fallback["fallback_full"]

    validate_plan(db)
    validate_plan(cert)
    print("AppLab Adaptive Impact Planner self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode", choices=("fast", "full", "certification"), default="full")
    parser.add_argument("--baseline-sha", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--history-file", default="")
    parser.add_argument("--shadow-rate", type=int, default=10)
    parser.add_argument("--history-risk-bias", type=int, default=0)
    parser.add_argument("--output")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.output:
        raise SystemExit("--repo-root and --output are required")
    if not (0 <= args.shadow_rate <= 100):
        raise SystemExit("--shadow-rate must be between 0 and 100")
    started = time.perf_counter()
    payload = plan_repository(
        Path(args.repo_root).resolve(),
        args.mode,
        args.baseline_sha,
        history_file=args.history_file,
        repository=args.repository,
        resolved_sha=args.resolved_sha,
        shadow_rate=args.shadow_rate,
        history_risk_bias=args.history_risk_bias,
    )
    payload["timing"] = {
        "planner_ms": round((time.perf_counter() - started) * 1000, 2)
    }
    validate_plan(payload)
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    emit_github_output(args.github_output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
