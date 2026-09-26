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

LABS = (
    "system", "performance", "network", "persistence", "configuration",
    "resource_pressure", "background", "storage", "upgrade",
)
SOURCE_SUFFIXES = {".kt", ".java", ".dart", ".xml", ".gradle", ".kts", ".toml", ".json", ".yaml", ".yml"}
DOC_PREFIXES = ("docs/", "readme", "changelog", "license", ".github/issue", ".github/pull")
STATIC_PREFIXES = ("test/", "tests/", "androidtest/", ".github/")

ROOT_DOC_NAMES = {
    "readme", "readme.md", "readme.txt", "changelog", "changelog.md",
    "license", "license.md", "license.txt", "contributing.md",
    "code_of_conduct.md", "security.md",
}

def is_documentation_path(path: str) -> bool:
    value = path.replace("\\", "/").lower().lstrip("./")
    name = value.rsplit("/", 1)[-1]
    return (
        value.startswith(("docs/", "documentation/", ".github/issue", ".github/pull"))
        or ("/" not in value and name in ROOT_DOC_NAMES)
    )
GLOBAL_RISK_PATTERNS = (
    r"pubspec\.ya?ml$", r"gradle\.properties$", r"settings\.gradle", r"build\.gradle",
    r"libs\.versions\.toml$", r"androidmanifest\.xml$", r"minSdk", r"targetSdk",
    r"applicationId", r"namespace", r"proguard", r"signing", r"schema", r"migration",
)
RULES: dict[str, tuple[str, ...]] = {
    "system": (r"AndroidManifest\.xml$", r"permissions?", r"notification", r"deeplink", r"intent",
               r"biometric", r"camera", r"location", r"bluetooth", r"foreground.?service"),
    "performance": (r"(^|/)(lib|src|app)/", r"build\.gradle", r"pubspec\.yaml$", r"render",
                    r"image", r"list", r"animation", r"compose", r"widget"),
    "network": (r"network", r"http", r"api", r"retrofit", r"dio", r"ktor", r"websocket",
                r"sync", r"remote", r"repository", r"connectivity"),
    "persistence": (r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref",
                    r"datastore", r"storage", r"cache", r"sqlite", r"repository", r"model"),
    "configuration": (r"activity", r"fragment", r"compose", r"widget", r"screen", r"page",
                      r"view", r"layout", r"theme", r"orientation", r"resource", r"res/",
                      r"lib/.*\.dart$"),
    "resource_pressure": (r"service", r"worker", r"background", r"cache", r"image", r"bitmap",
                          r"camera", r"media", r"memory", r"process"),
    "background": (r"service", r"worker", r"workmanager", r"background", r"alarm", r"job",
                   r"notification", r"battery", r"doze", r"sync"),
    "storage": (r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref",
                r"datastore", r"storage", r"file", r"sqlite", r"backup", r"cache"),
    "upgrade": (r"database", r"migration", r"schema", r"AndroidManifest\.xml$", r"build\.gradle",
                r"pubspec\.yaml$", r"version", r"applicationId", r"minSdk", r"targetSdk"),
}

def _run(repo: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False, timeout=timeout)

def baseline_status(repo: Path, baseline_sha: str) -> tuple[bool, str]:
    baseline = baseline_sha.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", baseline):
        return False, "missing-or-invalid-baseline"
    exists = _run(repo, "cat-file", "-e", f"{baseline}^{{commit}}", timeout=15)
    if exists.returncode != 0:
        return False, "baseline-not-present"
    ancestor = _run(repo, "merge-base", "--is-ancestor", baseline, "HEAD", timeout=15)
    if ancestor.returncode != 0:
        return False, "baseline-not-ancestor"
    return True, "trusted-ancestor"

