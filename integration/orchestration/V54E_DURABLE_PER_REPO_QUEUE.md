# AppLab v5.4E — Durable Per-Repository Queue

Status: **IMPLEMENTED CONTROL-PLANE QUEUE / NO NETWORK DISPATCH**

v5.4E replaces global event-driven cancellation semantics with durable repository/lineage/class queue state.

## Queue identity

Logical isolation remains:

```text
repository | source_ref | operation_class
```

Unrelated repositories never share supersession scope.

## Durable projections

The same v5.4B database stores:

- `queue_entries` mutable current queue state;
- `queue_history` append-only state history;
- `queue_repo_state` fairness projection.

Queue history rejects UPDATE and DELETE.

## Supersession

Automatic supersession is limited to pending normal VERIFICATION work when:

- repository matches;
- source ref matches;
- operation class matches;
- the old SHA is explicitly supplied as an ancestor of the new SHA;
- old work is not protected;
- old work is not preserved for calibration.

CERTIFICATION, PHYSICAL_VALIDATION and MANUAL_DIAGNOSTIC are protected.

LEASED work is not auto-cancelled by this step.

## Backpressure

The queue has explicit limits for:

- globally ready/leased work;
- ready/leased work per repository;
- active leased work per repository.

Ordinary overflow enters durable `DEFERRED` state rather than disappearing.

Protected work bypasses the soft ready limit so urgent release work is not silently dropped.

`rebalance()` promotes deferred work when capacity returns.

## Fairness

Claim ordering combines priority, bounded age bonus, repository last-claim sequence and enqueue sequence.

## Retry

Only infrastructure-like classes can be retried:

- INFRA_ERROR;
- UNKNOWN_FAILURE;
- FLAKY_SUSPECT.

Retry count is bounded per Operation and uses exponential availability delay.

Deterministic app/build failures are not retried merely to seek green.

Expired queue leases are recovered through the same bounded infrastructure retry path.

## Executor boundary

A successful claim emits a structured intent with:

```text
executor = GITHUB_ACTIONS
dispatch_performed = false
```

v5.4E contains no GitHub API client and no workflow dispatch call.

The actual event-driven dispatch adapter belongs to v5.4G.

## Recovery / chaos coverage

Tests verify restart persistence, repository isolation, protected-class survival, calibration-preservation, bounded retry, lease isolation, append-only history and zero network dispatch.
