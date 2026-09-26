#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

APPLAB_VERSION = "0.9.0"
SCHEMA_VERSION = 2
MAX_CHANGED_FILES = 500
MAX_DIFF_BYTES = 2_000_000
MAX_GRAPH_FILES = 6000
MAX_SOURCE_BYTES = 768_000

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
    "NO_RUNTIME_CHANGE",
    "STATIC_ONLY",
    "FAST_RUNTIME",
    "FULL_RUNTIME",
    "CERTIFICATION",
)

SOURCE_SUFFIXES = {
    ".kt", ".java", ".dart", ".xml", ".gradle", ".kts", ".toml",
    ".json", ".yaml", ".yml", ".properties",
}
RUNTIME_SUFFIXES = SOURCE_SUFFIXES | {
    ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ttf", ".otf", ".arb",
}
DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".adoc"}

RULES: dict[str, tuple[str, ...]] = {
    "system": (
        r"androidmanifest\.xml$", r"permissions?", r"notification", r"deeplink",
        r"intent", r"biometric", r"camera", r"location", r"bluetooth",
        r"foreground.?service", r"appop", r"broadcastreceiver",
    ),
    "performance": (
        r"(^|/)(lib|src|app)/", r"build\.gradle", r"pubspec\.yaml$",
        r"gradle\.properties$", r"render", r"image", r"list", r"animation",
        r"bitmap", r"compose", r"widget",
    ),
    "network": (
        r"network", r"http", r"api", r"retrofit", r"dio", r"ktor", r"websocket",
        r"sync", r"remote", r"repository", r"connectivity", r"firebase",
        r"supabase", r"graphql",
    ),
    "persistence": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref",
        r"datastore", r"storage", r"cache", r"sqlite", r"repository", r"model",
        r"drift", r"realm", r"hive",
    ),
    "configuration": (
        r"activity", r"fragment", r"compose", r"widget", r"screen", r"page",
        r"view", r"layout", r"theme", r"orientation", r"resource", r"res/",
        r"lib/.*\.dart$", r"navigation", r"router",
    ),
    "resource_pressure": (
        r"service", r"worker", r"background", r"cache", r"image", r"bitmap",
        r"camera", r"media", r"memory", r"process", r"stream",
    ),
    "background": (
        r"service", r"worker", r"workmanager", r"background", r"alarm", r"job",
        r"notification", r"battery", r"doze", r"sync", r"scheduler",
    ),
    "storage": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref",
        r"datastore", r"storage", r"file", r"sqlite", r"backup", r"cache",
        r"drift", r"realm", r"hive",
    ),
    "upgrade": (
        r"database", r"migration", r"schema", r"androidmanifest\.xml$",
        r"build\.gradle", r"pubspec\.yaml$", r"version", r"applicationid",
        r"minsdk", r"targetsdk", r"compileSdk", r"gradle-wrapper",
    ),
}

CONTENT_SIGNALS: dict[str, tuple[str, ...]] = {
    "system": (
        "uses-permission", "requestpermissions", "notificationchannel",
        "foregroundservice", "pendingintent", "biometric", "camera",
    ),
    "network": (
        "http://", "https://", "retrofit", "dio(", "ktor", "websocket",
        "firebase", "supabase", "graphql", "connectivity",
    ),
    "persistence": (
        "@database", "@entity", "@dao", "migration", "sqlite", "datastore",
        "sharedpreferences", "driftdatabase", "realm", "hive",
    ),
    "background": (
        "workmanager", "worker", "foregroundservice", "alarmmanager",
        "jobscheduler", "doze", "wakelock", "background",
    ),
    "storage": (
        "file(", "filesdir", "cachedir", "sqlite", "database", "backup",
        "sharedpreferences", "datastore",
    ),
    "upgrade": (
        "schemaversion", "versioncode", "versionname", "minsdk", "targetsdk",
        "applicationid", "migration",
    ),
    "performance": (
        "listview", "lazycolumn", "lazyrow", "image(", "bitmap", "animation",
        "repaintboundary", "remember", "streambuilder",
    ),
}

HIGH_RISK_PATTERNS = (
    r"androidmanifest\.xml$",
    r"pubspec\.yaml$",
    r"gradle\.properties$",
    r"settings\.gradle",
    r"build\.gradle",
    r"gradle-wrapper",
    r"migration",
    r"schema",
    r"database",
    r"applicationid",
    r"versioncode",
    r"minsdk",
    r"targetsdk",
    r"proguard",
    r"r8",
    r"signing",
    r"keystore",
    r"service",
    r"worker",
    r"alarm",
)

STATIC_ONLY_PATTERNS = (
    r"(^|/)test/",
    r"(^|/)tests/",
    r"(^|/)androidtest/",
    r"(^|/)integration_test/",
    r"analysis_options\.yaml$",
    r"lint\.xml$",
    r"detekt",
    r"ktlint",
)

