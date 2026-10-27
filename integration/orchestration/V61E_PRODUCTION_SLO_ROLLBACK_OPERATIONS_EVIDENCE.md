# AppLab v6.1E — Production SLO, Rollback & Operations Evidence

Status: **LANDED / EXACT-HEAD VALIDATED via PR #197 (2cfb3fc); LIVE OPERATIONAL EVIDENCE PENDING**

## Purpose

v6.1E closes the v6.1 productionization program with a read-only evidence layer.
It observes the closed loop without becoming verification, merge, release or
certification authority.

The evidence model keeps three questions separate:

1. **Is the closed loop operationally healthy?**
2. **Is v6.1D promotion evidence sufficient?**
3. **Should operators hold or roll back the active cohort?**

None of those answers mutates the live policy automatically.

## Evidence identity

Every operation evidence record is bound to:

- repository;
- source ref;
- immutable source SHA;
- immutable AppLab engine SHA;
- operation ID;
- WorkItem ID;
- v6.1D stage.

AppLab self evidence requires source SHA == AppLab SHA. Downstream repositories
keep source SHA and AppLab engine SHA distinct.

Replayed evidence is idempotent by operation ID. Identical redelivery is counted
once; a conflicting payload for the same immutable operation identity is
rejected instead of being merged or counted again.

## SLOs and latency truth

v6.1E reports p50/p95 independently for:

- commit-to-green;
- queue wait;
- AppLab orchestration overhead;
- GitHub execution time;
- repair runtime.

The initial p95 values in the contract are **operations alert targets only**.
They do not mint PASS/CERTIFIED and are not verification authority.

A repository needs at least three measured samples for a specific latency metric
before that metric's alert target is evaluated. Missing duration fields remain
missing: they are not converted to zero and do not count toward the sample
threshold. Fewer measured samples remain INSUFFICIENT_SAMPLES.

This explicitly prevents GitHub execution time from being misreported as AppLab
orchestration overhead.

## Repair and safety evidence

Per repository, v6.1E tracks:

- successful closed-loop operations;
- failed closed-loop operations;
- stopped operations;
- repeated-failure-signature STOPs;
- authority breaches;
- false repairs;
- recovery failures;
- exact-identity violations;
- rollback attempts/successes/failures.

A repeated-signature STOP is a safety stop, not a successful repair. It is
reported separately and blocks the v6.1E operations promotion recommendation.

## Event/reconciliation efficiency

The report separately counts:

- event observations;
- reconciliation recoveries;
- fallback observation batches;
- covered waits;
- external queries;
- coalesced wait savings.

This preserves the v6.1B/v6.1C design: events are primary, reconciliation is
independent recovery, and bounded fallback observation remains secondary.

## Promotion

v6.1E feeds its repository evidence into the existing v6.1D
promotion_decision() contract.

Two outputs are deliberately distinct:

- promotion: the raw v6.1D evidence gate;
- operations_gate: the read-only v6.1E operational recommendation.

Even when both say ELIGIBLE_FOR_EXPLICIT_PROMOTION, policy_changed=false.
A separate policy change is still mandatory.

The operations gate remains HOLD when there is:

- a rollback signal;
- an SLO alert;
- a repeated-signature STOP;
- a rollback failure.

## Rollback

Rollback is recommendation-only.

Failure, false repair or recovery failure recommends repository isolation.
Authority breach or exact-identity violation recommends the global kill switch.
For PILOT_3/PILOT_5, the report recommends the previous stage. At SELF_CANARY,
it recommends HOLD SELF_CANARY.

The report never edits v61d-expansion.json, kill switches, branch protection,
workflow files or release state.

## Operations Studio

The existing Agentic Operations Studio remains a read-only projection. v6.1E
adds the latest production-operations summary to that projection so operators
can see:

- production status;
- active stage;
- promotion/operations-gate state;
- rollback recommendation;
- latency alert count;
- repeated-signature STOP count;
- observation efficiency.

The WorkItem authority envelope remains visible and no control action is added.

## Acceptance criteria

- commit-to-green, queue, orchestration, GitHub execution and repair runtime
  p50/p95 are independently reported;
- latency alerts are monitoring-only and require enough samples;
- repair success/failure and repeated-signature STOPs are separated;
- rollback attempts and failures are explicit;
- false repair, authority breach, recovery failure and identity violation
  produce fail-closed rollback recommendations;
- event/reconciliation/fallback/coalescing efficiency is inspectable;
- raw v6.1D promotion and v6.1E operations recommendation are separate;
- no policy/stage/kill-switch mutation occurs;
- Operations Studio remains read-only;
- PASS/CERTIFIED, merge, release and certification authority remain unchanged;
- exact-head CI/review gates must be green before landing.
