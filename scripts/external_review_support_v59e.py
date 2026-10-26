#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import external_review_watchdog_v59e as policy

STATE_RE = re.compile(r"codex-review-state:v1\s+(\{.*?\})\s*-->")
WATCHDOG_RE = re.compile(
    r"applab-review-watchdog:v1\s+head=([0-9a-f]{40})\s+attempt=(\d+)"
)


def iso_datetime(value: str) -> datetime:
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
        match = STATE_RE.search(str(item.get("body", "")))
        if not match:
            continue
        try:
            marker = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        code = marker.get("code_review")
        if not isinstance(code, dict):
            continue
        created = iso_datetime(
            str(item.get("updated_at") or item.get("created_at"))
        )
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
        match = WATCHDOG_RE.search(str(item.get("body", "")))
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
    retry_count = watchdog_retry_count(
        comments,
        head,
        watchdog_actor_login,
    )

    marker_times: list[str] = []
    for item in comments:
        body = str(item.get("body", ""))
        author = str((item.get("user") or {}).get("login", ""))
        trusted = (
            (author == review_bot_login and STATE_RE.search(body))
            or (
                author == watchdog_actor_login
                and WATCHDOG_RE.search(body)
            )
        )
        created = str(item.get("created_at") or "")
        if trusted and created:
            marker_times.append(created)
    anchor = (
        max(marker_times)
        if marker_times
        else str(pr.get("updated_at") or pr.get("created_at") or "")
    )

    elapsed = (
        max(0, int((now - iso_datetime(anchor)).total_seconds()))
        if anchor
        else timeout_seconds
    )
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


def self_test() -> None:
    head = "a" * 40
    pr = {
        "number": 1,
        "title": "demo",
        "draft": False,
        "head": {"sha": head},
        "created_at": "2026-10-26T19:00:00Z",
        "updated_at": "2026-10-26T19:00:00Z",
    }
    marker = {
        "code_review": {
            "commit_sha": head,
            "has_unresolved_findings": False,
            "status": "completed",
        }
    }
    comment = {
        "user": {"login": "chatgpt-codex-connector[bot]"},
        "created_at": "2026-10-26T19:05:00Z",
        "body": (
            "<!-- codex-review-state:v1 "
            + json.dumps(marker, separators=(",", ":"))
            + " -->"
        ),
    }
    report = decision_for_pr(
        pr=pr,
        comments=[comment],
        now=datetime(2026, 10, 26, 19, 10, tzinfo=timezone.utc),
        timeout_seconds=900,
        max_retries=2,
    )
    assert report["state"] == "SATISFIED"
    print("AppLab v5.9E external review support self-test PASS")

if __name__ == "__main__":
    self_test()
