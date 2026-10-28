# AppLab External Review Watchdog — HTTP 403 incident

Recorded: 2026-10-28. Evidence: https://github.com/riccardopinato/AppLab/actions/runs/40621939259

## Observation

The scheduled v5.9E External Review Watchdog ran with reported
`issues: write`, `pull-requests: read`, and `contents: read`.
Contract self-tests passed. The live `POST /issues/{number}/comments`
for a review retrigger failed with `urllib.error.HTTPError: HTTP Error 403`.
The job exited before writing its output artifact.
The exact GitHub authorization/policy reason has not been established.

This patch does **not** claim to resolve repository/installation permissions.
It preserves a per-PR `BLOCKED / REVIEW_REQUEST_PERMISSION_DENIED` decision
and `review_request_http_status=403`, writes the JSON report artifact,
then still fails the scheduled job. It never counts a denied request as
`COMMENTED`, never fabricates an independent review receipt, and never
acquires merge/release authority.

## Operator remediation

Use a permitted GitHub user or connected app to post `@codex review` on
the exact PR head; check the resulting independent Codex review *completes*.
Investigate Actions installation/org policy and the comment endpoint 403
before claiming automated review recovery is operational. Do not add a
broader PAT or elevate secrets automatically. Maintain SELF_CANARY.

## Gate

Exact-head CI + independent review of this watchdog patch, followed by
one real scheduled run with an artifact showing the actual outcome.
A `BLOCKED_REVIEW_REQUEST` report is a diagnosed incident, **not** a fix.
