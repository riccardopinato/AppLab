#!/usr/bin/env python3
"""Read-only multi-app source structure gate. Never executes target code or builds APKs."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
ENGINES = {"flutter", "native_android", "auto"}


def fetch_json(url: str, token: str) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AppLab-Source-Gate/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def inspect_paths(paths: set[str], entry: dict) -> tuple[str, str, str]:
    """Inspect source structure only; does NOT prove compilation or behavior."""
    root = str(entry.get("working_directory") or ".").strip("/")
    root = "" if root == "." else root + "/"
    engine = str(entry.get("engine", "auto"))
    if engine not in ENGINES or ".." in root.split("/"):
        return "BLOCKED", "Invalid engine or working directory", "unknown"

    def has(suffix: str) -> bool:
        return root + suffix in paths

    def flutter() -> bool:
        return has("pubspec.yaml") and has("lib/main.dart")

    def android() -> bool:
        return (has("settings.gradle") or has("settings.gradle.kts")) and (
            has("app/build.gradle") or has("app/build.gradle.kts")
        )

    if engine == "flutter":
        return ("SOURCE_OK", "Flutter entrypoint and manifest present", "flutter") if flutter() else (
            "FAIL", "Missing Flutter pubspec.yaml or lib/main.dart", "flutter"
        )
    if engine == "native_android":
        return ("SOURCE_OK", "Gradle settings and app module present", "native_android") if android() else (
            "FAIL", "Missing Gradle settings or app module", "native_android"
        )
    if flutter():
        return "SOURCE_OK", "Flutter entrypoint and manifest present", "flutter"
    if android():
        return "SOURCE_OK", "Gradle settings and app module present", "native_android"

    # Auto-discovery can legitimately find projects in a nested directory.
    candidates = sorted(p[:-len("pubspec.yaml")] for p in paths if p.endswith("pubspec.yaml"))
    if any(prefix + "lib/main.dart" in paths for prefix in candidates):
        return "SOURCE_OK", "Nested Flutter project detected", "flutter"
    gradle_roots = sorted(p[:-len("settings.gradle.kts")] for p in paths if p.endswith("settings.gradle.kts"))
    gradle_roots += sorted(p[:-len("settings.gradle")] for p in paths if p.endswith("settings.gradle"))
    if any(prefix + "app/build.gradle.kts" in paths or prefix + "app/build.gradle" in paths for prefix in gradle_roots):
        return "SOURCE_OK", "Nested native Android project detected", "native_android"
    return "NOT_VERIFIED", "No supported Flutter/Android source structure detected", "unknown"


def check_entry(entry: dict, token: str) -> dict:
    repository = str(entry.get("repository") or "")
    ref = str(entry.get("ref") or "main")
    key = str(entry.get("key") or "")
    result = {"key": key, "repository": repository, "requested_ref": ref,
              "verification_tier": "SOURCE_STRUCTURE_ONLY", "runtime": "NOT_VERIFIED",
              "apk": "NOT_BUILT", "certification": "NOT_VERIFIED"}
    if not REPOSITORY.fullmatch(repository) or not re.fullmatch(r"[A-Za-z0-9_./-]+", ref) or ".." in ref:
        return {**result, "result": "BLOCKED", "reason": "Invalid repository or ref"}
    try:
        base = "https://api.github.com/repos/" + repository
        commit = fetch_json(base + "/commits/" + urllib.parse.quote(ref, safe=""), token)
        sha = str(commit.get("sha") or "").lower()
        tree_sha = str(commit.get("commit", {}).get("tree", {}).get("sha") or "").lower()
        if not SHA.fullmatch(sha) or not SHA.fullmatch(tree_sha):
            raise ValueError("Missing immutable commit/tree identity")
        tree = fetch_json(base + "/git/trees/" + tree_sha + "?recursive=1", token)
        if tree.get("truncated"):
            raise ValueError("Git tree truncated: cannot safely verify source structure")
        paths = {p["path"] for p in tree.get("tree", []) if p.get("type") == "blob" and isinstance(p.get("path"), str)}
        status, reason, detected = inspect_paths(paths, entry)
        return {**result, "resolved_sha": sha, "tree_sha": tree_sha,
                "result": status, "reason": reason, "detected_engine": detected}
    except (OSError, ValueError, KeyError, urllib.error.HTTPError) as exc:
        return {**result, "result": "BLOCKED", "reason": str(exc)[:300]}


def self_test() -> None:
    flutter = {"flutter_app/pubspec.yaml", "flutter_app/lib/main.dart"}
    entry = {"engine": "flutter", "working_directory": "flutter_app"}
    assert inspect_paths(flutter, entry)[0] == "SOURCE_OK"
    assert inspect_paths({"flutter_app/pubspec.yaml"}, entry)[0] == "FAIL"
    assert inspect_paths({"app/build.gradle.kts", "settings.gradle.kts"}, {"engine": "auto"})[0] == "SOURCE_OK"
    assert inspect_paths(set(), {"engine": "auto"})[0] == "NOT_VERIFIED"
    assert inspect_paths(flutter, {"engine": "flutter", "working_directory": "../secret"})[0] == "BLOCKED"
    assert inspect_paths({"nested/pubspec.yaml", "nested/lib/main.dart"}, {"engine": "auto"})[0] == "SOURCE_OK"
    print("Source gate self-test PASS (positive, negative, unsupported, traversal)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", type=Path)
    parser.add_argument("--repository", default="")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.watchlist or not args.output_dir:
        parser.error("--watchlist and --output-dir are required")
    payload = json.loads(args.watchlist.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("repositories"), list):
        raise ValueError("Invalid AppLab watchlist schema")
    known = [e for e in payload["repositories"] if isinstance(e, dict) and e.get("enabled", False)]
    if args.repository and not REPOSITORY.fullmatch(args.repository):
        raise ValueError("Invalid repository filter")
    entries = [e for e in known if not args.repository or e.get("repository") == args.repository]
    if not entries:
        raise ValueError("No enabled watchlist entries match the request")
    results = [check_entry(e, os.getenv("APPLAB_TARGET_TOKEN") or os.getenv("GITHUB_TOKEN", "")) for e in entries]
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "source-gate.json").write_text(json.dumps({"schema_version": 1, "results": results},
                                                     indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = ["# AppLab Source Gate (no APK)", "", "Only repository source structure is checked.",
            "Compilation, tests, trusted runtime and release are NOT VERIFIED.", "",
            "| Repository | SHA | Result | Engine |", "| --- | --- | --- | --- |"]
    for item in results:
        rows.append(f"| {item['repository']} | `{item.get('resolved_sha', '')[:10]}` | "
                    f"{item['result']} | {item.get('detected_engine', 'unknown')} |")
    (out / "source-gate.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))
    return 1 if any(item["result"] in {"FAIL", "BLOCKED"} for item in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"AppLab Source Gate configuration error: {exc}", file=sys.stderr)
        sys.exit(2)