def git_diff_evidence(repo: Path, baseline_sha: str, max_files: int = 500) -> dict[str, Any]:
    ok, status = baseline_status(repo, baseline_sha)
    if not ok:
        return {"trusted": False, "status": status, "files": [], "too_large": False,
                "additions": 0, "deletions": 0, "hunks": []}
    range_spec = f"{baseline_sha}..HEAD"
    name_status = _run(repo, "diff", "--name-status", "--find-renames", range_spec)
    numstat = _run(repo, "diff", "--numstat", "--find-renames", range_spec)
    patch = _run(repo, "diff", "--unified=0", "--no-color", range_spec, timeout=45)
    if name_status.returncode or numstat.returncode or patch.returncode:
        return {"trusted": False, "status": "diff-failed", "files": [], "too_large": False,
                "additions": 0, "deletions": 0, "hunks": []}
    files: list[dict[str, Any]] = []
    for raw in name_status.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        code = parts[0]
        path = (parts[-1] or "").replace("\\", "/")
        previous = parts[1].replace("\\", "/") if code.startswith("R") and len(parts) > 2 else ""
        files.append({"path": path, "status": code[:1], "previous_path": previous})
    additions = deletions = 0
    stats: dict[str, tuple[int, int]] = {}
    for raw in numstat.stdout.splitlines():
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        try:
            a = 0 if parts[0] == "-" else int(parts[0])
            d = 0 if parts[1] == "-" else int(parts[1])
        except ValueError:
            continue
        path = parts[-1].replace("\\", "/")
        stats[path] = (a, d)
        additions += a
        deletions += d
    for item in files:
        a, d = stats.get(item["path"], (0, 0))
        item["additions"], item["deletions"] = a, d
    hunks = [line[:500] for line in patch.stdout.splitlines()
             if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))][:200]
    too_large = len(files) > max_files or additions + deletions > 20000
    return {"trusted": True, "status": "ok", "files": files[:max_files],
            "file_count": len(files), "too_large": too_large,
            "additions": additions, "deletions": deletions, "hunks": hunks}

def tracked_files(repo: Path) -> list[str]:
    result = _run(repo, "ls-files", timeout=30)
    if result.returncode == 0:
        return [x.strip().replace("\\", "/") for x in result.stdout.splitlines() if x.strip()]
    return []

def _imports_from_head(repo: Path, relative: str) -> list[str]:
    blob = _run(repo, "show", f"HEAD:{relative}", timeout=15)
    if blob.returncode != 0:
        return []
    found: list[str] = []
    for pattern in (
        r"(?m)^\s*import\s+['\"]([^'\"]+)['\"]",
        r"(?m)^\s*import\s+([A-Za-z0-9_.*]+)",
    ):
        found.extend(re.findall(pattern, blob.stdout))
    return found[:100]

def dependency_impacts(repo: Path, changed: list[str], tracked: list[str]) -> list[str]:
    changed_set = set(changed)
    stems = {Path(p).stem.lower() for p in changed if Path(p).suffix.lower() in {".dart", ".kt", ".java"}}
    if not stems:
        return []
    impacted: set[str] = set()
    candidates = [p for p in tracked if Path(p).suffix.lower() in {".dart", ".kt", ".java"}]
    # Bounded reverse-import graph: deterministic and conservative.
    for rel in candidates[:5000]:
        if rel in changed_set:
            continue
        imports = _imports_from_head(repo, rel)
        joined = " ".join(imports).lower()
        if any(stem and stem in joined for stem in stems):
            impacted.add(rel)
            if len(impacted) >= 200:
                break
    return sorted(impacted)

def historical_failure_boost(
    history_file: str,
    repository: str,
    selected: dict[str, bool],
    history_key: str = "",
    source_ref: str = "",
) -> tuple[int, dict[str, int]]:
    if not history_file or not Path(history_file).is_file():
        return 0, {}
    counts = {lab: 0 for lab in LABS}
    rows = Path(history_file).read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
    for raw in rows:
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if repository and item.get("repository") != repository:
            continue
        if history_key and str(item.get("history_key", "")).strip() not in {"", history_key}:
            continue
        item_ref = str(item.get("requested_ref", item.get("ref", ""))).strip()
        if (
            source_ref
            and item_ref
            and item_ref != source_ref
            and not re.fullmatch(r"[0-9a-fA-F]{40}", item_ref)
        ):
            continue
        for lab in LABS:
            if str(item.get(f"{lab}_lab" if lab not in {"system", "performance"} else
                            ("system_lab" if lab == "system" else "performance_lab"), "")).upper() in {"FAIL", "ERROR"}:
                counts[lab] += 1
    active = {lab: n for lab, n in counts.items() if n and selected.get(lab)}
    return min(20, sum(min(n, 3) * 2 for n in active.values())), active

