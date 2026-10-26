#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

ENGINE_VERSION = "5.9E"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VALID_STATUS = {"missing", "running", "completed", "failed"}


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise ValueError(f"{label} must be a 40-character commit SHA")
    return text


def evaluate(
    *,
    expected_head_sha: str,
    review_head_sha: str,
    review_status: str,
    has_unresolved_findings: bool,
    elapsed_seconds: int,
    retry_count: int,
    timeout_seconds: int = 900,
    max_retries: int = 2,
) -> dict[str, Any]:
    expected = _sha(expected_head_sha, "expected_head_sha")
    observed = str(review_head_sha or "").strip().lower()
    status = str(review_status or "missing").strip().lower()
    if status not in VALID_STATUS:
        raise ValueError(f"unsupported review status: {status}")
    if observed and not SHA_RE.fullmatch(observed):
        raise ValueError("review_head_sha must be empty or a 40-character commit SHA")
    if elapsed_seconds < 0 or retry_count < 0:
        raise ValueError("elapsed_seconds and retry_count must be non-negative")
    if timeout_seconds < 1 or max_retries < 0:
        raise ValueError("timeout_seconds must be positive and max_retries non-negative")

    exact_head = observed == expected
    can_retry = retry_count < max_retries
    action = "NONE"
    state = "WAIT"
    reason = "REVIEW_IN_PROGRESS"

    if status == "completed" and exact_head and not has_unresolved_findings:
        state = "SATISFIED"
        reason = "EXACT_HEAD_REVIEW_CLEAN"
    elif status == "completed" and exact_head and has_unresolved_findings:
        state = "BLOCKED"
        reason = "EXACT_HEAD_REVIEW_HAS_FINDINGS"
    elif status == "completed" and not exact_head:
        if can_retry:
            state, action, reason = "RETRIGGER", "REQUEST_REVIEW", "STALE_COMPLETED_REVIEW"
        else:
            state, reason = "BLOCKED", "STALE_REVIEW_RETRY_EXHAUSTED"
    elif status == "running" and not exact_head:
        if can_retry:
            state, action, reason = "RETRIGGER", "REQUEST_REVIEW", "STALE_RUNNING_REVIEW"
        else:
            state, reason = "BLOCKED", "STALE_REVIEW_RETRY_EXHAUSTED"
    elif status == "running" and elapsed_seconds >= timeout_seconds:
        if can_retry:
            state, action, reason = "RETRIGGER", "REQUEST_REVIEW", "REVIEW_TIMEOUT"
        else:
            state, reason = "BLOCKED", "REVIEW_TIMEOUT_RETRY_EXHAUSTED"
    elif status == "failed":
        if can_retry:
            state, action, reason = "RETRIGGER", "REQUEST_REVIEW", "REVIEW_FAILED"
        else:
            state, reason = "BLOCKED", "REVIEW_FAILED_RETRY_EXHAUSTED"
    elif status == "missing":
        if can_retry:
            state, action, reason = "RETRIGGER", "REQUEST_REVIEW", "REVIEW_MISSING"
        else:
            state, reason = "BLOCKED", "REVIEW_MISSING_RETRY_EXHAUSTED"

    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "record_type": "EXTERNAL_REVIEW_WATCHDOG_V59E",
        "authority": "ORCHESTRATION_ONLY",
        "state": state,
        "action": action,
        "reason": reason,
        "expected_head_sha": expected,
        "review_head_sha": observed,
        "exact_head": exact_head,
        "review_status": status,
        "has_unresolved_findings": bool(has_unresolved_findings),
        "elapsed_seconds": int(elapsed_seconds),
        "timeout_seconds": int(timeout_seconds),
        "retry_count": int(retry_count),
        "max_retries": int(max_retries),
        "merge_authority_unchanged": True,
        "review_findings_never_auto_resolved": True,
        "retrigger_is_idempotent_request_only": True,
    }


def self_test() -> None:
    head = "a" * 40
    clean = evaluate(
        expected_head_sha=head,
        review_head_sha=head,
        review_status="completed",
        has_unresolved_findings=False,
        elapsed_seconds=120,
        retry_count=0,
    )
    assert clean["state"] == "SATISFIED"
    assert clean["action"] == "NONE"

    findings = evaluate(
        expected_head_sha=head,
        review_head_sha=head,
        review_status="completed",
        has_unresolved_findings=True,
        elapsed_seconds=120,
        retry_count=0,
    )
    assert findings["state"] == "BLOCKED"
    assert findings["action"] == "NONE"

    stale = evaluate(
        expected_head_sha=head,
        review_head_sha="b" * 40,
        review_status="completed",
        has_unresolved_findings=False,
        elapsed_seconds=60,
        retry_count=0,
    )
    assert stale["state"] == "RETRIGGER"
    assert stale["reason"] == "STALE_COMPLETED_REVIEW"

    timed_out = evaluate(
        expected_head_sha=head,
        review_head_sha=head,
        review_status="running",
        has_unresolved_findings=False,
        elapsed_seconds=901,
        retry_count=1,
    )
    assert timed_out["state"] == "RETRIGGER"
    assert timed_out["reason"] == "REVIEW_TIMEOUT"

    failed = evaluate(
        expected_head_sha=head,
        review_head_sha=head,
        review_status="failed",
        has_unresolved_findings=True,
        elapsed_seconds=0,
        retry_count=0,
    )
    assert failed["state"] == "RETRIGGER"
    assert failed["reason"] == "REVIEW_FAILED"
    assert failed["action"] == "REQUEST_REVIEW"

    exhausted = evaluate(
        expected_head_sha=head,
        review_head_sha="",
        review_status="missing",
        has_unresolved_findings=False,
        elapsed_seconds=0,
        retry_count=2,
    )
    assert exhausted["state"] == "BLOCKED"
    assert exhausted["action"] == "NONE"

    print("AppLab v5.9E external review watchdog self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head-sha", default="")
    parser.add_argument("--review-head-sha", default="")
    parser.add_argument("--review-status", default="missing")
    parser.add_argument("--has-unresolved-findings", action="store_true")
    parser.add_argument("--elapsed-seconds", type=int, default=0)
    parser.add_argument("--retry-count", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    report = evaluate(
        expected_head_sha=args.expected_head_sha,
        review_head_sha=args.review_head_sha,
        review_status=args.review_status,
        has_unresolved_findings=args.has_unresolved_findings,
        elapsed_seconds=args.elapsed_seconds,
        retry_count=args.retry_count,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