DOC_PATH_PATTERNS = (
    r"(^|/)docs?/",
    r"(^|/)readme(?:\.|$)",
    r"(^|/)changelog(?:\.|$)",
    r"(^|/)license(?:\.|$)",
    r"(^|/)notice(?:\.|$)",
    r"\.md$",
    r"\.mdx$",
    r"\.rst$",
    r"\.adoc$",
)

CI_ONLY_PATTERNS = (
    r"^\.github/",
    r"^\.gitlab/",
    r"^\.circleci/",
    r"^scripts/ci/",
)


def _run(command: list[str], *, timeout: int = 30, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )


def _git(repo_root: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(repo_root), *args], timeout=timeout)


def _valid_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value.strip().lower()))


def _head_sha(repo_root: Path) -> str:
    result = _git(repo_root, "rev-parse", "HEAD")
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and _valid_sha(value) else ""


def _commit_exists(repo_root: Path, sha: str) -> bool:
    if not _valid_sha(sha):
        return False
    result = _git(repo_root, "cat-file", "-e", f"{sha}^{{commit}}", timeout=15)
    return result.returncode == 0


def _is_ancestor(repo_root: Path, baseline: str, head: str) -> bool:
    if not (_valid_sha(baseline) and _valid_sha(head)):
        return False
    result = _git(repo_root, "merge-base", "--is-ancestor", baseline, head, timeout=15)
    return result.returncode == 0


