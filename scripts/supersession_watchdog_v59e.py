#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
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
        if key is None:
            continue
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
            if cancel
            else "SUPERSESSION_NOT_PROVEN"
        ),
    }


def self_test() -> None:
    base = {
        "name": "Controlled Event-Driven Pilot",
        "head_branch": "main",
        "event": "push",
        "status": "in_progress",
        "repository": {"full_name": "owner/app"},
    }
    old = {
        **base,
        "id": 1,
        "run_number": 10,
        "created_at": "2026-10-26T20:00:00Z",
        "head_sha": "a" * 40,
    }
    new = {
        **base,
        "id": 2,
        "run_number": 11,
        "created_at": "2026-10-26T20:05:00Z",
        "head_sha": "b" * 40,
    }
    rows = plan_candidates(
        [old, new],
        workflow_names={"Controlled Event-Driven Pilot"},
        allowed_events={"push"},
    )
    assert len(rows) == 1
    assert evaluate_candidate(
        old=old,
        new=new,
        ancestry_proven=True,
        ancestry_status="ahead",
    )["decision"] == "CANCEL"
    print("AppLab v5.9E supersession watchdog self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--config", default="config/supersession-watchdog.json")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repository or "/" not in args.repository:
        raise SystemExit("--repository owner/name is required")

    config = load_config(Path(args.config))
    if not config["enabled"] or config["global_kill_switch"]:
        payload = {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "record_type": "SUPERSESSION_WATCHDOG_V59E",
            "authority": "ORCHESTRATION_ONLY",
            "status": "DISABLED",
            "github_actions_fallback": True,
            "rows": [],
        }
    else:
        runs_payload = github.api(
            f"https://api.github.com/repos/{args.repository}/actions/runs?per_page=100",
            args.token,
            user_agent="AppLab-Supersession-Watchdog/5.9E",
        )
        runs = list(runs_payload.get("workflow_runs", []))
        candidates = plan_candidates(
            runs,
            workflow_names=set(config["workflow_names"]),
            allowed_events=set(config.get("allowed_events", ["push", "pull_request"])),
        )
        rows: list[dict[str, Any]] = []
        cancellations = 0
        max_cancel = int(config["max_cancellations_per_run"])
        for old, new in candidates:
            if cancellations >= max_cancel:
                break
            try:
                proven, status = descendant_status(
                    args.repository,
                    str(old["head_sha"]),
                    str(new["head_sha"]),
                    args.token,
                )
                decision = evaluate_candidate(
                    old=old,
                    new=new,
                    ancestry_proven=proven,
                    ancestry_status=status,
                )
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as exc:
                decision = evaluate_candidate(
                    old=old,
                    new=new,
                    ancestry_proven=False,
                    ancestry_status="LOOKUP_ERROR",
                )
                decision["reason"] = "ANCESTRY_LOOKUP_ERROR"
                decision["error"] = str(exc)
            if decision["decision"] == "CANCEL":
                if not args.dry_run:
                    github.api(
                        f"https://api.github.com/repos/{args.repository}/actions/runs/{old['id']}/cancel",
                        args.token,
                        method="POST",
                        user_agent="AppLab-Supersession-Watchdog/5.9E",
                    )
                    decision["dispatch"] = "CANCEL_REQUESTED"
                else:
                    decision["dispatch"] = "DRY_RUN"
                cancellations += 1
            else:
                decision["dispatch"] = "NONE"
            rows.append(decision)

        payload = {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "record_type": "SUPERSESSION_WATCHDOG_V59E",
            "authority": "ORCHESTRATION_ONLY",
            "status": "PASS",
            "repository": args.repository,
            "dry_run": bool(args.dry_run),
            "cancellation_count": cancellations,
            "ancestry_required": True,
            "cross_repository_cancellation": False,
            "protected_stages_unchanged": True,
            "github_actions_fallback": True,
            "rows": rows,
        }

    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
