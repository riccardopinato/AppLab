# AppLab v6.0D — Verify–Repair Loop

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

Close the bounded engineering loop without turning “keep trying until green”
into policy.

v6.0D consumes:

- v6.0A WorkItem authority/budgets;
- v6.0B causal investigation;
- v6.0C repair manifests;
- focused verification;
- existing AppLab verification evidence.

## Loop

```
deterministic failure
 -> investigate
 -> bounded repair
 -> focused verify
 -> AppLab FAST/FULL
 -> PASS / next bounded investigation / STOP
```

## Hard rules

- maximum repair attempts: 2;
- focused verification is required before AppLab verification;
- a trusted AppLab PASS is **observed**, never minted by the loop;
- PASS must bind the exact repair identity;
- UNKNOWN stops;
- infra/flaky uncertainty waits instead of triggering code edits;
- a materially changed failure class stops as unexplained mutation;
- the same failure signature after the second repair stops;
- a different deterministic failure after the second repair stops on budget;
- no third repair attempt exists.

## Failure signatures

The loop hashes:

- failure classification;
- sorted failed specialist labs;
- normalized reason/build-error text.

Volatile SHA-like and numeric values are normalized before hashing so line
numbers or run IDs do not make the same causal failure look different.

## Repair identity

The repair identity binds:

- repository;
- exact parent source SHA;
- WorkItem;
- repair attempt number;
- changed-line count;
- every repaired path;
- before/after hashes;
- created/existing state.

A PASS that does not carry the exact expected repair identity is
`IDENTITY_NOT_PROVEN`.

## Terminal outcomes

- VERIFIED_PASS;
- UNKNOWN_CLASSIFICATION;
- REPEATED_FAILURE_SIGNATURE;
- UNEXPLAINED_FAILURE_MUTATION;
- IDENTITY_NOT_PROVEN;
- BUDGET_EXHAUSTED;
- VERIFICATION_BLOCKED;
- human/security/protected-scope conditions inherited from the WorkItem.

## Successful next step

A verified repair ends with:

`COMPLETE -> OPEN_DRAFT_PR`

not merge or release.

## Acceptance

- [x] versioned loop contract;
- [x] deterministic failure signature;
- [x] exact repair identity;
- [x] focused-before-AppLab ordering;
- [x] AppLab PASS identity binding;
- [x] UNKNOWN fail closed;
- [x] infra/flaky wait path;
- [x] failure-mutation stop;
- [x] repeated-second-attempt stop;
- [x] hard two-attempt budget;
- [x] no PASS rewrite of prior failed attempts;
- [x] successful handoff only to draft PR stewardship;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] merged after v6.0C.

## Authority

The loop never:

- edits protected policy;
- changes Smart Test Plan authority;
- mints PASS/CERTIFIED;
- merges;
- releases.