def targeted_paths(changed: list[str], impacted: list[str]) -> dict[str, Any]:
    dart = sorted({p for p in changed + impacted if p.endswith(".dart") and not p.startswith(("test/", "tests/"))})
    dart_tests: set[str] = set()
    for p in dart:
        candidate = ""
        if p.startswith("lib/"):
            candidate = "test/" + p[4:]
        elif "/lib/" in p:
            prefix, suffix = p.split("/lib/", 1)
            candidate = f"{prefix}/test/{suffix}"
        if candidate:
            candidate = re.sub(r"\.dart$", "_test.dart", candidate)
            dart_tests.add(candidate)
    gradle_modules: set[str] = set()
    for p in changed:
        parts = p.split("/")
        if len(parts) > 1 and parts[0] not in {"lib", "src", "test", "tests", ".github"}:
            gradle_modules.add(parts[0])
        elif p.startswith("app/"):
            gradle_modules.add("app")
    return {"dart_analyze": dart[:100], "dart_tests": sorted(dart_tests)[:100],
            "gradle_modules": sorted(gradle_modules)[:20]}

def classify(files: list[str], mode: str, baseline_sha: str = "") -> dict[str, Any]:
    # Backward-compatible path-only classifier used by callers/tests.
    evidence = {"trusted": bool(files), "status": "compat", "files": [{"path": p, "status": "M", "additions": 0, "deletions": 0} for p in files],
                "file_count": len(files), "too_large": len(files) > 500, "additions": 0, "deletions": 0, "hunks": []}
    return classify_evidence(evidence, mode, baseline_sha)

