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

from contract_fingerprint import compute as compute_contract_fingerprint, compute_selected

APPLAB_VERSION = "0.9.0"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ENGINES = {"auto", "flutter", "native_android"}
LAB_FIELDS = (
    "system_lab",
    "network_lab",
    "persistence_lab",
    "configuration_lab",
    "resource_pressure_lab",
    "background_lab",
    "storage_lab",
    "upgrade_lab",
    "performance_lab",
)


def api_json(url: str, token: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"AppLab-Repo-Watcher/{APPLAB_VERSION}",
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
    if ".." in raw.replace("\\", "/").split("/"):
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


def read_history(path: str) -> list[dict[str, Any]]:
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
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _identity_matches(
    item: dict[str, Any],
    entry: dict[str, Any],
    config_fingerprint: str,
    *,
    require_config: bool,
) -> bool:
    repository = str(entry["repository"])
    if str(item.get("repository", "")).strip() != repository:
        return False
    requested_ref = str(item.get("requested_ref", item.get("ref", ""))).strip()
    if requested_ref != str(entry.get("ref", "")).strip():
        return False
    history_key = str(item.get("history_key", "")).strip()
    if history_key and history_key != str(entry.get("key", "")).strip():
        return False

    expected_engine = str(entry.get("engine", "flutter")).strip()
    observed_engine = str(item.get("engine", "")).strip()
    if expected_engine != "auto" and observed_engine and observed_engine != expected_engine:
        return False

    observed_config = str(item.get("config_fingerprint", "")).strip()
    if require_config:
        return bool(observed_config) and observed_config == config_fingerprint
    if observed_config and observed_config != config_fingerprint:
        return False
    return True


def latest_identity_record(
    rows: list[dict[str, Any]],
    entry: dict[str, Any],
    config_fingerprint: str,
) -> dict[str, Any] | None:
    candidates = [
        item for item in rows
        if _identity_matches(item, entry, config_fingerprint, require_config=True)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("recorded_at", "")))


def latest_verified_record(
    rows: list[dict[str, Any]],
    entry: dict[str, Any],
    config_fingerprint: str,
) -> dict[str, Any] | None:
    candidates = [
        item for item in rows
        if str(item.get("result", "")).upper() == "PASS"
        and _identity_matches(item, entry, config_fingerprint, require_config=True)
        and re.fullmatch(r"[0-9a-f]{40}", str(item.get("resolved_sha", "")).lower())
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("recorded_at", "")))


def history_risk(
    rows: list[dict[str, Any]],
    entry: dict[str, Any],
    config_fingerprint: str,
) -> dict[str, Any]:
    matching = [
        item for item in rows
        if _identity_matches(item, entry, config_fingerprint, require_config=False)
    ]
    matching = sorted(
        matching,
        key=lambda item: str(item.get("recorded_at", "")),
        reverse=True,
    )[:20]

    lab_failure_counts: dict[str, int] = {}
    lab_warning_counts: dict[str, int] = {}
    for field in LAB_FIELDS:
        key = field.removesuffix("_lab") if field.endswith("_lab") else field
        if field == "resource_pressure_lab":
            key = "resource_pressure"
        hard = sum(
            1 for item in matching
            if str(item.get(field, "")).upper() in {"FAIL", "ERROR"}
        )
        warns = sum(
            1 for item in matching
            if str(item.get(field, "")).upper() in {"WARN", "NO_BASELINE"}
        )
        if hard:
            lab_failure_counts[key] = hard
        if warns:
            lab_warning_counts[key] = warns

    shadow_false_negatives = 0
    shadow_over_selection = 0
    for item in matching:
        shadow = item.get("shadow_calibration")
        if isinstance(shadow, dict):
            shadow_false_negatives += int(shadow.get("false_negatives", 0) or 0)
            shadow_over_selection += int(shadow.get("over_selection", 0) or 0)

    return {
        "sample_size": len(matching),
        "recent_pipeline_failures": sum(
            1 for item in matching if str(item.get("result", "")).upper() == "FAIL"
        ),
        "lab_failure_counts": lab_failure_counts,
        "lab_warning_counts": lab_warning_counts,
        "shadow_false_negatives": shadow_false_negatives,
        "shadow_over_selection": shadow_over_selection,
    }


