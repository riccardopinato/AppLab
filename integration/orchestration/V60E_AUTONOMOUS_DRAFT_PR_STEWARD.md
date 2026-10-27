# AppLab v6.0E — Autonomous Draft PR Steward

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

v6.0E materializes an already-authorized v6.0C repair into a real Git commit and
keeps one draft repair PR moving without acquiring merge/release authority.

Code-edit permission and GitHub-write permission are deliberately separate.

`allow_code_edit=true` does **not** grant PR authority. A WorkItem must also
receive the explicit `allow_draft_pr_steward` capability grant, which adds:

- `CREATE_DRAFT_PR`;
- `UPDATE_DRAFT_PR`.

## Materialization

The steward requires:

- exact repository HEAD == WorkItem `resolved_sha`;
- WorkItem-bound `BOUNDED_FIX_RESULT_V60C`;
- exact result-patch SHA-256;
- chain attempt 1 or 2;
- stable root WorkItem identity;
- valid target base branch.

It creates an ephemeral worktree, reapplies the exact result patch, stages it and
requires the staged diff SHA-256 to equal the v6.0C result-patch hash.

Only then does it create a commit.

The materialization record exposes:

- parent SHA;
- exact repaired commit SHA;
- repair identity;
- exact patch hash;
- repair branch;
- PR base.

This record is the v6.0D `MATERIALIZE_DRAFT_BRANCH` boundary.

## Repair branch

The remote branch is deterministic and namespaced:

`applab/repair/<root-work-item>-<root-sha-prefix>`

The steward never pushes to the base branch.

Attempt 1:
- remote repair branch must be absent;
- or, on idempotent recovery, already equal the exact repaired SHA.

Attempt 2:
- remote repair branch must equal the current WorkItem source SHA;
- the new repair commit must be a fast-forward child;
- force push is never used.

Any other remote head blocks the operation.

## Draft PR rules

For attempt 1:
- create a draft PR when none exists;
- if an identical draft PR already exists after an interrupted request, reuse it.

For attempt 2:
- the branch fast-forward automatically updates the existing draft PR.

An existing repair PR must:
- still be draft;
- have the expected base;
- have the expected repair branch as head.

The steward never:
- marks a PR ready;
- approves;
- dismisses review findings as resolved;
- merges;
- releases.

## Credential boundary

The script does not read or print token values.

Remote execution relies on the Git credential / GitHub CLI credential already
provided by the trusted execution environment. The credential is an opaque
transport capability; `READ_SECRETS` remains denied.

## Recovery

The remote path is idempotent around the two interruption points that matter:

- push succeeded, PR creation did not: rerun sees remote head == repaired SHA and
  creates the missing draft PR;
- draft PR creation succeeded but response was lost: rerun sees the exact remote
  head plus matching draft PR and reuses it.

Unexpected branch divergence fails closed.

## Validation

The contract tests exercise a real local v6.0C → v6.0E chain:

- v6.0C produces the canonical result patch;
- v6.0E reapplies those exact bytes;
- staged diff identity must match;
- repaired commit parent must be the exact source SHA;
- source checkout and temporary local branch remain clean afterward.

Remote decision tests cover:
- first draft create;
- idempotent recovery;
- second-attempt fast-forward;
- non-draft rejection;
- base mismatch rejection;
- divergent remote rejection.

## Authority

v6.0E may write only the repair branch and draft PR metadata under an explicitly
authorized WorkItem.

It cannot mint PASS/CERTIFIED. Trusted runtime remains v6.0D/AppLab evidence.
