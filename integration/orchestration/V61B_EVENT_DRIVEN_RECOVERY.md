# AppLab v6.1B — Durable Event-Driven Recovery & Supersession

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Purpose

v6.1B turns external CI waiting into durable control-plane state. It directly addresses the repeated `check -> sleep 20/25/30 seconds -> check again` pattern observed during AppLab work.

The primary progression model is now:

`GitHub state change -> normalized observation -> durable wait projection -> next WorkItem transition`.

A fixed polling loop is not the primary mechanism.

## Durable wait

Each external wait binds:

- one WorkItem;
- one durable operation;
- one repository;
- one immutable target SHA;
- one exact set of required gates;
- a persisted per-gate state;
- a bounded fallback-observation budget.

The target SHA and required gate set are immutable. A new SHA cannot silently replace the current target.

Gate state is normalized to `PENDING`, `SUCCESS` or `FAILURE`. Reaching terminal states for all gates moves the wait to `READY_FOR_EVALUATION`; it does **not** mint PASS or CERTIFIED. Existing verification logic remains authoritative.

## Event-driven progression

An external observation updates only the named gate. Duplicate event delivery is idempotent. Conflicting reuse of the same event ID is rejected.

While at least one required gate is pending, the WorkItem and durable operation remain in `WAITING_EXTERNAL`. When all required gates are terminal they return to `VERIFYING` / `RUNNING` so the existing verification layer can interpret the results.

No network client and no `sleep` loop exists in the v6.1B primitive.

## Reconciliation fallback

Reconciliation is independent recovery, not the primary scheduler.

Before the fallback deadline the action is `WAIT_EVENT`. If GitHub Actions is unavailable the action is `HOLD_DURABLE_WAIT`. Only after the deadline may reconciliation emit `POLL_PENDING_GATES`, and that directive contains only the still-pending gate names plus the immutable SHA.

Fallback polling is bounded to three observations at 120-second intervals in the initial contract. Exhaustion becomes `FALLBACK_EXHAUSTED_HOLD / WATCHDOG_REQUIRED`; it never becomes an infinite retry loop.

## Recovery matrix

v6.1B covers the v6 closed-loop equivalents of the existing v5.5 recovery matrix:

- duplicate delivery -> event replay/dedupe;
- event loss -> bounded reconciliation of pending gates;
- Actions outage -> durable hold;
- coordinator restart -> reopen the same wait projection;
- interrupted external wait -> persisted gate state and fallback budget survive;
- superseding SHA -> explicit supersession;
- watcher recovery -> may feed the same normalized observation path;
- terminal WorkItems/operations -> preserved, never redispatched.

Existing v5.5 expired-lease recovery remains authoritative for queue leases.

## Supersession

Supersession requires a different exact SHA and explicit ancestry proof. The old wait becomes `SUPERSEDED`; the old WorkItem is stopped and the running durable operation is canceled because Durable Brain v1 does not permit `WAITING_EXTERNAL -> SUPERSEDED`.

The new SHA requires a new admission/operation/WorkItem. No target mutation is hidden inside the old identity.

## Authority

v6.1B remains orchestration-only. GitHub Actions remains an execution fallback. Merge, release, trusted verification and Production Certification authority are unchanged.

## Acceptance criteria

- event-driven progression is primary;
- durable wait survives coordinator restart;
- duplicate event observations are idempotent;
- only pending gates are returned for fallback observation;
- fallback polling is delayed and bounded;
- Actions outage causes durable hold, not retry storm;
- superseding SHA is explicit and never silently retargets a WorkItem;
- terminal identities are never redispatched;
- no fixed `sleep` loop or network polling client exists in the module;
- exact-head CI/review/runtime gates must be green before landing.
