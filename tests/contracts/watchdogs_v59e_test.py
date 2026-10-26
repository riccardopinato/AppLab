#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import external_review_reconcile_v59e as reconcile  # noqa: E402
import external_review_support_v59e as review  # noqa: E402
import supersession_watchdog_v59e as supersession  # noqa: E402
import watchdog_github_v59e as github  # noqa: E402


def review_comment(
    head: str,
    *,
    sha: str | None = None,
    status: str = "completed",
    findings: bool = False,
    actor: str = "chatgpt-codex-connector[bot]",
    created: str = "2026-10-26T19:00:00Z",
) -> dict:
    marker = {
        "code_review": {
            "commit_sha": sha or head,
            "has_any_findings": findings,
            "has_unresolved_findings": findings,
            "status": status,
        }
    }
    return {
        "user": {"login": actor},
        "created_at": created,
        "body": (
            "<!-- codex-review-state:v1 "
            + json.dumps(marker, separators=(",", ":"))
            + " -->"
        ),
    }


def test_review_watchdog() -> None:
    now = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)
    head = "a" * 40
    pr = {
        "number": 12,
        "title": "demo",
        "draft": False,
        "head": {"sha": head},
        "created_at": "2026-10-26T18:00:00Z",
        "updated_at": "2026-10-26T19:59:30Z",
    }

    clean = review.decision_for_pr(
        pr=pr,
        comments=[review_comment(head, created="2026-10-26T19:55:00Z")],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert clean["state"] == "SATISFIED"

    stale = review.decision_for_pr(
        pr=pr,
        comments=[review_comment(head, sha="b" * 40)],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert stale["state"] == "RETRIGGER"
    assert stale["reason"] == "STALE_COMPLETED_REVIEW"

    running = review.decision_for_pr(
        pr=pr,
        comments=[
            review_comment(
                head,
                status="running",
                created="2026-10-26T19:00:00Z",
            )
        ],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert running["state"] == "RETRIGGER"
    assert running["reason"] == "REVIEW_TIMEOUT"

    spoof = review.decision_for_pr(
        pr=pr,
        comments=[review_comment(head, actor="untrusted-user")],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert spoof["state"] == "RETRIGGER"
    assert spoof["reason"] == "REVIEW_MISSING"

    retry = {
        "user": {"login": "github-actions[bot]"},
        "created_at": "2026-10-26T19:20:00Z",
        "body": (
            "@codex review\n"
            f"<!-- applab-review-watchdog:v1 head={head} attempt=1 -->"
        ),
    }
    timed = review.decision_for_pr(
        pr=pr,
        comments=[
            review_comment(
                head,
                status="running",
                created="2026-10-26T19:00:00Z",
            ),
            retry,
        ],
        now=now,
        timeout_seconds=900,
        max_retries=2,
    )
    assert timed["retry_count"] == 1


def test_supersession_identity() -> None:
    push = {
        "name": "Controlled Event-Driven Pilot",
        "head_branch": "main",
        "event": "push",
        "status": "in_progress",
        "repository": {"full_name": "owner/app"},
    }
    old = {
        **push,
        "id": 1,
        "run_number": 10,
        "created_at": "2026-10-26T20:00:00Z",
        "head_sha": "a" * 40,
    }
    new = {
        **push,
        "id": 2,
        "run_number": 11,
        "created_at": "2026-10-26T20:05:00Z",
        "head_sha": "b" * 40,
    }
    candidates = supersession.plan_candidates(
        [old, new],
        workflow_names={"Controlled Event-Driven Pilot"},
        allowed_events={"push"},
    )
    assert len(candidates) == 1
    assert supersession.evaluate_candidate(
        old=old,
        new=new,
        ancestry_proven=True,
        ancestry_status="ahead",
    )["decision"] == "CANCEL"
    assert supersession.evaluate_candidate(
        old=old,
        new=new,
        ancestry_proven=False,
        ancestry_status="diverged",
    )["decision"] == "KEEP"

    pr_base = {
        "name": "AppLab True Autonomous App Review v5.3.5",
        "head_branch": "feature",
        "event": "pull_request",
        "status": "in_progress",
        "repository": {"full_name": "owner/app"},
    }
    fork_old = {
        **pr_base,
        "id": 3,
        "run_number": 20,
        "created_at": "2026-10-26T20:00:00Z",
        "head_sha": "c" * 40,
        "head_repository": {"full_name": "fork-one/app"},
        "pull_requests": [
            {
                "number": 10,
                "head": {"repo": {"full_name": "fork-one/app"}},
            }
        ],
    }
    fork_new = {
        **pr_base,
        "id": 4,
        "run_number": 21,
        "created_at": "2026-10-26T20:05:00Z",
        "head_sha": "d" * 40,
        "head_repository": {"full_name": "fork-two/app"},
        "pull_requests": [
            {
                "number": 11,
                "head": {"repo": {"full_name": "fork-two/app"}},
            }
        ],
    }
    assert supersession.plan_candidates(
        [fork_old, fork_new],
        workflow_names={"AppLab True Autonomous App Review v5.3.5"},
        allowed_events={"pull_request"},
    ) == []

    unknown = dict(fork_old)
    unknown["pull_requests"] = []
    assert supersession.group_key(unknown) is None


def test_comment_pagination() -> None:
    original = github.api
    calls: list[str] = []

    def fake(url: str, token: str, **kwargs):
        calls.append(url)
        if "&page=1" in url:
            return [{"id": index} for index in range(100)]
        if "&page=2" in url:
            return [{"id": 100}]
        raise AssertionError(url)

    github.api = fake
    try:
        rows = github.paginated_list(
            "https://api.github.com/repos/owner/app/issues/1/comments",
            "",
            max_pages=3,
        )
    finally:
        github.api = original
    assert len(rows) == 101
    assert len(calls) == 2

    github.api = lambda *args, **kwargs: [{"id": 1}] * 100
    try:
        try:
            github.paginated_list(
                "https://api.github.com/repos/owner/app/issues/1/comments",
                "",
                max_pages=2,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("pagination cap must fail closed")
    finally:
        github.api = original


def test_bounded_pr_rotation() -> None:
    rows = [{"number": number} for number in range(1, 26)]
    seen: set[int] = set()
    for slot in range(25):
        selected = reconcile.bounded_rotation(
            rows,
            limit=20,
            now=datetime.fromtimestamp(slot, tz=timezone.utc),
            rotation_seconds=1,
        )
        assert len(selected) == 20
        seen.update(int(item["number"]) for item in selected)
    assert seen == set(range(1, 26))


def main() -> int:
    test_review_watchdog()
    test_supersession_identity()
    test_comment_pagination()
    test_bounded_pr_rotation()
    print("AppLab v5.9E watchdog regression contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
