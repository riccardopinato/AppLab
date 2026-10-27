# AppLab v6.1D — Controlled Multi-Repo Expansion

Status: **IMPLEMENTED CANDIDATE / PROMOTION HELD AT SELF_CANARY**

## Purpose

v6.1D adds the production control needed to expand the v6 closed loop beyond
AppLab without converting the old v5.5 rollout into implicit mutation authority.

The only authorized progression is:

```
SELF_CANARY -> PILOT_3 -> PILOT_5
```

`ALL_COMPATIBLE` is deliberately absent. Any later expansion beyond five
repositories requires a separate evidence-backed roadmap and policy decision.

## Cohort reuse without authority inheritance

v6.1D reuses the already-tested v5.5 cohort topology:

- SELF_CANARY: AppLab;
- PILOT_3: AppLab, CamperBoss, TrailPath;
- PILOT_5: PILOT_3 + Notes-Ecosistema + World-Days.

This reuses infrastructure knowledge only. v5.5 success does not grant v6.1
closed-loop mutation authority.

## Promotion gate

Promotion is never automatic and never edits the policy itself.

For every repository in the **current** stage, promotion requires real v6.1
closed-loop operation evidence meeting all of these thresholds:

- at least three successful closed-loop operations;
- zero failed closed-loop operations;
- zero authority breaches;
- zero false repairs;
- zero recovery failures;
- zero exact-identity violations.

Sufficient evidence returns only `ELIGIBLE_FOR_EXPLICIT_PROMOTION`. A separate
policy change is still required. Missing or bad evidence returns `HOLD`.

The repository policy intentionally remains at `SELF_CANARY` in this change.
Exact-head CI success for the implementation itself is not relabeled as three
closed-loop repair operations.

## Admission boundary

When a later explicit promotion activates a cohort, v6.1D admission:

- requires exact stage membership and `refs/heads/main`;
- applies global and per-repository kill switches;
- preserves exact source SHA;
- requires AppLab self source SHA to equal the AppLab engine SHA;
- keeps downstream source SHA and AppLab engine SHA distinct immutable identities;
- grants bounded mutation/draft-PR authority only for LOW/NORMAL risk;
- admits HIGH/SECURITY risk as investigation-only;
- reuses Durable Store, DurablePerRepoQueue, v6 Work Graph and v6.1C budgets;
- creates no live remote dispatcher.

The existing bounded fix worker remains branch-workspace mutation authority and
the draft-PR steward remains draft branch/PR authority. Main writes, self-merge,
release and certification are not granted.

## Waiting, recovery and fallback

v6.1B event-driven durable waiting and independent reconciliation remain the
primary progression model. v6.1C observation coalescing/backpressure remains in
force. GitHub Actions remains the execution fallback.

v6.1D does not add polling loops, schedulers or another queue.

## Current promotion state

**HOLD AT SELF_CANARY.**

The controller and PILOT_3/PILOT_5 materialization paths can be validated in CI,
but live stage promotion must wait for the required real v6.1 operation evidence.

## Acceptance criteria

- only SELF_CANARY/PILOT_3/PILOT_5 exist;
- v5.5 cohort topology is reused but v5.5 evidence grants no v6.1 mutation authority;
- promotion is explicit and evidence-gated;
- current live policy remains SELF_CANARY;
- downstream PILOT_3 admission is proven in non-dispatch contract tests;
- HIGH/SECURITY remain investigation-only;
- global/per-repository kill switches fail closed;
- AppLab self identity mismatch fails closed;
- Durable Store/Queue/Work Graph/v6.1C budget controls are reused;
- no remote dispatch or fixed polling loop is introduced;
- merge/release/verification/certification authority is unchanged.
