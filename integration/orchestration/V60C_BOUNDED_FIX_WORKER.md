# AppLab v6.0C — Bounded Autonomous Fix Worker

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

v6.0C is the first v6 step allowed to modify source code, but only inside an
isolated ephemeral Git worktree and only after v6.0B has produced deterministic
causal localization that is explicitly eligible for bounded repair.

The worker is not a general coding agent. It is a constrained patch executor.

## Required chain

```
exact failing/source SHA
  -> v6.0A WorkItem with ALLOW_CODE_EDIT
  -> v6.0B LOCALIZED + ELIGIBLE_FOR_BOUNDED_REPAIR
  -> bounded patch preflight
  -> ephemeral detached worktree
  -> local repair branch
  -> post-apply scope / test-integrity audit
  -> immutable result patch
  -> READY_FOR_VERIFICATION
```

No remote branch is pushed in v6.0C. Draft-PR stewardship belongs to v6.0E.

## Exact identity

Before editing, the worker requires the checked-out repository HEAD to equal:

- the WorkItem `resolved_sha`;
- the causal investigation `resolved_sha`.

A branch name is never accepted as the trust-sensitive identity.

## Scope

Allowed paths are derived only from:

- v6.0B ranked non-protected candidate files;
- paired tests returned by the investigator;
- regression targets that are explicit repository paths.

A patch outside that set fails closed.

## Budgets

The effective budget is the minimum of the WorkItem and worker contract:

- maximum files: **5**;
- maximum changed lines: **250**;
- maximum repair attempts: **2**.

The worker checks both the patch preflight statistics and the final applied
workspace paths.

## Protected surfaces

v1 rejects edits to, among other protected surfaces:

- GitHub workflows/actions;
- governance policy;
- orchestration contracts;
- `AGENTS.md`;
- Factory resolver/Master-like policy files;
- roadmap/product-bible authority files;
- key/keystore/environment-secret material.

Renames, file deletion patches and binary patches are also denied in v1.

## Test-integrity gate

A repair is rejected when the diff attempts to obtain green by weakening tests.

The bounded heuristic currently detects:

- adding common skip/disable markers;
- deleting more assertion/test coverage tokens than the same hunk adds.

Replacing an obsolete assertion with a new assertion remains allowed. New
regression-test files are preserved through `git add -N` so they appear in the
result patch without committing or pushing them.

This heuristic is an additional deny gate, not proof that a test change is
semantically correct. Exact-head verification remains mandatory.

## Workspace semantics

The worker creates a detached worktree at the exact source SHA and a local
repair branch named from that SHA and attempt number. It applies the candidate
patch there, audits the resulting diff and then deletes the worktree.

The source checkout is not modified.

The output may include an immutable normalized result patch for the next
verification stage.

## Output authority

`BOUNDED_FIX_RESULT_V60C` can say:

- `READY_FOR_VERIFICATION`;
- `NO_CHANGE`;
- blocked via fail-closed worker error.

It cannot say PASS or CERTIFIED.

It performs no:

- remote push;
- PR creation;
- merge;
- release;
- main write;
- Factory-Core write.

## Acceptance

- [x] versioned worker contract;
- [x] exact-SHA binding;
- [x] WorkItem capability enforcement;
- [x] v6.0B causal eligibility enforcement;
- [x] bounded candidate/regression path scope;
- [x] file and line budgets;
- [x] max repair-attempt budget;
- [x] protected path denial;
- [x] binary/rename/delete denial;
- [x] test skip/assertion-weakening denial;
- [x] new regression-test preservation;
- [x] ephemeral worktree isolation;
- [x] source checkout remains unchanged;
- [x] no remote/merge/release authority;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] merged after v6.0B.

## Next boundary

v6.0D owns the Verify–Repair Loop. It may consume a
`READY_FOR_VERIFICATION` result, run the required focused/AppLab verification,
and decide PASS / one further bounded repair attempt / STOP.

v6.0D must never convert “repair worker produced a patch” into trusted PASS.
