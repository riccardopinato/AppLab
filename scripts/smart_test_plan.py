#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
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

SOURCE_SUFFIXES = {".kt", ".java", ".dart", ".xml", ".gradle", ".kts", ".toml", ".json", ".yaml", ".yml"}

RULES: dict[str, tuple[str, ...]] = {
    "system": (
        r"AndroidManifest\.xml$", r"permissions?", r"notification", r"deeplink", r"intent",
        r"biometric", r"camera", r"location", r"bluetooth", r"foreground.?service",
    ),
    "performance": (
        r"(^|/)(lib|src|app)/", r"build\.gradle", r"pubspec\.yaml$", r"gradle\.properties$",
        r"render", r"image", r"list", r"animation",
    ),
    "network": (
        r"network", r"http", r"api", r"retrofit", r"dio", r"ktor", r"websocket", r"sync",
        r"remote", r"repository", r"connectivity",
    ),
    "persistence": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref", r"datastore",
        r"storage", r"cache", r"sqlite", r"repository", r"model",
    ),
    "configuration": (
        r"activity", r"fragment", r"compose", r"widget", r"screen", r"page", r"view", r"layout",
        r"theme", r"orientation", r"resource", r"res/", r"lib/.*\.dart$",
    ),
    "resource_pressure": (
        r"service", r"worker", r"background", r"cache", r"image", r"bitmap", r"camera",
        r"media", r"memory", r"process",
    ),
    "background": (
        r"service", r"worker", r"workmanager", r"background", r"alarm", r"job", r"notification",
        r"battery", r"doze", r"sync",
    ),
    "storage": (
        r"database", r"room", r"dao", r"entity", r"migration", r"shared.?pref", r"datastore",
        r"storage", r"file", r"sqlite", r"backup", r"cache",
    ),
    "upgrade": (
        r"database", r"migration", r"schema", r"AndroidManifest\.xml$", r"build\.gradle",
        r"pubspec\.yaml$", r"version", r"applicationId", r"minSdk", r"targetSdk",
    ),
}

def git_changed_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        return []
    return sorted({line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()})

def classify(files: list[str], mode: str) -> dict[str, Any]:
    mode = mode.lower().strip()
    if mode not in {"fast", "full", "certification"}:
        raise ValueError("analysis mode must be fast, full or certification")

    selected = {lab: True for lab in LABS}
    reasons: dict[str, list[str]] = {lab: [] for lab in LABS}

    if mode == "full":
        for lab in LABS:
            reasons[lab].append("FULL mode")
        return {
            "schema_version": 1,
            "planner_version": "0.8.0",
            "mode": "full",
            "changed_files": files,
            "selected_labs": selected,
            "reasons": reasons,
            "fallback_full": False,
        }

    if not files:
        for lab in LABS:
            reasons[lab].append("no reliable changed-file set; safe FULL fallback")
        return {
            "schema_version": 1,
            "planner_version": "0.8.0",
            "mode": "full",
            "requested_mode": "fast",
            "changed_files": [],
            "selected_labs": selected,
            "reasons": reasons,
            "fallback_full": True,
        }

    selected = {lab: False for lab in LABS}
    for path in files:
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

    # Core UI/interaction/launch/crash verification is outside this list and always runs.
    # A code change with no specialist match still gets configuration + performance coverage.
    code_files = [
        p for p in files
        if Path(p.lower()).suffix in SOURCE_SUFFIXES
        and not p.lower().startswith(("docs/", "readme", ".github/"))
    ]
    if code_files and not any(selected.values()):
        selected["configuration"] = True
        selected["performance"] = True
        reasons["configuration"].append("generic application-code change")
        reasons["performance"].append("generic application-code change")

    return {
        "schema_version": 1,
        "planner_version": "0.8.0",
        "mode": "fast",
        "changed_files": files,
        "selected_labs": selected,
        "reasons": reasons,
        "fallback_full": False,
    }

def validate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("invalid analysis plan schema")
    mode = str(payload.get("mode", "")).lower()
    if mode not in {"fast", "full"}:
        raise ValueError("invalid analysis plan mode")
    selected = payload.get("selected_labs")
    if not isinstance(selected, dict) or set(selected) != set(LABS):
        raise ValueError("analysis plan selected_labs mismatch")
    if not all(isinstance(selected[k], bool) for k in LABS):
        raise ValueError("analysis plan lab values must be booleans")
    files = payload.get("changed_files", [])
    if not isinstance(files, list) or len(files) > 500:
        raise ValueError("invalid changed_files in analysis plan")
    for path in files:
        if not isinstance(path, str) or len(path) > 500 or "\n" in path or "\r" in path:
            raise ValueError("invalid changed file path")
    return payload

def self_test() -> None:
    docs = classify(["README.md"], "fast")
    assert not any(docs["selected_labs"].values())
    db = classify(["app/src/main/java/x/AppDatabase.kt"], "fast")
    assert db["selected_labs"]["storage"]
    assert db["selected_labs"]["persistence"]
    ui = classify(["lib/screens/home_page.dart"], "fast")
    assert ui["selected_labs"]["configuration"]
    assert ui["selected_labs"]["performance"]
    full = classify([], "fast")
    assert full["mode"] == "full" and full["fallback_full"]
    validate_plan(db)
    print("AppLab Smart Test Planner self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--mode", choices=("fast", "full", "certification"), default="full")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.output:
        raise SystemExit("--repo-root and --output are required")
    files = git_changed_files(Path(args.repo_root).resolve())
    payload = classify(files, args.mode)
    validate_plan(payload)
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
