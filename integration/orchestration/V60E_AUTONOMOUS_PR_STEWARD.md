# AppLab v6.0E — Autonomous PR Steward

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

The steward consumes only a v6.0D decision `COMPLETE / VERIFIED_PASS / OPEN_DRAFT_PR` bound to the exact canonical v6.0C fix-result identity.

## Allowed remote actions

- create the deterministic `applab/repair/*` branch from the exact source SHA;
- apply the already-verified result patch;
- commit and push that repair branch;
- create a **draft** PR;
- update the title/body of its own existing **draft** PR;
- observe CI/review state and route fresh failures/findings back to v6.0B.

## Explicitly forbidden

- mark ready for review;
- self-approve;
- dismiss or resolve external findings unilaterally;
- merge/rebase main;
- release;
- edit branch protection or workflow policy.

A green PR remains `HUMAN_OR_INDEPENDENT_APPROVAL`.

## Identity gates

The WorkItem, v6.0C result, v6.0D decision and result-patch bytes must agree on repository, source SHA, WorkItem id and fix-result identity. The patch SHA-256 must match v6.0C before any remote write.

## Review reconciliation

- failed CI or unresolved findings -> `RUN_CAUSAL_INVESTIGATOR`;
- pending CI -> wait;
- green CI -> human/independent approval;
- suspected supersession -> require ancestry/equivalence review; the steward does not close the PR by itself.

## Acceptance

- [x] versioned draft-only contract;
- [x] exact fix identity binding;
- [x] result-patch hash gate;
- [x] repair-branch-only remote write;
- [x] draft create/update;
- [x] CI/review reconciliation to Investigator;
- [x] external findings never auto-resolved;
- [x] no ready/approve/merge/release authority;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] real bounded repair pilot creates a draft PR.