def _parse_name_status(raw: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status_raw = parts[0].strip()
        status = status_raw[:1]
        if status in {"R", "C"} and len(parts) >= 3:
            rows.append({
                "status": status,
                "similarity": status_raw[1:] or "",
                "previous_path": parts[1].replace("\\", "/"),
                "path": parts[2].replace("\\", "/"),
            })
        elif len(parts) >= 2:
            rows.append({
                "status": status,
                "similarity": "",
                "previous_path": "",
                "path": parts[1].replace("\\", "/"),
            })
    return rows


def _parse_numstat(raw: str) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw, path = parts[0], parts[1], parts[-1].replace("\\", "/")
        try:
            added = int(added_raw)
        except ValueError:
            added = 0
        try:
            deleted = int(deleted_raw)
        except ValueError:
            deleted = 0
        stats[path] = (added, deleted)
    return stats


def _diff_content_by_file(raw: str) -> dict[str, str]:
    current = ""
    chunks: dict[str, list[str]] = defaultdict(list)
    for line in raw.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            continue
        if line.startswith("+++ /dev/null"):
            continue
        if not current:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            chunks[current].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            chunks[current].append(line[1:])
    return {path: "\n".join(lines) for path, lines in chunks.items()}


def git_change_evidence(
    repo_root: Path,
    baseline_sha: str = "",
    *,
    baseline_trusted: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    baseline = baseline_sha.strip().lower()
    head = _head_sha(repo_root)
    evidence: dict[str, Any] = {
        "baseline_sha": baseline,
        "head_sha": head,
        "baseline_trusted": bool(baseline_trusted),
        "baseline_exists": False,
        "baseline_is_ancestor": False,
        "trusted_range": False,
        "range_error": "",
        "large_change": False,
        "diff_truncated": False,
        "changes": [],
        "changed_files": [],
        "total_files": 0,
        "total_additions": 0,
        "total_deletions": 0,
        "total_churn": 0,
    }

    if not _valid_sha(baseline):
        evidence["range_error"] = "missing or invalid baseline SHA"
        return evidence
    if not baseline_trusted:
        evidence["range_error"] = "baseline identity is not trusted for this watcher target"
        return evidence
    if not head:
        evidence["range_error"] = "unable to resolve HEAD"
        return evidence

    evidence["baseline_exists"] = _commit_exists(repo_root, baseline)
    if not evidence["baseline_exists"]:
        evidence["range_error"] = "baseline commit is unavailable"
        return evidence

    evidence["baseline_is_ancestor"] = _is_ancestor(repo_root, baseline, head)
    if not evidence["baseline_is_ancestor"]:
        evidence["range_error"] = "baseline is not an ancestor of current HEAD"
        return evidence

    name_status = _git(
        repo_root, "diff", "--name-status", "--find-renames", f"{baseline}..{head}",
        timeout=45,
    )
    numstat = _git(
        repo_root, "diff", "--numstat", "--find-renames", f"{baseline}..{head}",
        timeout=45,
    )
    if name_status.returncode != 0 or numstat.returncode != 0:
        evidence["range_error"] = "git diff failed"
        return evidence

    rows = _parse_name_status(name_status.stdout)
    stats = _parse_numstat(numstat.stdout)
    evidence["total_files"] = len(rows)
    if len(rows) > MAX_CHANGED_FILES:
        evidence["large_change"] = True
        evidence["range_error"] = f"changed-file count exceeds safe FAST limit ({MAX_CHANGED_FILES})"
        evidence["changed_files"] = [row["path"] for row in rows[:MAX_CHANGED_FILES]]
        evidence["changes"] = rows[:MAX_CHANGED_FILES]
        return evidence

    diff = _git(
        repo_root, "diff", "--unified=0", "--no-ext-diff", "--find-renames",
        f"{baseline}..{head}", timeout=60,
    )
    diff_text = diff.stdout if diff.returncode == 0 else ""
    if len(diff_text.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
        evidence["diff_truncated"] = True
        diff_text = diff_text.encode("utf-8", errors="ignore")[:MAX_DIFF_BYTES].decode(
            "utf-8", errors="ignore"
        )
    content = _diff_content_by_file(diff_text)

    additions = deletions = 0
    enriched: list[dict[str, Any]] = []
    for row in rows:
        path = str(row["path"])
        added, deleted = stats.get(path, (0, 0))
        additions += added
        deletions += deleted
        body = content.get(path, "")
        signals = sorted(
            {
                lab
                for lab, needles in CONTENT_SIGNALS.items()
                if any(needle.lower() in body.lower() for needle in needles)
            }
        )
        enriched.append({
            **row,
            "additions": added,
            "deletions": deleted,
            "churn": added + deleted,
            "content_signals": signals,
        })

    evidence.update({
        "trusted_range": True,
        "changes": enriched,
        "changed_files": [row["path"] for row in enriched],
        "total_additions": additions,
        "total_deletions": deletions,
        "total_churn": additions + deletions,
    })
    if evidence["diff_truncated"]:
        evidence["large_change"] = True
        evidence["range_error"] = "diff exceeds safe FAST byte limit"
    return evidence


def git_changed_files(repo_root: Path, baseline_sha: str = "") -> list[str]:
    """Compatibility helper. A caller without trusted identity gets no FAST range."""
    return git_change_evidence(
        repo_root, baseline_sha, baseline_trusted=True
    )["changed_files"]


def tracked_files(repo_root: Path) -> list[Path]:
    result = _git(repo_root, "ls-files", "-z", timeout=30)
    if result.returncode == 0 and result.stdout:
        files: list[Path] = []
        for raw in result.stdout.split("\0"):
            if not raw:
                continue
            path = repo_root / raw
            if path.is_file():
                files.append(path)
        return files

    ignored = {".git", ".dart_tool", ".gradle", ".idea", "build", "node_modules"}
    files = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        files.append(path)
    return files


def _read_source(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _dart_package_name(repo_root: Path) -> str:
    for pubspec in tracked_files(repo_root):
        if pubspec.name != "pubspec.yaml":
            continue
        match = re.search(r"^name:\s*([A-Za-z0-9_]+)\s*$", _read_source(pubspec), re.MULTILINE)
        if match:
            return match.group(1)
    return ""


def build_dependency_graph(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    candidates = [
        p for p in tracked_files(repo_root)
        if p.suffix.lower() in {".dart", ".kt", ".java"} and p.stat().st_size <= MAX_SOURCE_BYTES
    ]
    if len(candidates) > MAX_GRAPH_FILES:
        return {
            "available": False,
            "reason": f"source graph exceeds {MAX_GRAPH_FILES} files",
            "nodes": 0,
            "edges": 0,
            "reverse": {},
        }

    rels = {p.relative_to(repo_root).as_posix(): p for p in candidates}
    dart_package = _dart_package_name(repo_root)
    package_to_files: dict[str, list[str]] = defaultdict(list)
    java_fqcn: dict[str, str] = {}

    for rel, path in rels.items():
        if path.suffix.lower() not in {".kt", ".java"}:
            continue
        text = _read_source(path)
        match = re.search(r"^\s*package\s+([A-Za-z0-9_.]+)", text, re.MULTILINE)
        if match:
            package = match.group(1)
            package_to_files[package].append(rel)
            java_fqcn[f"{package}.{path.stem}"] = rel

    reverse: dict[str, set[str]] = defaultdict(set)
    edge_count = 0
    for rel, path in rels.items():
        text = _read_source(path)
        deps: set[str] = set()
        if path.suffix.lower() == ".dart":
            for imported in re.findall(r"\b(?:import|export|part)\s+['\"]([^'\"]+)['\"]", text):
                if imported.startswith("dart:") or imported.startswith("package:flutter/"):
                    continue
                resolved = ""
                if imported.startswith("package:") and dart_package:
                    prefix = f"package:{dart_package}/"
                    if imported.startswith(prefix):
                        resolved = f"lib/{imported[len(prefix):]}"
                elif not imported.startswith("package:"):
                    try:
                        resolved = (path.parent / imported).resolve().relative_to(repo_root).as_posix()
                    except ValueError:
                        resolved = ""
                if resolved in rels:
                    deps.add(resolved)
        else:
            for imported in re.findall(r"^\s*import\s+([A-Za-z0-9_.*]+)", text, re.MULTILINE):
                if imported.endswith(".*"):
                    package = imported[:-2]
                    deps.update(package_to_files.get(package, []))
                elif imported in java_fqcn:
                    deps.add(java_fqcn[imported])

        for dep in deps:
            reverse[dep].add(rel)
            edge_count += 1

    return {
        "available": True,
        "reason": "",
        "nodes": len(rels),
        "edges": edge_count,
        "reverse": {key: sorted(value) for key, value in reverse.items()},
    }


def impacted_files(changed: list[str], graph: dict[str, Any], max_depth: int = 2) -> list[str]:
    if not graph.get("available"):
        return sorted(set(changed))
    reverse = graph.get("reverse", {})
    visited = set(changed)
    queue: deque[tuple[str, int]] = deque((path, 0) for path in changed)
    while queue:
        path, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for dependent in reverse.get(path, []):
            if dependent in visited:
                continue
            visited.add(dependent)
            queue.append((dependent, depth + 1))
    return sorted(visited)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, path, re.IGNORECASE) for pattern in patterns)


def _doc_only(files: list[str]) -> bool:
    return bool(files) and all(_matches(path.lower(), DOC_PATH_PATTERNS) for path in files)


def _static_only(files: list[str]) -> bool:
    if not files:
        return False
    saw_static = False
    for path in files:
        lower = path.lower()
        if _matches(lower, DOC_PATH_PATTERNS):
            continue
        if _matches(lower, CI_ONLY_PATTERNS) or _matches(lower, STATIC_ONLY_PATTERNS):
            saw_static = True
            continue
        return False
    return saw_static


def _module_for(path: str) -> str:
    parts = path.split("/")
    if "src" in parts:
        idx = parts.index("src")
        return "/".join(parts[:idx]) or "."
    if len(parts) >= 3 and parts[0] == "lib" and parts[1] in {"features", "core"}:
        return "/".join(parts[:3])
    if parts and parts[0] == "lib":
        return "lib"
    return parts[0] if parts else "."


def _targeted_tests(repo_root: Path, changed: list[str], impacted: list[str]) -> list[str]:
    tracked = [p.relative_to(repo_root).as_posix() for p in tracked_files(repo_root)]
    tests = {
        path for path in tracked
        if (
            "/test/" in f"/{path.lower()}"
            or path.lower().startswith(("test/", "integration_test/"))
        ) and Path(path).suffix.lower() in {".dart", ".kt", ".java"}
    }
    selected: set[str] = {p for p in changed if p in tests}
    impacted_set = set(impacted)
    for test in tests:
        stem = Path(test).stem.lower().removesuffix("_test")
        if any(Path(source).stem.lower() in {stem, stem.removesuffix("test")} for source in impacted_set):
            selected.add(test)
    return sorted(selected)[:80]


def _analysis_targets(changed: list[str], impacted: list[str]) -> list[str]:
    candidates = [
        p for p in sorted(set(changed) | set(impacted))
        if Path(p).suffix.lower() in {".dart", ".kt", ".java"}
    ]
    modules = sorted({_module_for(path) for path in candidates})
    return modules[:40]


def _history_payload(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _risk_and_confidence(
    evidence: dict[str, Any],
    selected_labs: dict[str, bool],
    graph: dict[str, Any],
    impacted: list[str],
    history: dict[str, Any],
) -> tuple[int, str, float, list[str]]:
    reasons: list[str] = []
    if not evidence.get("trusted_range"):
        return 100, "CRITICAL", 0.0, [str(evidence.get("range_error") or "untrusted diff range")]

    files = evidence["changed_files"]
    churn = int(evidence.get("total_churn", 0))
    score = 5
    confidence = 0.96

    if _doc_only(files):
        return 0, "LOW", 0.99, ["documentation-only change"]
    if _static_only(files):
        score = 10
        reasons.append("static/test/CI-only change")

    for change in evidence.get("changes", []):
        path = str(change.get("path", "")).lower()
        status = str(change.get("status", "M"))
        if status in {"D", "R"}:
            score += 4
            reasons.append(f"{status} change: {change.get('path')}")
        if _matches(path, HIGH_RISK_PATTERNS):
            score += 12
            reasons.append(f"high-risk path: {change.get('path')}")
        signals = change.get("content_signals", [])
        if signals:
            score += min(10, len(signals) * 2)

    if churn >= 500:
        score += 8
        reasons.append(f"large code churn: {churn} lines")
    if churn >= 2000:
        score += 12
        confidence -= 0.08
    if len(files) >= 20:
        score += 8
        reasons.append(f"cross-file change: {len(files)} files")
    if len(files) >= 100:
        score += 18
        confidence -= 0.12
    if evidence.get("large_change"):
        score += 40
        confidence = min(confidence, 0.45)
        reasons.append(str(evidence.get("range_error") or "change exceeds FAST limits"))

    if graph.get("available"):
        if len(impacted) > len(files):
            score += min(12, max(0, len(impacted) - len(files)) // 3)
            reasons.append(f"dependency impact expands to {len(impacted)} files")
    else:
        confidence -= 0.12
        reasons.append(f"dependency graph unavailable: {graph.get('reason', 'unknown')}")
    if len(impacted) >= 50:
        score += 12
        confidence -= 0.08

    failure_counts = history.get("lab_failure_counts", {})
    if isinstance(failure_counts, dict):
        historical = sum(
            int(failure_counts.get(lab, 0) or 0)
            for lab, selected in selected_labs.items()
            if selected
        )
        if historical:
            score += min(15, historical * 3)
            confidence -= min(0.08, historical * 0.01)
            reasons.append(f"historical failures in affected labs: {historical}")

    recent_pipeline_failures = int(history.get("recent_pipeline_failures", 0) or 0)
    if recent_pipeline_failures:
        score += min(10, recent_pipeline_failures * 2)
        reasons.append(f"recent project failures: {recent_pipeline_failures}")

    unknown_runtime = [
        path for path in files
        if Path(path).suffix.lower() in RUNTIME_SUFFIXES
        and not any(
            re.search(pattern, path, re.IGNORECASE)
            for patterns in RULES.values()
            for pattern in patterns
        )
    ]
    if unknown_runtime:
        confidence -= min(0.15, len(unknown_runtime) * 0.02)
        reasons.append(f"{len(unknown_runtime)} runtime files have weak semantic classification")

    score = max(0, min(100, score))
    confidence = max(0.0, min(0.99, confidence))
    if score >= 85:
        level = "CRITICAL"
    elif score >= 65:
        level = "HIGH"
    elif score >= 35:
        level = "MEDIUM"
    else:
        level = "LOW"
    return score, level, round(confidence, 3), reasons


def _shadow_recommended(head_sha: str, history: dict[str, Any]) -> bool:
    if not _valid_sha(head_sha):
        return False
    divergence = int(history.get("shadow_false_negatives", 0) or 0)
    modulo = 5 if divergence else 10
    return int(hashlib.sha256(head_sha.encode()).hexdigest()[:8], 16) % modulo == 0


def _lab_selection(
    changes: list[dict[str, Any]],
    impacted: list[str],
    history: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, list[str]]]:
    selected = {lab: False for lab in LABS}
    reasons: dict[str, list[str]] = {lab: [] for lab in LABS}
    paths = sorted(set([str(row.get("path", "")) for row in changes] + impacted))

    for path in paths:
        lower = path.lower()
        for lab, patterns in RULES.items():
            if any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns):
                selected[lab] = True
                if path not in reasons[lab]:
                    reasons[lab].append(path)

    for row in changes:
        path = str(row.get("path", ""))
        for lab in row.get("content_signals", []):
            if lab in selected:
                selected[lab] = True
                marker = f"content:{path}"
                if marker not in reasons[lab]:
                    reasons[lab].append(marker)

    runtime_code = [
        path for path in paths
        if Path(path).suffix.lower() in SOURCE_SUFFIXES
        and not _matches(path.lower(), DOC_PATH_PATTERNS)
        and not _matches(path.lower(), STATIC_ONLY_PATTERNS)
    ]
    if runtime_code:
        selected["performance"] = True
        if not reasons["performance"]:
            reasons["performance"].append("generic runtime-code change")

    failure_counts = history.get("lab_failure_counts", {})
    if isinstance(failure_counts, dict) and runtime_code:
        unstable = sorted(
            (
                (int(failure_counts.get(lab, 0) or 0), lab)
                for lab in LABS
                if int(failure_counts.get(lab, 0) or 0) > 0
            ),
            reverse=True,
        )[:2]
        for count, lab in unstable:
            selected[lab] = True
            reasons[lab].append(f"historical-instability:{count}")

    if runtime_code and not any(selected.values()):
        selected["configuration"] = True
        selected["performance"] = True
        reasons["configuration"].append("generic runtime-code change")
        reasons["performance"].append("generic runtime-code change")

    return selected, reasons


def plan_from_repo(
    repo_root: Path,
    mode: str,
    baseline_sha: str = "",
    *,
    baseline_trusted: bool = False,
    history_risk: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = mode.lower().strip()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")

    repo_root = repo_root.resolve()
    history = _history_payload(history_risk)
    evidence = git_change_evidence(
        repo_root, baseline_sha, baseline_trusted=baseline_trusted
    )
    graph = build_dependency_graph(repo_root)
    changed = list(evidence.get("changed_files", []))
    impacted = impacted_files(changed, graph)

    selected, reasons = _lab_selection(evidence.get("changes", []), impacted, history)

    if mode in {"full", "certification"}:
        selected = {lab: True for lab in LABS}
        label = "FULL mode" if mode == "full" else "CERTIFICATION mode"
        reasons = {lab: [label] for lab in LABS}
        lane = "FULL_RUNTIME" if mode == "full" else "CERTIFICATION"
        score, level, confidence = (
            (70, "HIGH", 1.0) if mode == "full" else (100, "CRITICAL", 1.0)
        )
        risk_reasons = [label]
        effective_mode = mode
        fallback_full = False
    else:
        score, level, confidence, risk_reasons = _risk_and_confidence(
            evidence, selected, graph, impacted, history
        )
        fallback_full = False
        effective_mode = "fast"
        if not evidence.get("trusted_range"):
            lane = "FULL_RUNTIME"
            effective_mode = "full"
            fallback_full = True
            selected = {lab: True for lab in LABS}
            for lab in LABS:
                reasons[lab].append("untrusted FAST baseline; safe FULL fallback")
        elif evidence.get("large_change") or level in {"HIGH", "CRITICAL"} or confidence < 0.72:
            lane = "FULL_RUNTIME"
            effective_mode = "full"
            fallback_full = True
            selected = {lab: True for lab in LABS}
            for lab in LABS:
                reasons[lab].append("risk/confidence escalation to FULL")
        elif _doc_only(changed):
            lane = "NO_RUNTIME_CHANGE"
            selected = {lab: False for lab in LABS}
        elif _static_only(changed):
            lane = "STATIC_ONLY"
            selected = {lab: False for lab in LABS}
        else:
            lane = "FAST_RUNTIME"

    tests = _targeted_tests(repo_root, changed, impacted)
    analysis_targets = _analysis_targets(changed, impacted)
    modules = sorted({_module_for(path) for path in impacted if path})[:40]

    if lane == "NO_RUNTIME_CHANGE":
        static_strategy = "skip"
    elif lane == "STATIC_ONLY":
        static_strategy = "targeted" if tests or analysis_targets else "full"
    elif lane == "FAST_RUNTIME" and confidence >= 0.85 and score <= 45:
        static_strategy = "targeted"
    else:
        static_strategy = "full"

    shadow = (
        lane == "FAST_RUNTIME"
        and effective_mode == "fast"
        and _shadow_recommended(str(evidence.get("head_sha", "")), history)
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "planner_version": APPLAB_VERSION,
        "mode": effective_mode,
        "requested_mode": mode,
        "lane": lane,
        "baseline_sha": baseline_sha.strip().lower(),
        "baseline_trusted": bool(baseline_trusted),
        "head_sha": evidence.get("head_sha", ""),
        "changed_files": changed,
        "changes": evidence.get("changes", []),
        "change_summary": {
            key: evidence.get(key)
            for key in (
                "trusted_range", "baseline_exists", "baseline_is_ancestor",
                "range_error", "large_change", "diff_truncated", "total_files",
                "total_additions", "total_deletions", "total_churn",
            )
        },
        "dependency_graph": {
            "available": bool(graph.get("available")),
            "reason": graph.get("reason", ""),
            "nodes": int(graph.get("nodes", 0)),
            "edges": int(graph.get("edges", 0)),
            "impacted_files": impacted[:500],
            "impacted_count": len(impacted),
            "modules": modules,
        },
        "risk": {
            "score": score,
            "level": level,
            "confidence": confidence,
            "reasons": risk_reasons,
        },
        "selected_labs": selected,
        "reasons": reasons,
        "fallback_full": fallback_full,
        "runtime_required": lane in {"FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"},
        "static_required": lane != "NO_RUNTIME_CHANGE",
        "static_plan": {
            "strategy": static_strategy,
            "analysis_targets": analysis_targets,
            "test_targets": tests,
            "gradle_modules": modules,
            "combine_gradle_tasks": lane in {"STATIC_ONLY", "FAST_RUNTIME"} and static_strategy == "targeted",
        },
        "shadow_full_recommended": shadow,
        "history_risk": history,
    }
    validate_plan(payload)
    return payload


def classify(files: list[str], mode: str, baseline_sha: str = "") -> dict[str, Any]:
    """Compatibility path-level classifier used by older tests/callers."""
    mode = mode.lower().strip()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")
    selected = {lab: True for lab in LABS}
    reasons = {lab: [] for lab in LABS}
    if mode in {"full", "certification"}:
        label = "FULL mode" if mode == "full" else "CERTIFICATION mode"
        for lab in LABS:
            reasons[lab].append(label)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "planner_version": APPLAB_VERSION,
            "mode": mode,
            "requested_mode": mode,
            "lane": "FULL_RUNTIME" if mode == "full" else "CERTIFICATION",
            "baseline_sha": baseline_sha,
            "baseline_trusted": bool(baseline_sha),
            "head_sha": "",
            "changed_files": files,
            "changes": [{"path": p, "status": "M", "content_signals": []} for p in files],
            "change_summary": {"trusted_range": True, "total_files": len(files), "large_change": False},
            "dependency_graph": {"available": False, "reason": "path-only compatibility mode", "nodes": 0, "edges": 0, "impacted_files": files, "impacted_count": len(files), "modules": []},
            "risk": {"score": 70 if mode == "full" else 100, "level": "HIGH" if mode == "full" else "CRITICAL", "confidence": 1.0, "reasons": [label]},
            "selected_labs": selected,
            "reasons": reasons,
            "fallback_full": False,
            "runtime_required": True,
            "static_required": True,
            "static_plan": {"strategy": "full", "analysis_targets": [], "test_targets": [], "gradle_modules": [], "combine_gradle_tasks": False},
            "shadow_full_recommended": False,
            "history_risk": {},
        }
        return payload

    if not files:
        for lab in LABS:
            reasons[lab].append("no reliable changed-file set; safe FULL fallback")
        return classify([], "full", baseline_sha) | {
            "requested_mode": "fast",
            "fallback_full": True,
        }

    changes = [{"path": p, "status": "M", "content_signals": []} for p in files]
    selected, reasons = _lab_selection(changes, files, {})
    if _doc_only(files):
        lane = "NO_RUNTIME_CHANGE"
        selected = {lab: False for lab in LABS}
    elif _static_only(files):
        lane = "STATIC_ONLY"
        selected = {lab: False for lab in LABS}
    else:
        lane = "FAST_RUNTIME"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "planner_version": APPLAB_VERSION,
        "mode": "fast",
        "requested_mode": "fast",
        "lane": lane,
        "baseline_sha": baseline_sha,
        "baseline_trusted": bool(baseline_sha),
        "head_sha": "",
        "changed_files": files,
        "changes": changes,
        "change_summary": {"trusted_range": True, "total_files": len(files), "large_change": False},
        "dependency_graph": {"available": False, "reason": "path-only compatibility mode", "nodes": 0, "edges": 0, "impacted_files": files, "impacted_count": len(files), "modules": []},
        "risk": {"score": 20, "level": "LOW", "confidence": 0.8, "reasons": ["path-only compatibility mode"]},
        "selected_labs": selected,
        "reasons": reasons,
        "fallback_full": False,
        "runtime_required": lane == "FAST_RUNTIME",
        "static_required": lane != "NO_RUNTIME_CHANGE",
        "static_plan": {"strategy": "targeted", "analysis_targets": [], "test_targets": [], "gradle_modules": [], "combine_gradle_tasks": False},
        "shadow_full_recommended": False,
        "history_risk": {},
    }
    validate_plan(payload)
    return payload


def validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid analysis plan schema")
    mode = str(payload.get("mode", "")).lower()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("invalid analysis plan mode")
    if payload.get("lane") not in LANES:
        raise ValueError("invalid analysis lane")

    baseline_sha = str(payload.get("baseline_sha", "")).strip().lower()
    if baseline_sha and not _valid_sha(baseline_sha):
        raise ValueError("invalid analysis plan baseline SHA")

    selected = payload.get("selected_labs")
    if not isinstance(selected, dict) or set(selected) != set(LABS):
        raise ValueError("analysis plan selected_labs mismatch")
    if not all(isinstance(selected[k], bool) for k in LABS):
        raise ValueError("analysis plan lab values must be booleans")

    files = payload.get("changed_files", [])
    if not isinstance(files, list) or len(files) > MAX_CHANGED_FILES:
        raise ValueError("invalid changed_files in analysis plan")
    for path in files:
        if not isinstance(path, str) or len(path) > 500 or "\n" in path or "\r" in path:
            raise ValueError("invalid changed file path")

    risk = payload.get("risk")
    if not isinstance(risk, dict):
        raise ValueError("missing risk section")
    score = int(risk.get("score", -1))
    confidence = float(risk.get("confidence", -1))
    if not 0 <= score <= 100 or not 0 <= confidence <= 1:
        raise ValueError("invalid risk score/confidence")

    static = payload.get("static_plan")
    if not isinstance(static, dict) or static.get("strategy") not in {"skip", "targeted", "full"}:
        raise ValueError("invalid static plan")

    if payload.get("lane") == "NO_RUNTIME_CHANGE" and payload.get("runtime_required"):
        raise ValueError("NO_RUNTIME_CHANGE cannot require runtime")
    if payload.get("lane") in {"FULL_RUNTIME", "CERTIFICATION"} and not all(selected.values()):
        raise ValueError("FULL/CERTIFICATION lanes must select every specialist lab")
    return payload


def emit_github_output(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    static = payload["static_plan"]
    values = {
        "lane": payload["lane"],
        "effective_mode": payload["mode"],
        "runtime_required": str(bool(payload["runtime_required"])).lower(),
        "static_required": str(bool(payload["static_required"])).lower(),
        "static_strategy": static["strategy"],
        "analysis_targets_json": json.dumps(static["analysis_targets"], separators=(",", ":")),
        "test_targets_json": json.dumps(static["test_targets"], separators=(",", ":")),
        "gradle_modules_json": json.dumps(static["gradle_modules"], separators=(",", ":")),
        "combine_gradle_tasks": str(bool(static["combine_gradle_tasks"])).lower(),
        "shadow_full": str(bool(payload["shadow_full_recommended"])).lower(),
        "risk_score": str(payload["risk"]["score"]),
        "risk_level": str(payload["risk"]["level"]),
        "confidence": str(payload["risk"]["confidence"]),
    }
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def self_test() -> None:
    docs = classify(["README.md"], "fast", "a" * 40)
    assert docs["lane"] == "NO_RUNTIME_CHANGE"
    db = classify(["app/src/main/java/x/AppDatabase.kt"], "fast", "a" * 40)
    assert db["selected_labs"]["storage"]
    assert db["selected_labs"]["persistence"]
    ui = classify(["lib/screens/home_page.dart"], "fast", "a" * 40)
    assert ui["selected_labs"]["configuration"]
    assert ui["selected_labs"]["performance"]
    full = classify([], "fast", "")
    assert full["mode"] == "full" and full["fallback_full"]
    cert = classify(["README.md"], "certification", "a" * 40)
    assert cert["lane"] == "CERTIFICATION" and all(cert["selected_labs"].values())
    validate_plan(db)
    validate_plan(cert)

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "applab@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "AppLab Self Test"], check=True)

        (root / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
        (root / "lib").mkdir()
        (root / "lib" / "db.dart").write_text("class Db {}\n", encoding="utf-8")
        (root / "test").mkdir()
        (root / "test" / "db_test.dart").write_text(
            "import 'package:demo/db.dart';\nvoid main() {}\n", encoding="utf-8"
        )
        (root / "README.md").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
        baseline = _head_sha(root)

        (root / "lib" / "db.dart").write_text(
            "class DatabaseMigration {}\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "database change"], check=True)
        (root / "README.md").write_text("docs-only final commit\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "docs change"], check=True)

        evidence = git_change_evidence(root, baseline, baseline_trusted=True)
        assert evidence["trusted_range"]
        assert "lib/db.dart" in evidence["changed_files"]
        plan = plan_from_repo(root, "fast", baseline, baseline_trusted=True)
        assert plan["lane"] in {"FAST_RUNTIME", "FULL_RUNTIME"}
        assert plan["dependency_graph"]["available"]
        assert "test/db_test.dart" in plan["dependency_graph"]["impacted_files"]

        untrusted = plan_from_repo(root, "fast", baseline, baseline_trusted=False)
        assert untrusted["lane"] == "FULL_RUNTIME"
        assert untrusted["fallback_full"]

        unrelated = "f" * 40
        missing = plan_from_repo(root, "fast", unrelated, baseline_trusted=True)
        assert missing["lane"] == "FULL_RUNTIME"

        docs_base = _head_sha(root)
        (root / "README.md").write_text("docs only\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "only docs"], check=True)
        docs_plan = plan_from_repo(root, "fast", docs_base, baseline_trusted=True)
        assert docs_plan["lane"] == "NO_RUNTIME_CHANGE"
        assert not docs_plan["runtime_required"]

        # Baseline lineage must be enforced.
        subprocess.run(["git", "-C", str(root), "checkout", "--orphan", "other"], check=True, stdout=subprocess.DEVNULL)
        for path in root.iterdir():
            if path.name == ".git":
                continue
            if path.is_file():
                path.unlink()
        (root / "other.txt").write_text("other\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "unrelated"], check=True)
        unrelated_plan = plan_from_repo(root, "fast", docs_base, baseline_trusted=True)
        assert unrelated_plan["fallback_full"]
        assert unrelated_plan["lane"] == "FULL_RUNTIME"

    # Regression corpus for expected minimum coverage.
    corpus = [
        (["android/app/src/main/AndroidManifest.xml"], {"system", "upgrade"}),
        (["lib/network/api_client.dart"], {"network", "performance"}),
        (["app/src/main/java/x/Migration_4_5.kt"], {"persistence", "storage", "upgrade"}),
        (["lib/background/sync_worker.dart"], {"background", "resource_pressure", "performance"}),
        (["lib/screens/settings_page.dart"], {"configuration", "performance"}),
    ]
    for files, required in corpus:
        payload = classify(files, "fast", "a" * 40)
        selected = {lab for lab, enabled in payload["selected_labs"].items() if enabled}
        assert required <= selected, (files, required, selected)

    print("AppLab v0.9 Adaptive Impact Engine self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode", choices=("fast", "full", "certification"), default="full")
    parser.add_argument("--baseline-sha", default="")
    parser.add_argument("--baseline-trusted", action="store_true")
    parser.add_argument("--history-risk-json", default="")
    parser.add_argument("--output")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.output:
        raise SystemExit("--repo-root and --output are required")

    payload = plan_from_repo(
        Path(args.repo_root),
        args.mode,
        args.baseline_sha,
        baseline_trusted=args.baseline_trusted,
        history_risk=args.history_risk_json,
    )
    Path(args.output).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    emit_github_output(args.github_output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
