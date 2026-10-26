#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import external_review_watchdog_v59e as policy

ENGINE_VERSION = "5.9E"
STATE_RE = re.compile(r"codex-review-state:v1\s+(\{.*?\})\s*-->")
WATCHDOG_RE = re.compile(
    r"applab-review-watchdog:v1\s+head=([0-9a-f]{40})\s+attempt=(\d+)"
)


def _api(url: str, token: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AppLab-External-Review-Watchdog/5.9E",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _iso(value: str) -> datetime:
    raw = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_codex_state(
    comments: list[dict[str, Any]],
    review_bot_login: str,
) -> dict[str, Any]:
    best: tuple[datetime, dict[str, Any]] | None = None
    for item in comments:
        author = str((item.get("user") or {}).get("login", ""))
        if author != review_bot_login:
            continue
        body = str(item.get("body", ""))
        match = STATE_RE.search(body)
        if not match:
            continue
        try:
            marker = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        code = marker.get("code_review")
        if not isinstance(code, dict):
            continue
        created = _iso(str(item.get("updated_at") or item.get("created_at")))
        if best is None or created >= best[0]:
            best = (created, code)
    return dict(best[1]) if best else {}


def watchdog_retry_count(
    comments: list[dict[str, Any]],
    head_sha: str,
    watchdog_actor_login: str,
) -> int:
    count = 0
    for item in comments:
        author = str((item.get("user") or {}).get("login", ""))
        if author != watchdog_actor_login:
            continue
        body = str(item.get("body", ""))
        match = WATCHDOG_RE.search(body)
        if match and match.group(1) == head_sha:
            count = max(count, int(match.group(2)))
    return count


def decision_for_pr(
    *,
    pr: dict[str, Any],
    comments: list[dict[str, Any]],
    now: datetime,
    timeout_seconds: int,
    max_retries: int,
    review_bot_login: str = "chatgpt-codex-connector[bot]",
    watchdog_actor_login: str = "github-actions[bot]",
) -> dict[str, Any]:
    head = str((pr.get("head") or {}).get("sha", "")).lower()
    review = parse_codex_state(comments, review_bot_login)
    observed = str(review.get("commit_sha") or "").lower()
    status = str(review.get("status") or "missing").lower()
    findings = bool(review.get("has_unresolved_findings"))
    retry_count = watchdog_retry_count(comments, head, watchdog_actor_login)

    anchor = str(pr.get("updated_at") or pr.get("created_at") or "")
    for item in comments:
        body = str(item.get("body", ""))
        if (
            (STATE_RE.search(body) or WATCHDOG_RE.search(body))
            and str(item.get("created_at") or "") > anchor
        ):
            anchor = str(item.get("created_at") or "")
    elapsed = max(0, int((now - _iso(anchor)).total_seconds())) if anchor else timeout_seconds

    report = policy.evaluate(
        expected_head_sha=head,
        review_head_sha=observed,
        review_status=status,
        has_unresolved_findings=findings,
        elapsed_seconds=elapsed,
        retry_count=retry_count,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    report.update(
        {
            "pull_request_number": int(pr.get("number", 0)),
            "draft": bool(pr.get("draft")),
            "title": str(pr.get("title", "")),
        }
    )
    return report


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
    _api(
        f"https://api.github.com/repos/{repository}/issues/{pr_number}/comments",
        token,
        method="POST",
        payload={"body": body},
    )


def self_test() -> None:
    now = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)
    head = "a" * 40
    pr = {
        "number": 12,
        "title": "demo",
        "draft": False,
        "head": {"sha": head},
        "created_at": "2026-10-26T19:00:00Z",
        "updated_at": "2026-10-26T19:00:00Z",
    }
    clean_comment = {
        "user": {"login": "chatgpt-codex-connector[bot]"},
        "created_at": "2026-10-26T19:55:00Z",
        "body": (
            '<!-- codex-review-state:v1 '
            + json.dumps(
                {
                    "code_review": {
                        "commit_sha": head,
                        "has_any_findings": False,
                        "has_unresolved_findings": False,
                        "status": "completed",
                    }
                },
                separators=(",", ":"),
            )
            + " -->"
        ),
    }
    clean = decision_for_pr(
        pr=pr,
        comments=[clean_comment],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert clean["state"] == "SATISFIED"

    stale_comment = {
        "created_at": "2026-10-26T19:55:00Z",
        "body": (
            '<!-- codex-review-state:v1 '
            + json.dumps(
                {
                    "code_review": {
                        "commit_sha": "b" * 40,
                        "has_any_findings": False,
                        "has_unresolved_findings": False,
                        "status": "completed",
                    }
                },
                separators=(",", ":"),
            )
            + " -->"
        ),
    }
    stale = decision_for_pr(
        pr=pr,
        comments=[stale_comment],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert stale["action"] == "REQUEST_REVIEW"

    timed = {
        "created_at": "2026-10-26T19:00:00Z",
        "body": (
            '<!-- codex-review-state:v1 '
            + json.dumps(
                {
                    "code_review": {
                        "commit_sha": head,
                        "has_any_findings": None,
                        "has_unresolved_findings": None,
                        "status": "running",
                    }
                },
                separators=(",", ":"),
            )
            + " -->"
        ),
    }
    retry = {
        "user": {"login": "github-actions[bot]"},
        "created_at": "2026-10-26T19:20:00Z",
        "body": (
            "@codex review\n<!-- applab-review-watchdog:v1 "
            f"head={head} attempt=1 -->"
        ),
    }
    timeout = decision_for_pr(
        pr=pr,
        comments=[timed, retry],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert timeout["state"] == "RETRIGGER"
    assert timeout["retry_count"] == 1

    findings = dict(clean_comment)
    findings["body"] = findings["body"].replace(
        '"has_unresolved_findings":false',
        '"has_unresolved_findings":true',
    )
    blocked = decision_for_pr(
        pr=pr,
        comments=[findings],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert blocked["state"] == "BLOCKED"
    assert blocked["action"] == "NONE"

    spoof = dict(clean_comment)
    spoof["user"] = {"login": "untrusted-user"}
    ignored = decision_for_pr(
        pr=pr,
        comments=[spoof],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert ignored["state"] == "RETRIGGER"
    assert ignored["reason"] == "REVIEW_MISSING"

    print("AppLab v5.9E external review reconciler self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--config", default="config/external-review-watchdog.json")
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
        print(json.dumps({"status": "DISABLED"}))
        return 0
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

    prs = _api(
        f"https://api.github.com/repos/{args.repository}/pulls?state=open&per_page={limit}",
        args.token,
    )
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for pr in prs[:limit]:
        if pr.get("draft") and not include_drafts:
            continue
        number = int(pr["number"])
        comments = _api(
            f"https://api.github.com/repos/{args.repository}/issues/{number}/comments?per_page=100",
            args.token,
        )
        decision = decision_for_pr(
            pr=pr,
            comments=comments,
            now=now,
            timeout_seconds=timeout,
            max_retries=max_retries,
            review_bot_login=review_bot_login,
            watchdog_actor_login=watchdog_actor_login,
        )
        if decision["action"] == "REQUEST_REVIEW" and not args.dry_run:
            request_review(
                args.repository,
                number,
                decision["expected_head_sha"],
                decision["retry_count"] + 1,
                request_body,
                args.token,
            )
            decision["dispatch"] = "COMMENTED"
        else:
            decision["dispatch"] = "DRY_RUN" if args.dry_run else "NONE"
        rows.append(decision)

    payload = {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "record_type": "EXTERNAL_REVIEW_RECONCILIATION_V59E",
        "authority": "ORCHESTRATION_ONLY",
        "repository": args.repository,
        "dry_run": bool(args.dry_run),
        "reviewed_pr_count": len(rows),
        "retrigger_count": sum(1 for row in rows if row.get("dispatch") == "COMMENTED"),
        "merge_authority_unchanged": True,
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
