#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any

import watchdog_github_v59e as github

ENGINE_VERSION = "5.9E"
ACTIVE = {"queued", "in_progress"}


def load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported supersession policy")
    if not isinstance(payload.get("enabled"), bool):
        raise ValueError("enabled must be boolean")
    if not isinstance(payload.get("global_kill_switch"), bool):
        raise ValueError("global_kill_switch must be boolean")
    workflows = payload.get("workflow_names")
    if not isinstance(workflows, list) or not workflows:
        raise ValueError("workflow_names must be a non-empty list")
    if len(workflows) != len(set(workflows)):
        raise ValueError("workflow_names must be unique")
    protected = payload.get("protected_workflow_names", [])
    if not isinstance(protected, list):
        raise ValueError("protected_workflow_names must be a list")
    if set(workflows) & set(protected):
        raise ValueError("protected workflows cannot be cancellable")
    limit = int(payload.get("max_cancellations_per_run", 0))
    if not 1 <= limit <= 20:
        raise ValueError("max_cancellations_per_run must be 1..20")
    return payload


def group_key(run: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    event = str(run.get("event", ""))
    source_repo = str(
        (run.get("head_repository") or {}).get("full_name")
        or (run.get("repository") or {}).get("full_name")
        or ""
    )
    if not source_repo:
        return None
    pr_identity = ""
    if event == "pull_request":
        pull_requests = run.get("pull_requests")
        if not isinstance(pull_requests, list) or len(pull_requests) != 1:
            return None
        pr = pull_requests[0]
        pr_number = str(pr.get("number") or "")
        pr_head_repo = str(
            ((pr.get("head") or {}).get("repo") or {}).get("full_name")
            or source_repo
        )
        if not pr_number or not pr_head_repo:
            return None
        source_repo = pr_head_repo
        pr_identity = pr_number
    return (
        str(run.get("name", "")),
        str(run.get("head_branch", "")),
        event,
        source_repo,
        pr_identity,
    )


def plan_candidates(
    runs: list[dict[str, Any]],
    *,
    workflow_names: set[str],
    allowed_events: set[str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    active = [
        run for run in runs
        if str(run.get("status", "")) in ACTIVE
        and str(run.get("name", "")) in workflow_names
        and str(run.get("event", "")) in allowed_events
        and str(run.get("head_branch", ""))
        and str(run.get("head_sha", ""))
    ]
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for run in active:
        key = group_key(run)
        if key is not None:
            groups.setdefault(key, []).append(run)

    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for rows in groups.values():
        if len(rows) < 2:
            continue
        rows.sort(
            key=lambda item: (
                str(item.get("created_at", "")),
                int(item.get("run_number", 0)),
                int(item.get("id", 0)),
            )
        )
        newest = rows[-1]
        for old in rows[:-1]:
            if str(old.get("head_sha")) != str(newest.get("head_sha")):
                candidates.append((old, newest))
    return candidates


def fetch_workflow_runs(
    repository: str,
    token: str,
    *,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    rows: list[dict[str, Any]] = []
    for status in ("queued", "in_progress"):
        status_complete = False
        for page in range(1, max_pages + 1):
            payload = github.api(
                (
                    f"https://api.github.com/repos/{repository}/actions/runs"
                    f"?status={status}&per_page=100&page={page}"
                ),
                token,
                user_agent="AppLab-Supersession-Watchdog/5.9E",
            )
            values = (
                payload.get("workflow_runs")
                if isinstance(payload, dict)
                else None
            )
            if not isinstance(values, list):
                raise ValueError("workflow_runs response must contain a list")
            rows.extend(
                item for item in values
                if isinstance(item, dict)
            )
            if len(values) < 100:
                status_complete = True
                break
        if not status_complete:
            raise RuntimeError(
                f"{status} workflow run pagination exceeded safe page bound"
            )
    return rows


def descendant_status(
    repository: str,
    old_sha: str,
    new_sha: str,
    token: str,
) -> tuple[bool, str]:
    if old_sha == new_sha:
        return False, "IDENTICAL_SHA"
    base = urllib.parse.quote(old_sha, safe="")
    head = urllib.parse.quote(new_sha, safe="")
    payload = github.api(
        f"https://api.github.com/repos/{repository}/compare/{base}...{head}",
        token,
        user_agent="AppLab-Supersession-Watchdog/5.9E",
    )
    status = str(payload.get("status", "")).lower()
    return status == "ahead", status or "UNKNOWN"


def evaluate_candidate(
    *,
    old: dict[str, Any],
    new: dict[str, Any],
    ancestry_proven: bool,
    ancestry_status: str,
) -> dict[str, Any]:
    old_key = group_key(old)
    new_key = group_key(new)
    same_lineage = old_key is not None and old_key == new_key
    old_active = str(old.get("status", "")) in ACTIVE
    newer = (
        str(new.get("created_at", "")),
        int(new.get("run_number", 0)),
        int(new.get("id", 0)),
    ) > (
        str(old.get("created_at", "")),
        int(old.get("run_number", 0)),
        int(old.get("id", 0)),
    )
    cancel = bool(same_lineage and old_active and newer and ancestry_proven)
    return {
        "old_run_id": int(old.get("id", 0)),
        "new_run_id": int(new.get("id", 0)),
        "workflow": str(old.get("name", "")),
        "head_branch": str(old.get("head_branch", "")),
        "event": str(old.get("event", "")),
        "old_sha": str(old.get("head_sha", "")),
        "new_sha": str(new.get("head_sha", "")),
        "same_lineage": same_lineage,
        "old_active": old_active,
        "newer_run_observed": newer,
        "ancestry_proven": bool(ancestry_proven),
        "ancestry_status": ancestry_status,
        "decision": "CANCEL" if cancel else "KEEP",
        "reason": (
            "NEWER_DESCENDANT_SAME_LINEAGE"
            if cancel else "SUPERSESSION_NOT_PROVEN"
        ),
    }


def disabled_payload(repository: str, *, dry_run: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "record_type": "SUPERSESSION_WATCHDOG_V59E",
        "authority": "ORCHESTRATION_ONLY",
        "status": "DISABLED",
        "repository": repository,
        "dry_run": bool(dry_run),
        "cancellation_count": 0,
        "ancestry_required": True,
        "cross_repository_cancellation": False,
        "protected_stages_unchanged": True,
        "github_actions_fallback": True,
        "rows": [],
    }


def self_test() -> None:
    payload = disabled_payload("owner/app", dry_run=True)
    assert payload["dry_run"] is True
    assert payload["ancestry_required"] is True
    assert payload["protected_stages_unchanged"] is True
    print("AppLab v5.9E supersession support self-test PASS")


if __name__ == "__main__":
    self_test()