def self_test_history() -> None:
    entry = {
        "key": "watch-one",
        "repository": "owner/app",
        "ref": "main",
        "engine": "flutter",
    }
    rows = [
        {
            "repository": "owner/app", "requested_ref": "main",
            "history_key": "watch-one", "engine": "flutter",
            "config_fingerprint": "cfg", "recorded_at": "2026-01-01T00:00:00Z",
            "result": "PASS", "resolved_sha": "a" * 40,
        },
        {
            "repository": "owner/app", "requested_ref": "beta",
            "history_key": "watch-one", "engine": "flutter",
            "config_fingerprint": "cfg", "recorded_at": "2026-01-02T00:00:00Z",
            "result": "PASS", "resolved_sha": "b" * 40,
        },
        {
            "repository": "owner/app", "requested_ref": "main",
            "history_key": "watch-one", "engine": "flutter",
            "config_fingerprint": "other", "recorded_at": "2026-01-03T00:00:00Z",
            "result": "PASS", "resolved_sha": "c" * 40,
        },
        {
            "repository": "owner/app", "requested_ref": "main",
            "history_key": "watch-one", "engine": "flutter",
            "config_fingerprint": "cfg", "recorded_at": "2026-01-04T00:00:00Z",
            "result": "FAIL", "resolved_sha": "d" * 40, "network_lab": "FAIL",
        },
    ]
    record = latest_verified_record(rows, entry, "cfg")
    assert record and record["resolved_sha"] == "a" * 40
    risk = history_risk(rows, entry, "cfg")
    assert risk["recent_pipeline_failures"] == 1
    assert risk["lab_failure_counts"]["network"] == 1


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
    Path(path).write_text(
        json.dumps({"include": items}, separators=(",", ":")) + "\n",
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
    parser.add_argument("--status-output")
    parser.add_argument("--history-file", default="")
    parser.add_argument("--only-repository", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    data = json.loads(Path(args.watchlist).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise SystemExit("Unsupported watchlist schema_version")

    applab_root = Path(__file__).resolve().parent.parent
    contract_fingerprint = compute_contract_fingerprint(applab_root)[:16]

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
                1 for entry in entries
                if str(entry.get("engine", "flutter")) == engine
            )
            for engine in sorted(ENGINES)
        }
        print(
            f"Validated {len(entries)} AppLab watcher entries: "
            f"{counts['auto']} auto, {counts['flutter']} flutter, "
            f"{counts['native_android']} native_android."
        )
        return 0

    applab_repository = args.applab_repository.strip()
    if not REPO_RE.fullmatch(applab_repository):
        raise SystemExit("--applab-repository must be owner/name")

    token = os.environ.get("GITHUB_TOKEN", "")
    history_rows = read_history(args.history_file)
    only_repository = args.only_repository.strip()
    matrix: list[dict[str, Any]] = []
    flutter_matrix: list[dict[str, Any]] = []
    native_matrix: list[dict[str, Any]] = []
    auto_matrix: list[dict[str, Any]] = []
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
        item_status: dict[str, Any] = {
            "key": entry["key"],
            "engine": engine,
            "repository": repository,
            "ref": entry["ref"],
            "config_fingerprint": config_fingerprint,
        }

        try:
            sha = resolve_sha(repository, str(entry["ref"]), token)
            verified = latest_verified_record(history_rows, entry, config_fingerprint)
            previous_verified_sha = (
                str(verified.get("resolved_sha", "")).lower() if verified else ""
            )
            baseline_trusted = bool(previous_verified_sha)
            risk = history_risk(history_rows, entry, config_fingerprint)

            latest_identity = latest_identity_record(
                history_rows, entry, config_fingerprint
            )
            selected_for_previous = (
                latest_identity.get("selected_labs", {})
                if isinstance(latest_identity, dict)
                else {}
            )
            selected_contract = compute_selected(
                applab_root,
                selected_for_previous if isinstance(selected_for_previous, dict) else {},
                certification=bool(
                    isinstance(latest_identity, dict)
                    and str(latest_identity.get("analysis_mode", "")) == "certification"
                ),
            )[:16]
            history_cached = bool(
                latest_identity
                and str(latest_identity.get("resolved_sha", "")).lower() == sha
                and str(latest_identity.get("verification_contract_fingerprint", ""))
                    == selected_contract
            )
            cache_key = (
                f"applab-c{selected_contract}-"
                f"p{config_fingerprint}-{entry['key']}-{sha}"
            )
            legacy_cached = False
            if not history_cached and not args.force:
                legacy_key = (
                    f"applab-c{contract_fingerprint}-"
                    f"p{config_fingerprint}-{entry['key']}-{sha}"
                )
                legacy_cached = cache_exists(applab_repository, legacy_key, token)
            cached = False if args.force else (history_cached or legacy_cached)
            scheduled = args.force or not cached
            item_status.update({
                "resolved_sha": sha,
                "cache_key": cache_key,
                "cached": cached,
                "scheduled": scheduled,
                "previous_verified_sha": previous_verified_sha,
                "baseline_trusted": baseline_trusted,
                "history_risk": risk,
                "selected_contract_fingerprint": selected_contract,
                "history_cached": history_cached,
            })
            if scheduled:
                resolved = {
                    **entry,
                    "engine": engine,
                    "resolved_sha": sha,
                    "previous_verified_sha": previous_verified_sha,
                    "baseline_trusted": baseline_trusted,
                    "history_risk": risk,
                    "cache_epoch": cache_epoch,
                    "contract_fingerprint": contract_fingerprint,
                    "config_fingerprint": config_fingerprint,
                }
                matrix.append(resolved)
                if engine == "flutter":
                    flutter_matrix.append(resolved)
                elif engine == "native_android":
                    native_matrix.append(resolved)
                else:
                    auto_matrix.append(resolved)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            item_status.update({"scheduled": False, "error": str(exc)})
        status.append(item_status)

    write_matrix(args.matrix_output, matrix)
    write_matrix(args.flutter_matrix_output, flutter_matrix)
    write_matrix(args.native_matrix_output, native_matrix)
    write_matrix(args.auto_matrix_output, auto_matrix)

    if not args.matrix_output:
        print(json.dumps({"include": matrix}, separators=(",", ":")))

    status_payload = {
        "schema_version": 2,
        "applab_version": APPLAB_VERSION,
        "force": args.force,
        "only_repository": only_repository,
        "contract_fingerprint": contract_fingerprint,
        "scheduled_count": len(matrix),
        "flutter_scheduled_count": len(flutter_matrix),
        "native_scheduled_count": len(native_matrix),
        "auto_scheduled_count": len(auto_matrix),
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
