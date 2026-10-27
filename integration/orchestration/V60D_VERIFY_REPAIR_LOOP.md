# AppLab v6.0D — Trusted Verify–Repair Loop

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

v6.0D coordinates a bounded repair chain without creating a second verification
authority and without pretending that modified local bytes are still represented
by the original Git SHA.

The loop consumes v6.0A WorkItems, v6.0B investigations, v6.0C repair results,
focused verification, materialization evidence and existing trusted AppLab
runtime evidence.

## Canonical chain

```
original exact SHA / WorkItem
  -> causal investigation
  -> bounded patch
  -> focused verification
  -> materialize exact repaired commit
  -> trusted AppLab verification
       -> PASS
       -> deterministic FAIL -> new WorkItem on repaired SHA
       -> UNKNOWN / mutation / budget / trust loss -> STOP
```

A second repair is therefore **not** performed while claiming the original SHA.
It starts from a new WorkItem whose exact source SHA equals the prior
materialized repaired commit.

## Attempt budget

Maximum repair attempts: **2**.

Attempt two must:
- use a new WorkItem identity;
- use the exact materialized SHA from attempt one as its source;
- carry its own v6.0B causal investigation;
- produce a new v6.0C repair identity.

There is no third repair attempt.

## Repair identity

The loop hashes the v6.0C repair result over:
- repository;
- exact source SHA;
- WorkItem ID;
- chain attempt number;
- input/result patch hashes;
- changed paths;
- additions/deletions/changed-line count.

Focused verification must explicitly bind this repair identity.

## Materialization boundary

A focused PASS is not enough to run trusted AppLab verification against the
original source SHA.

The repair must first be materialized into an exact Git commit with:
- repository;
- parent SHA equal to the repair WorkItem source SHA;
- repaired source SHA;
- repair identity;
- exact result-patch hash.

v6.0E will own remote draft-branch materialization and PR stewardship. v6.0D
already models that boundary so trusted runtime can only observe a real exact
source identity.

## Trusted AppLab evidence

A result string is never accepted by itself.

The loop requires validated trusted-manifest metadata:
- `trusted=true`;
- producer `trusted-apk-verifier`;
- manifest SHA-256;
- non-empty evidence-file count;
- repository binding;
- resolved-SHA binding to the exact repaired commit.

The AppLab verification result must carry the same repository and repaired SHA.

The loop **observes** trusted PASS; it never mints PASS or CERTIFIED.

## Failure semantics

- UNKNOWN -> STOP;
- infrastructure/flaky -> WAIT_EXTERNAL, no code repair;
- deterministic failure after attempt one -> new investigation on the repaired SHA;
- failure-class mutation -> STOP;
- same normalized failure signature after attempt two -> STOP;
- different same-class failure after attempt two -> budget exhausted;
- untrusted/mismatched runtime evidence -> STOP;
- focused verification failure in v1 -> STOP for human/deeper investigation
  rather than inventing a remote source identity that never existed.

Failure signatures normalize volatile SHA-like and numeric values before hashing.

## Authority

v6.0D:
- does not edit code;
- does not push;
- does not merge;
- does not release;
- does not approve;
- does not change Smart Test Plan authority;
- does not replace Production Certification.

## Acceptance

- [x] versioned contract;
- [x] max-two-attempt chain;
- [x] exact root WorkItem identity;
- [x] second attempt requires a new WorkItem on prior repaired SHA;
- [x] v6.0C repair-result identity;
- [x] focused verification identity binding;
- [x] exact materialization boundary;
- [x] trusted-manifest metadata requirement;
- [x] exact AppLab repository/SHA binding;
- [x] UNKNOWN/infra/flaky fail-closed semantics;
- [x] failure-mutation stop;
- [x] repeated-signature stop;
- [x] hard budget exhaustion;
- [x] no PASS/CERTIFIED authority;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] merged after v6.0C.

## Next dependency

v6.0E implements the draft-branch/PR stewardship side of
`MATERIALIZE_DRAFT_BRANCH`. Until that executor exists, the v6.0D state machine
correctly stops at `NEEDS_MATERIALIZATION` after a focused local PASS.
