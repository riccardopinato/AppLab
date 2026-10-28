#!/usr/bin/env python3
"""v6.2 review-request transport and permission-safe observation."""
from __future__ import annotations

import urllib.error
from typing import Any, Callable

import watchdog_github_v59e as github


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


def attempt_request(send: Callable[[], None]) -> dict[str, Any]:
    """A 403 never becomes COMMENTED, SATISFIED, or a synthetic approval."""
    try:
        send()
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        exc.close()
        return {
            "state": "BLOCKED",
            "reason": (
                "REVIEW_REQUEST_PERMISSION_DENIED"
                if status in {401, 403}
                else "REVIEW_REQUEST_HTTP_FAILED"
            ),
            "dispatch": "BLOCKED",
            "review_request_http_status": status,
            "operator_action_required": True,
        }
    return {"dispatch": "COMMENTED"}
