# AppLab v6.1C — Queue, Backpressure & Repair Budgets

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Purpose

v6.1C makes closed-loop execution bounded under load without introducing a second
queue or scheduler. It reuses the existing `DurablePerRepoQueue` and consumes
v6.1B durable wait/reconciliation directives.

The screenshot-driven objective is explicit: one pending GitHub job must not
create one independent `check -> sleep -> check` loop. Event delivery remains
primary; fallback observation is coalesced and backpressured.

## Existing queue reuse

Every admitted WorkItem must already be backed by the existing durable operation
and queue entry. Budget registration fails closed when that queue route is
missing. Existing per-repository/global queue limits, fairness, leases and
recovery therefore remain authoritative.

No v6.1C queue table, executor queue or parallel scheduler is introduced.

## Repair budget ledger

The immutable v6 WorkItem still owns the file, changed-line and repair-attempt
ceilings. v6.1C copies those limits into an immutable accounting identity and
adds cumulative runtime, cost and external-observation budgets.

Attempt reservations are idempotent. Reusing an attempt number with different
usage is rejected. Runtime/cost usage is cumulative and a hard violation stops
the budget rather than increasing the ceiling.

Failure delivery dedupe is keyed by a stable occurrence identity, not only by
the signature string. This preserves sequences such as `A -> B -> A -> A`: the
final consecutive `A` still triggers the repeated-signature STOP rule while a
redelivery of the third occurrence remains idempotent.

## Coalesced GitHub observation

v6.1B remains the authority that decides when a wait is due for bounded fallback
observation. v6.1C groups those due waits by exact `(repository, target_sha)`.

For example, two waits on the same AppLab SHA:

```
wait A -> AppLab CI, AppLab CodeQL
wait B -> AppLab CI, Emulator Self Test
```

produce one observation batch requesting:

```
AppLab CI, AppLab CodeQL, Emulator Self Test
```

rather than two independent GitHub status queries.

Each selected batch is journaled durably together with its per-WorkItem
observation-budget reservation **before** v6.1B fallback consumption. A crash
between reservation and the external query therefore replays the persisted batch
instead of losing a fallback slot. Already terminal waits, not-yet-due waits and
Actions-outage holds do not create a new observation batch. READY recovery is
query-free and remains available even when the observation budget is exhausted.
Groups deferred by v6.1C backpressure do not consume the v6.1B fallback counter.

## Observation backpressure

The initial contract permits at most four coalesced batches per cycle and one
batch per repository per cycle. Capacity is checked transactionally against
already persisted reservations, so retries or concurrent planners cannot bypass
the limit. Excess exact-SHA groups are deferred with
`OBSERVATION_BACKPRESSURE` and may be considered by a later reconciliation
cycle.

This is deliberate backpressure, not a failure and not an excuse to mutate the
target SHA.

## Authority

v6.1C remains orchestration-only. It does not mint verification results, does
not merge, does not release and does not certify. GitHub Actions remains an
execution/fallback surface; Production Certification remains the sole
certification authority.

## Acceptance criteria

- existing per-repository durable queue is reused;
- per-repository backpressure is observed without a second scheduler;
- WorkItem file/line/attempt limits are preserved;
- runtime/cost accounting is cumulative and bounded;
- attempt reservation is idempotent and conflicting replay is rejected;
- failure occurrence replay is idempotent while distinct occurrences remain distinct;
- repeated consecutive failure signature stops the repair budget;
- v6.1B event-driven waiting remains primary;
- due waits on the same repository + exact SHA are coalesced;
- one external observation can cover multiple waits/gates;
- batch+budget intent is durable before fallback consumption and is restart-recoverable;
- READY recovery remains available after observation-budget exhaustion;
- cycle capacity counts persisted reservations across retries/concurrent planners;
- backpressured observation groups do not consume fallback budget;
- no fixed sleep/network polling loop is introduced;
- target SHA is never silently retargeted;
- merge/release/verification/certification authority remains unchanged;
- exact-head CI/review/runtime gates must be green before landing.
