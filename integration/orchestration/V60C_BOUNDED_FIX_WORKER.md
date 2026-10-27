# AppLab v6.0C — Bounded Autonomous Fix Worker

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

Apply a repair only when v6.0A authority and v6.0B causal evidence make the
blast radius explicit and bounded.

The worker is deliberately not a generic shell executor.

## Entry requirements

All are mandatory:

- exact WorkItem source SHA;
- clean Git workspace;
- branch name beginning with `applab-repair/`;
- WorkItem grants `ALLOW_CODE_EDIT`;
- WorkItem risk is not SECURITY;
- v6.0B state is `LOCALIZED`;
- v6.0B recommendation is `ELIGIBLE_FOR_BOUNDED_REPAIR`;
- edit path is a sufficiently confident investigator candidate, or a required
  regression-test path.

## Patch model

The worker accepts structured exact-match text replacements:

```
path
before_sha256
old
new
expected_occurrences
```

No arbitrary shell command is accepted from the patch plan.

New files are allowed only when they are required regression-test targets.

## Hard bounds

The effective budget is the minimum of contract and WorkItem limits:

- files <= 5;
- changed lines <= 250;
- repair attempts <= 2.

## Protected scope

Denied by default:

- `.github/workflows/**`;
- `.github/actions/**`;
- `integration/orchestration/contracts/**`;
- `AGENTS.md`;
- `ROADMAP.md`;
- `CURRENT.yaml`;
- `.github/CODEOWNERS`.

v6.0B may localize a protected path, but v6.0C will not edit it.

## Test-strength guard

For existing test files:

- assertion-signal count may not decrease;
- skip/disable-signal count may not increase.

A newly created regression test must contain an assertion signal.

This does not prove semantic test quality; it prevents the most direct
green-by-weakening behavior and keeps final verification authoritative.

## Atomicity

All files are validated before the first write.

On write-set failure:

- previously written existing files are restored;
- newly created files are removed.

After apply, Git status must contain exactly the bounded repair paths.

## Output

The worker emits a repair manifest with:

- exact source SHA;
- isolated branch;
- attempt number;
- file hashes before/after;
- changed-line count;
- dry-run/applied state;
- explicit `commit_performed=false`;
- explicit `push_performed=false`;
- explicit `merge_performed=false`;
- explicit `release_performed=false`.

Commit/push responsibility belongs to the later PR Steward after v6.0D
verification.

## Acceptance

- [x] exact SHA gate;
- [x] isolated branch gate;
- [x] clean workspace gate;
- [x] candidate-file proof;
- [x] confidence threshold;
- [x] WorkItem ALLOW_CODE_EDIT gate;
- [x] SECURITY denial;
- [x] protected-path denial;
- [x] before-hash validation;
- [x] file/line/attempt budgets;
- [x] regression-test-only new file rule;
- [x] test weakening/skip guard;
- [x] validate-all-before-write;
- [x] rollback on apply failure;
- [x] bounded Git-status postcondition;
- [x] no commit/push/merge/release;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] merged after v6.0B.