def classify_evidence(evidence: dict[str, Any], mode: str, baseline_sha: str = "",
                      impacted: list[str] | None = None, history_file: str = "",
                      repository: str = "", head_sha: str = "", shadow_every: int = 10,
                      history_key: str = "", source_ref: str = "") -> dict[str, Any]:
    mode = mode.lower().strip()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")
    impacted = impacted or []
    changed = [str(x.get("path", "")) for x in evidence.get("files", []) if x.get("path")]
    previous_paths = [
        str(x.get("previous_path", ""))
        for x in evidence.get("files", [])
        if str(x.get("status", "")) == "R" and x.get("previous_path")
    ]
    classification_paths = list(dict.fromkeys(changed + previous_paths))
    selected = {lab: mode in {"full", "certification"} for lab in LABS}
    reasons: dict[str, list[str]] = {lab: [] for lab in LABS}
    if mode in {"full", "certification"}:
        for lab in LABS:
            reasons[lab].append("FULL mode" if mode == "full" else "CERTIFICATION mode")
        return _plan(mode, mode, "FULL_RUNTIME" if mode == "full" else "CERTIFICATION",
                     baseline_sha, evidence, selected, reasons, 100 if mode == "certification" else 80,
                     1.0, impacted, False, False, repository)

    if not evidence.get("trusted") or evidence.get("too_large"):
        for lab in LABS:
            reasons[lab].append("untrusted/oversized diff; safe FULL fallback")
        return _plan("fast", "full", "FULL_RUNTIME", baseline_sha, evidence,
                     {lab: True for lab in LABS}, reasons, 90, 0.0, impacted, True, False, repository)

    if not classification_paths:
        for lab in LABS:
            reasons[lab].append("trusted empty target diff; contract/cache invalidation requires FULL rerun")
        return _plan("fast", "full", "FULL_RUNTIME", baseline_sha, evidence,
                     {lab: True for lab in LABS}, reasons, 80, 0.99, impacted, True, False, repository)

    lower_paths = [p.lower() for p in classification_paths]
    docs_only = all(is_documentation_path(p) for p in lower_paths)
    static_only = all(
        is_documentation_path(p) or p.startswith(STATIC_PREFIXES)
        for p in lower_paths
    )
    if docs_only:
        return _plan("fast", "fast", "NO_RUNTIME_CHANGE", baseline_sha, evidence,
                     {lab: False for lab in LABS}, reasons, 0, 0.99, impacted, False, False, repository)
    if static_only:
        return _plan("fast", "fast", "STATIC_ONLY", baseline_sha, evidence,
                     {lab: False for lab in LABS}, reasons, 15, 0.95, impacted, False, False, repository)

    risk = 20
    changed_hunks = [str(value) for value in evidence.get("hunks", [])]
    changed_text = "\n".join(classification_paths + changed_hunks)
    for item in evidence.get("files", []):
        path = str(item.get("path", ""))
        prior = str(item.get("previous_path", "")) if item.get("status") == "R" else ""
        churn = int(item.get("additions", 0)) + int(item.get("deletions", 0))
        risk += min(10, churn // 100)
        if item.get("status") in {"D", "R"}:
            risk += 5
        for candidate in [p for p in (path, prior) if p]:
            lower = candidate.lower()
            suffix = Path(lower).suffix
            for lab, patterns in RULES.items():
                if any(re.search(pattern, lower, re.I) for pattern in patterns):
                    selected[lab] = True
                    reasons[lab].append(candidate if candidate == path else f"rename-source:{candidate}")
            if suffix in SOURCE_SUFFIXES and ("/src/" in f"/{lower}" or lower.startswith(("lib/", "app/"))):
                selected["performance"] = True
                reasons["performance"].append(candidate if candidate == path else f"rename-source:{candidate}")
    for pattern in GLOBAL_RISK_PATTERNS:
        if (
            any(re.search(pattern, path, re.I) for path in classification_paths)
            or any(re.search(pattern, hunk, re.I) for hunk in changed_hunks)
        ):
            risk += 8

    # Content-aware specialist selection: generic filenames must not hide a
    # runtime capability introduced inside the changed hunks.
    semantic_text = "\n".join(str(x) for x in evidence.get("hunks", []))
    for lab, patterns in RULES.items():
        semantic_patterns = [
            pattern for pattern in patterns
            if not pattern.startswith("(^|/)") and not pattern.endswith("\\$")
        ]
        if semantic_text and any(re.search(pattern, semantic_text, re.I) for pattern in semantic_patterns):
            selected[lab] = True
            reasons[lab].append("changed-hunk semantic match")
            risk += 4

    if impacted:
        risk += min(15, len(impacted) // 5 + 3)
        for p in impacted[:50]:
            lower = p.lower()
            for lab, patterns in RULES.items():
                if any(re.search(pattern, lower, re.I) for pattern in patterns):
                    selected[lab] = True
                    reasons[lab].append(f"dependency:{p}")
    boost, failures = historical_failure_boost(
        history_file, repository, selected, history_key, source_ref
    )
    risk += boost
    risk = max(0, min(100, risk))
    confidence = max(0.35, min(0.99, 0.96 - min(len(changed), 100) * 0.002 - min(len(impacted), 100) * 0.001))
    if failures:
        confidence = max(0.35, confidence - 0.05)

    if not any(selected.values()):
        selected["configuration"] = True
        selected["performance"] = True
        reasons["configuration"].append("generic runtime source change")
        reasons["performance"].append("generic runtime source change")

    lane = "FAST_RUNTIME"
    fallback = False
    if risk >= 70 or confidence < 0.60:
        lane = "FULL_RUNTIME"
        selected = {lab: True for lab in LABS}
        fallback = True
        for lab in LABS:
            reasons[lab].append("risk/confidence escalation to FULL")

    predicted = dict(selected)
    shadow = False
    if lane == "FAST_RUNTIME" and shadow_every > 0 and re.fullmatch(r"[0-9a-f]{40}", head_sha or ""):
        shadow = int(head_sha[-8:], 16) % shadow_every == 0
        if shadow:
            lane = "FULL_RUNTIME"
            selected = {lab: True for lab in LABS}
            for lab in LABS:
                reasons[lab].append("shadow FULL calibration sample")

    plan = _plan("fast", "full" if lane == "FULL_RUNTIME" else "fast", lane, baseline_sha,
                 evidence, selected, reasons, risk, confidence, impacted, fallback, shadow, repository)
    plan["predicted_selected_labs"] = predicted
    plan["historical_failures"] = failures
    return plan

def _plan(requested: str, effective: str, lane: str, baseline_sha: str, evidence: dict[str, Any],
          selected: dict[str, bool], reasons: dict[str, list[str]], risk: int, confidence: float,
          impacted: list[str], fallback: bool, shadow: bool, repository: str) -> dict[str, Any]:
    changed = [str(x.get("path", "")) for x in evidence.get("files", []) if x.get("path")]
    targets = targeted_paths(changed, impacted)
    return {
        "schema_version": 2, "planner_version": "0.9.0", "requested_mode": requested,
        "mode": effective, "lane": lane, "repository": repository, "baseline_sha": baseline_sha,
        "diff_status": evidence.get("status", ""), "changed_files": changed,
        "changes": evidence.get("files", []), "additions": int(evidence.get("additions", 0)),
        "deletions": int(evidence.get("deletions", 0)), "impacted_files": impacted,
        "selected_labs": selected, "reasons": reasons, "risk_score": risk,
        "confidence": round(confidence, 3), "fallback_full": fallback, "shadow_full": shadow,
        "run_static": lane not in {"NO_RUNTIME_CHANGE"},
        "run_build": lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"},
        "run_runtime": lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"},
        "targets": targets,
    }

def analyze_repository(repo_root: Path, mode: str, baseline_sha: str = "", history_file: str = "",
                       repository: str = "", shadow_every: int = 10,
                       history_key: str = "", source_ref: str = "") -> dict[str, Any]:
    start = time.perf_counter()
    head = _run(repo_root, "rev-parse", "HEAD", timeout=15)
    head_sha = head.stdout.strip().lower() if head.returncode == 0 else ""
    evidence = git_diff_evidence(repo_root, baseline_sha)
    changed = [str(x.get("path", "")) for x in evidence.get("files", []) if x.get("path")]
    impacted = dependency_impacts(repo_root, changed, tracked_files(repo_root)) if evidence.get("trusted") else []
    plan = classify_evidence(
        evidence,
        mode,
        baseline_sha,
        impacted,
        history_file,
        repository,
        head_sha,
        shadow_every,
        history_key,
        source_ref,
    )
    plan["head_sha"] = head_sha
    plan["history_key"] = history_key
    plan["source_ref"] = source_ref
    plan["planner_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return plan

def validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
        raise ValueError("invalid analysis plan schema")
    mode = str(payload.get("mode", "")).lower()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("invalid analysis plan mode")
    selected = payload.get("selected_labs")
    if not isinstance(selected, dict) or set(selected) != set(LABS) or not all(isinstance(selected[k], bool) for k in LABS):
        raise ValueError("analysis plan selected_labs mismatch")
    files = payload.get("changed_files", [])
    if not isinstance(files, list) or len(files) > 500:
        raise ValueError("invalid changed_files in analysis plan")
    if payload.get("schema_version") == 2:
        if payload.get("lane") not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY", "FAST_RUNTIME", "FULL_RUNTIME", "CERTIFICATION"}:
            raise ValueError("invalid adaptive lane")
        if not 0 <= int(payload.get("risk_score", -1)) <= 100:
            raise ValueError("invalid risk score")
        if not 0.0 <= float(payload.get("confidence", -1)) <= 1.0:
            raise ValueError("invalid confidence")
    return payload

def regression_corpus_test() -> None:
    corpus_path = Path(__file__).resolve().parent.parent / "integration" / "performance" / "planner-regression-corpus.json"
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cases"), list):
        raise AssertionError("invalid planner regression corpus")
    for case in payload["cases"]:
        plan = classify(list(case.get("files", [])), "fast", "a" * 40)
        assert plan["lane"] == case["lane"], f"{case['name']}: lane {plan['lane']}"
        for lab in case.get("labs", []):
            assert plan["selected_labs"].get(lab), f"{case['name']}: expected {lab}"


def self_test() -> None:
    regression_corpus_test()
    docs = classify(["README.md"], "fast", "a"*40)
    assert docs["lane"] == "NO_RUNTIME_CHANGE"
    db = classify(["app/src/main/java/x/AppDatabase.kt"], "fast", "a"*40)
    assert db["selected_labs"]["storage"] and db["selected_labs"]["persistence"]
    static = classify(["test/foo_test.dart"], "fast", "a"*40)
    assert static["lane"] == "STATIC_ONLY"
    asset = classify(["assets/content.md"], "fast", "a"*40)
    assert asset["lane"] not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}
    rename = classify_evidence(
        {
            "trusted": True, "status": "ok",
            "files": [{"path": "test/worker_test.dart", "previous_path": "lib/worker.dart",
                       "status": "R", "additions": 0, "deletions": 0}],
            "file_count": 1, "too_large": False, "additions": 0, "deletions": 0, "hunks": [],
        },
        "fast", "a"*40,
    )
    assert rename["lane"] not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}
    empty = classify_evidence(
        {"trusted": True, "status": "ok", "files": [], "file_count": 0,
         "too_large": False, "additions": 0, "deletions": 0, "hunks": []},
        "fast", "a"*40,
    )
    assert empty["lane"] == "FULL_RUNTIME" and empty["fallback_full"]
    gradle_config = classify_evidence(
        {
            "trusted": True, "status": "ok",
            "files": [{"path": "gradle.properties", "status": "M", "additions": 1, "deletions": 0}],
            "file_count": 1, "too_large": False, "additions": 1, "deletions": 0, "hunks": [],
        },
        "fast", "a"*40,
    )
    assert gradle_config["risk_score"] >= 28
    semantic = classify_evidence(
        {
            "trusted": True,
            "status": "ok",
            "files": [{"path": "lib/core/manager.dart", "status": "M", "additions": 1, "deletions": 0}],
            "file_count": 1,
            "too_large": False,
            "additions": 1,
            "deletions": 0,
            "hunks": ["+ final client = http.Client();"],
        },
        "fast",
        "a"*40,
    )
    assert semantic["selected_labs"]["network"]
    huge = classify([f"lib/f{i}.dart" for i in range(501)], "fast", "a"*40)
    assert huge["mode"] == "full" and huge["fallback_full"]
    cert = classify(["README.md"], "certification", "a"*40)
    assert cert["lane"] == "CERTIFICATION" and all(cert["selected_labs"].values())

    with tempfile.TemporaryDirectory() as raw_history:
        history = Path(raw_history) / "history.jsonl"
        history.write_text(
            "\n".join(
                json.dumps(row)
                for row in (
                    {
                        "repository": "owner/app",
                        "history_key": "main",
                        "requested_ref": "main",
                        "network_lab": "FAIL",
                    },
                    {
                        "repository": "owner/app",
                        "history_key": "beta",
                        "requested_ref": "beta",
                        "network_lab": "FAIL",
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        selected = {lab: lab == "network" for lab in LABS}
        boost, failures = historical_failure_boost(
            str(history), "owner/app", selected, "main", "main"
        )
        assert boost == 2 and failures == {"network": 1}

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "applab@example.test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "AppLab Self Test"], check=True)
        (root/"lib").mkdir()
        (root/"lib"/"api.dart").write_text("class Api {}\n")
        (root/"lib"/"home.dart").write_text("import 'api.dart';\n")
        subprocess.run(["git","-C",str(root),"add","."],check=True)
        subprocess.run(["git","-C",str(root),"commit","-qm","base"],check=True)
        baseline=_run(root,"rev-parse","HEAD").stdout.strip()
        (root/"lib"/"api.dart").write_text("class Api { void httpCall() {} }\n")
        subprocess.run(["git","-C",str(root),"add","."],check=True)
        subprocess.run(["git","-C",str(root),"commit","-qm","api"],check=True)
        plan=analyze_repository(root,"fast",baseline,shadow_every=0)
        assert "lib/home.dart" in plan["impacted_files"]
        assert plan["run_runtime"]
        api_head=_run(root,"rev-parse","HEAD").stdout.strip()
        orphan="f"*40
        fallback=analyze_repository(root,"fast",orphan,shadow_every=0)
        assert fallback["mode"]=="full" and fallback["fallback_full"]
        subprocess.run(["git","-C",str(root),"checkout","-qb","other",baseline],check=True)
        (root/"lib"/"other.dart").write_text("void other(){}\n")
        subprocess.run(["git","-C",str(root),"add","."],check=True)
        subprocess.run(["git","-C",str(root),"commit","-qm","other"],check=True)
        nonancestor=analyze_repository(root,"fast",api_head,shadow_every=0)
        assert nonancestor["mode"]=="full"
    print("AppLab Adaptive Impact Planner self-test PASS")

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode",choices=("fast","full","certification"),default="full")
    parser.add_argument("--baseline-sha",default="")
    parser.add_argument("--history-file",default="")
    parser.add_argument("--repository",default="")
    parser.add_argument("--history-key",default="")
    parser.add_argument("--source-ref",default="")
    parser.add_argument("--shadow-every",type=int,default=10)
    parser.add_argument("--output")
    parser.add_argument("--github-output",default="")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.repo_root or not args.output:
        raise SystemExit("--repo-root and --output are required")
    plan=analyze_repository(
        Path(args.repo_root).resolve(),
        args.mode,
        args.baseline_sha,
        args.history_file,
        args.repository,
        args.shadow_every,
        args.history_key,
        args.source_ref,
    )
    validate_plan(plan)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(plan,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a",encoding="utf-8") as h:
            for key in ("mode","lane","run_static","run_build","run_runtime","shadow_full","risk_score","confidence"):
                value=plan[key]
                h.write(f"{key}={str(value).lower() if isinstance(value,bool) else value}\n")
    print(json.dumps(plan,indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
