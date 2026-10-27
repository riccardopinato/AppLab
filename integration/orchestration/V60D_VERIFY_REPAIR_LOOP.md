# AppLab v6.0D — Verify–Repair Loop

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Canonical input boundary

This implementation is rebuilt on the canonical v6.0C branch and accepts only:

`BOUNDED_FIX_RESULT_V60C / READY_FOR_VERIFICATION`.

The earlier v6.0D PR #163 was closed before merge because it depended on a
superseded Fix Worker lineage. No old repair-result contract is accepted here.

## Loop

```
deterministic failure
 -> causal investigation
 -> BOUNDED_FIX_RESULT_V60C
 -> focused verification
 -> AppLab FAST/FULL
 -> PASS | one further bounded investigation/repair | STOP
```

## Exact fix identity

The loop hashes the canonical v6.0C result fields:

- repository;
- exact parent source SHA;
- WorkItem id;
- attempt number;
- source patch hash;
- normalized result-patch hash;
- changed paths;
- additions/deletions/changed-line budget.

Focused verification and AppLab verification must both bind that exact identity.

## Terminal rules

- UNKNOWN -> STOP;
- infra/flaky -> WAIT_EXTERNAL;
- non-localized/ambiguous evidence -> investigate or human decision;
- unexplained failure-class mutation -> STOP;
- same normalized failure signature after repair #2 -> STOP;
- different deterministic failure after repair #2 -> BUDGET_EXHAUSTED;
- missing/mismatched fix identity -> STOP;
- no third repair attempt.

A failed attempt is never rewritten as PASS.

## Success

Only an already authoritative AppLab PASS bound to the exact fix result produces:

`COMPLETE -> OPEN_DRAFT_PR`.

The loop itself cannot mint PASS/CERTIFIED and cannot merge or release.

## Acceptance

- [x] canonical v6.0C result binding;
- [x] focused-before-AppLab ordering;
- [x] exact fix-result identity;
- [x] deterministic normalized failure signature;
- [x] UNKNOWN fail-closed;
- [x] infra/flaky wait path;
- [x] repeated second-attempt stop;
- [x] unexplained mutation stop;
- [x] hard two-attempt budget;
- [x] superseded v6.0C result rejection;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] merged after canonical v6.0C.
