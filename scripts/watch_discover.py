#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from contract_fingerprint import manifest as contract_manifest


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ENGINES = {"auto", "flutter", "native_android"}


def api_json(url: str, token: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AppLab-Repo-Watcher/0.9.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def validate_relative_path(value: object, field: str, repository: str) -> None:
    raw = str(value or "").strip()
    if not raw:
        return
    if raw.startswith("/") or "\n" in raw or "\r" in raw:
        raise ValueError(f"Invalid {field} for {repository}: {raw!r}")
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(f"{field} must stay inside repository: {raw!r}")


def validate_entry(entry: dict[str, Any]) -> None:
    key = str(entry.get("key", "")).strip()
    repository = str(entry.get("repository", "")).strip()
    ref = str(entry.get("ref", "")).strip()
    engine = str(entry.get("engine", "flutter")).strip()

    if not KEY_RE.fullmatch(key):
        raise ValueError(f"Invalid watcher key: {key!r}")
    if not REPO_RE.fullmatch(repository):
        raise ValueError(f"Invalid repository: {repository!r}")
    if not ref or "\n" in ref or "\r" in ref:
        raise ValueError(f"Invalid ref for {repository}: {ref!r}")
    if engine not in ENGINES:
        raise ValueError(
            f"Unsupported engine for {repository}: {engine!r}; "
            f"expected one of {sorted(ENGINES)}"
        )

    validate_relative_path(entry.get("working_directory", "."), "working_directory", repository)
    validate_relative_path(entry.get("apk_path", ""), "apk_path", repository)
    validate_relative_path(entry.get("maestro_flow", ""), "maestro_flow", repository)

    if engine != "auto":
        if not str(entry.get("build_command", "")).strip():
            raise ValueError(f"build_command is required for {repository}")
        if not str(entry.get("apk_path", "")).strip():
            raise ValueError(f"apk_path is required for {repository}")


def cache_exists(applab_repository: str, cache_key: str, token: str) -> bool:
    encoded = urllib.parse.quote(cache_key, safe="")
    url = (
        f"https://api.github.com/repos/{applab_repository}/actions/caches"
        f"?per_page=1&key={encoded}"
    )
    payload = api_json(url, token)
    return int(payload.get("total_count", 0)) > 0


def resolve_sha(repository: str, ref: str, token: str) -> str:
    encoded_ref = urllib.parse.quote(ref, safe="")
    url = f"https://api.github.com/repos/{repository}/commits/{encoded_ref}"
    payload = api_json(url, token)
    sha = str(payload.get("sha", "")).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise ValueError(f"GitHub returned an invalid SHA for {repository}@{ref}")
    return sha.lower()


def matching_history(
    path: str,
    repository: str,
    history_key: str,
    ref: str,
    engine: str,
) -> list[dict[str, Any]]:
    if not path:
        return []
    history = Path(path)
    if not history.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw in history.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if str(item.get("repository", "")).strip() != repository:
            continue
        row_key = str(item.get("history_key", "")).strip()
        if row_key and row_key != history_key:
            continue
        row_ref = str(item.get("requested_ref", "")).strip()
        row_ref_is_sha = bool(re.fullmatch(r"[0-9a-fA-F]{40}", row_ref))
        if row_ref and not row_ref_is_sha and row_ref != ref:
            continue
        row_engine = str(item.get("engine", "")).strip()
        if row_engine and row_engine != engine and engine != "auto":
            continue
        rows.append(item)
    rows.sort(key=lambda item: str(item.get("recorded_at", "")))
    return rows


def latest_history_sha(
    path: str,
    repository: str,
    history_key: str,
    ref: str,
    engine: str,
) -> str:
    latest_sha = ""
    for item in matching_history(path, repository, history_key, ref, engine):
        if str(item.get("result", "")).strip().upper() != "PASS":
            continue
        sha = str(item.get("resolved_sha", "")).strip().lower()
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            latest_sha = sha
    return latest_sha


def recent_failure_bias(
    path: str,
    repository: str,
    history_key: str,
    ref: str,
    engine: str,
) -> int:
    rows = matching_history(path, repository, history_key, ref, engine)[-20:]
    bias = 0
    consecutive_failures = 0
    for item in rows:
        result = str(item.get("result", "")).strip().upper()
        if result == "FAIL":
            bias += 3
            consecutive_failures += 1
        elif result == "PASS":
            consecutive_failures = 0
    if consecutive_failures:
        bias += min(8, consecutive_failures * 2)
    return min(25, bias)


def self_test_history() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "history.jsonl"
        rows = [
            {
                "repository": "owner/app", "history_key": "main", "requested_ref": "main",
                "engine": "flutter", "recorded_at": "2026-01-01T00:00:00Z",
                "result": "PASS", "resolved_sha": "a" * 40,
            },
            {
                "repository": "owner/app", "history_key": "beta", "requested_ref": "beta",
                "engine": "flutter", "recorded_at": "2026-01-02T00:00:00Z",
                "result": "PASS", "resolved_sha": "b" * 40,
            },
            {
                "repository": "owner/app", "history_key": "main", "requested_ref": "main",
                "engine": "flutter", "recorded_at": "2026-01-03T00:00:00Z",
                "result": "FAIL", "resolved_sha": "c" * 40,
            },
            {
                "repository": "owner/app", "history_key": "main", "requested_ref": "main",
                "engine": "flutter", "recorded_at": "2026-01-04T00:00:00Z",
                "result": "PASS", "resolved_sha": "d" * 40,
            },
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        assert latest_history_sha(str(path), "owner/app", "main", "main", "flutter") == "d" * 40
        assert latest_history_sha(str(path), "owner/app", "beta", "beta", "flutter") == "b" * 40
        assert latest_history_sha(str(path), "owner/app", "missing", "main", "flutter") == ""
        assert recent_failure_bias(str(path), "owner/app", "main", "main", "flutter") >= 3

def entry_fingerprint(entry: dict[str, Any]) -> str:
    normalized = {
        key: value
        for key, value in entry.items()
        if key not in {"cache_epoch"}
    }
    raw = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def write_matrix(path: str | None, items: list[dict[str, Any]]) -> None:
    if not path:
        return
    payload = {"include": items}
    Path(path).write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--applab-repository", default="")
    parser.add_argument("--matrix-output")
    parser.add_argument("--flutter-matrix-output")
    parser.add_argument("--native-matrix-output")
    parser.add_argument("--auto-matrix-output")
    parser.add_argument("--shadow-flutter-matrix-output")
    parser.add_argument("--shadow-native-matrix-output")
    parser.add_argument("--shadow-auto-matrix-output")
    parser.add_argument("--status-output")
    parser.add_argument("--history-file", default="")
    parser.add_argument("--only-repository", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    data = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise SystemExit("Unsupported watchlist schema_version")

    contract_state = contract_manifest(Path(__file__).resolve().parent.parent)
    full_contract_fingerprint = str(contract_state["full"])[:16]
    core_contract_fingerprint = str(contract_state["core"])[:16]
    domain_fingerprints = {
        key: str(value)[:16]
        for key, value in dict(contract_state["domains"]).items()
    }

    entries = data.get("repositories")
    if not isinstance(entries, list):
        raise SystemExit("watchlist repositories must be an array")

    seen_keys: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("watchlist entries must be objects")
        validate_entry(entry)
        key = str(entry["key"])
        if key in seen_keys:
            raise SystemExit(f"Duplicate watcher key: {key}")
        seen_keys.add(key)

    if args.validate_only:
        self_test_history()
        counts = {
            engine: sum(
                1
                for entry in entries
                if str(entry.get("engine", "flutter")) == engine
            )
            for engine in sorted(ENGINES)
        }
        print(
            f"Validated {len(entries)} AppLab watcher entries: "
            f"{counts['auto']} auto, "
            f"{counts['flutter']} flutter, "
            f"{counts['native_android']} native_android."
        )
        return 0

    applab_repository = args.applab_repository.strip()
    if not REPO_RE.fullmatch(applab_repository):
        raise SystemExit("--applab-repository must be owner/name")

    token = os.environ.get("GITHUB_TOKEN", "")
    only_repository = args.only_repository.strip()
    matrix: list[dict[str, Any]] = []
    flutter_matrix: list[dict[str, Any]] = []
    native_matrix: list[dict[str, Any]] = []
    auto_matrix: list[dict[str, Any]] = []
    shadow_flutter_matrix: list[dict[str, Any]] = []
    shadow_native_matrix: list[dict[str, Any]] = []
    shadow_auto_matrix: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []

    for entry in entries:
        if not bool(entry.get("enabled", False)):
            continue

        repository = str(entry["repository"])
        engine = str(entry.get("engine", "flutter"))
        cache_epoch = str(entry.get("cache_epoch", "legacy")).strip() or "legacy"
        if only_repository and repository != only_repository:
            continue

        config_fingerprint = entry_fingerprint(entry)
        history_rows = matching_history(
            args.history_file,
            repository,
            str(entry["key"]),
            str(entry["ref"]),
            engine,
        )
        latest_pass = next(
            (row for row in reversed(history_rows) if str(row.get("result", "")).upper() == "PASS"),
            None,
        )
        selected_domains: set[str] = {"visual"}
        if latest_pass:
            prior_plan = latest_pass.get("adaptive_plan")
            if isinstance(prior_plan, dict):
                prior_selected = prior_plan.get("selected_labs")
                if isinstance(prior_selected, dict):
                    selected_domains.update(
                        lab for lab, enabled in prior_selected.items()
                        if enabled and lab in domain_fingerprints
                    )
        if latest_pass:
            domain_material = "|".join(
                [core_contract_fingerprint]
                + [f"{name}:{domain_fingerprints[name]}" for name in sorted(selected_domains)]
            )
            contract_fingerprint = hashlib.sha256(domain_material.encode()).hexdigest()[:16]
        else:
            contract_fingerprint = full_contract_fingerprint
        item_status: dict[str, Any] = {
            "key": entry["key"],
            "engine": engine,
            "repository": repository,
            "ref": entry["ref"],
            "config_fingerprint": config_fingerprint,
        }

        try:
            sha = resolve_sha(repository, str(entry["ref"]), token)
            history_key = str(entry["key"])
            ref = str(entry["ref"])
            previous_verified_sha = latest_history_sha(
                args.history_file, repository, history_key, ref, engine
            )
            history_risk_bias = recent_failure_bias(
                args.history_file, repository, history_key, ref, engine
            )
            shadow_full_sample = int(hashlib.sha256(sha.encode()).hexdigest()[:8], 16) % 10 == 0
            cache_key = (
                f"applab-c{contract_fingerprint}-"
                f"p{config_fingerprint}-{entry['key']}-{sha}"
            )
            cached = False if args.force else cache_exists(
                applab_repository, cache_key, token
            )
            scheduled = args.force or not cached
            item_status.update(
                {
                    "resolved_sha": sha,
                    "cache_key": cache_key,
                    "cached": cached,
                    "scheduled": scheduled,
                    "previous_verified_sha": previous_verified_sha,
                    "history_risk_bias": history_risk_bias,
                    "shadow_full_sample": shadow_full_sample,
                }
            )
            if scheduled:
                resolved = {
                    **entry,
                    "engine": engine,
                    "resolved_sha": sha,
                    "previous_verified_sha": previous_verified_sha,
                    "history_risk_bias": history_risk_bias,
                    "shadow_full_sample": shadow_full_sample,
                    "cache_epoch": cache_epoch,
                    "contract_fingerprint": contract_fingerprint,
                    "config_fingerprint": config_fingerprint,
                }
                matrix.append(resolved)
                if engine == "flutter":
                    flutter_matrix.append(resolved)
                elif engine == "native_android":
                    native_matrix.append(resolved)
                elif engine == "auto":
                    auto_matrix.append(resolved)
                if shadow_full_sample:
                    if engine == "flutter":
                        shadow_flutter_matrix.append(resolved)
                    elif engine == "native_android":
                        shadow_native_matrix.append(resolved)
                    elif engine == "auto":
                        shadow_auto_matrix.append(resolved)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            item_status.update({"scheduled": False, "error": str(exc)})
        status.append(item_status)

    write_matrix(args.matrix_output, matrix)
    write_matrix(args.flutter_matrix_output, flutter_matrix)
    write_matrix(args.native_matrix_output, native_matrix)
    write_matrix(args.auto_matrix_output, auto_matrix)
    write_matrix(args.shadow_flutter_matrix_output, shadow_flutter_matrix)
    write_matrix(args.shadow_native_matrix_output, shadow_native_matrix)
    write_matrix(args.shadow_auto_matrix_output, shadow_auto_matrix)

    if not args.matrix_output:
        print(json.dumps({"include": matrix}, separators=(",", ":")))

    status_payload = {
        "schema_version": 1,
        "force": args.force,
        "only_repository": only_repository,
        "contract_fingerprint": full_contract_fingerprint,
        "core_contract_fingerprint": core_contract_fingerprint,
        "domain_fingerprints": domain_fingerprints,
        "scheduled_count": len(matrix),
        "flutter_scheduled_count": len(flutter_matrix),
        "native_scheduled_count": len(native_matrix),
        "auto_scheduled_count": len(auto_matrix),
        "shadow_scheduled_count": len(shadow_flutter_matrix) + len(shadow_native_matrix) + len(shadow_auto_matrix),
        "repositories": status,
    }

    if args.status_output:
        Path(args.status_output).write_text(
            json.dumps(status_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"AppLab watcher configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
