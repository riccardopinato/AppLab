#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import external_review_support_v59e as support
import watchdog_github_v59e as github

ENGINE_VERSION = "5.9E"


def request_review(
    repository: str,
    pr_number: int,
    head_sha: str,
    attempt: int,
    request_body: str,
    token: str,
) -> None:
    body = (
        request_body.strip()
        + "\n\n"
        + f"<!-- applab-review-watchdog:v1 head={head_sha} attempt={attempt} -->"
    )
    github.api(
        f"https://api.github.com/repos/{repository}/issues/{pr_number}/comments",
        token,
        method="POST",
        payload={"body": body},
        user_agent="AppLab-External-Review-Watchdog/5.9E",
    )


def reconcile(
    *,
    repository: str,
    config: dict[str, Any],
    token: str,
    dry_run: bool,
    now: datetime,
) -> dict[str, Any]:
    timeout = int(config.get("timeout_seconds", 900))
    max_retries = int(config.get("max_retries", 2))
    include_drafts = bool(config.get("include_drafts", False))
    limit = int(config.get("max_open_prs_per_run", 20))
    request_body = str(config.get("request_body", "@codex review"))
    review_bot_login = str(
        config.get("review_bot_login", "chatgpt-codex-connector[bot]")
    )
    watchdog_actor_login = str(
        config.get("watchdog_actor_login", "github-actions[bot]")
    )

    prs = github.api(
        f"https://api.github.com/repos/{repository}/pulls?state=open&per_page={limit}",
        token,
        user_agent="AppLab-External-Review-Watchdog/5.9E",
    )
    rows: list[dict[str, Any]] = []
    for pr in prs[:limit]:
        if pr.get("draft") and not include_drafts:
            continue
        number = int(pr["number"])
        comments = github.api(
            f"https://api.github.com/repos/{repository}/issues/{number}/comments?per_page=100",
            token,
            user_agent="AppLab-External-Review-Watchdog/5.9E",
        )
        decision = support.decision_for_pr(
            pr=pr,
            comments=comments,
            now=now,
            timeout_seconds=timeout,
            max_retries=max_retries,
            review_bot_login=review_bot_login,
            watchdog_actor_login=watchdog_actor_login,
        )
        if decision["action"] == "REQUEST_REVIEW" and not dry_run:
            request_review(
                repository,
                number,
                decision["expected_head_sha"],
                decision["retry_count"] + 1,
                request_body,
                token,
            )
            decision["dispatch"] = "COMMENTED"
        else:
            decision["dispatch"] = "DRY_RUN" if dry_run else "NONE"
        rows.append(decision)

    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "record_type": "EXTERNAL_REVIEW_RECONCILIATION_V59E",
        "authority": "ORCHESTRATION_ONLY",
        "repository": repository,
        "dry_run": bool(dry_run),
        "reviewed_pr_count": len(rows),
        "retrigger_count": sum(
            1 for row in rows if row.get("dispatch") == "COMMENTED"
        ),
        "merge_authority_unchanged": True,
        "rows": rows,
    }


def self_test() -> None:
    support.self_test()
    print("AppLab v5.9E external review reconciler self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
    )
    parser.add_argument(
        "--config",
        default="config/external-review-watchdog.json",
    )
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

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if not config.get("enabled"):
        payload: dict[str, Any] = {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "record_type": "EXTERNAL_REVIEW_RECONCILIATION_V59E",
            "authority": "ORCHESTRATION_ONLY",
            "status": "DISABLED",
            "repository": args.repository,
            "dry_run": bool(args.dry_run),
            "reviewed_pr_count": 0,
            "retrigger_count": 0,
            "merge_authority_unchanged": True,
            "rows": [],
        }
    else:
        payload = reconcile(
            repository=args.repository,
            config=config,
            token=args.token,
            dry_run=args.dry_run,
            now=datetime.now(timezone.utc),
        )

    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
