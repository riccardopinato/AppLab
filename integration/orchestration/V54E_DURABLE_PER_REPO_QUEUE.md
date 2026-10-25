# AppLab v5.4E — Durable Per-Repository Queue

Status: **IMPLEMENTED CONTROL-PLANE QUEUE / NO NETWORK DISPATCH**

v5.4E introduces durable queue state keyed by repository, lineage/ref and operation class while keeping GitHub Actions as the executor contract.

## Queue identity

Logical isolation is:

```text
repository | source_ref | operation_class
```

Unrelated repositories never share supersession scope.

## Durable state

The queue persists:

- current queue projection in `queue_entries`;
- append-only transition history in `queue_history`;
- repository fairness projection in `queue_repo_state`.

The SQLite reference adapter and PostgreSQL migration both protect immutable queue identity and reject queue-entry deletion. Queue history is append-only.

## Supersession

Automatic supersession is allowed only for pending normal VERIFICATION work when all are true:

- repository matches;
- source ref matches;
- operation class is VERIFICATION;
- the caller supplies the older SHA as an ancestor;
- `ancestry_proven=true`;
- old work is not protected;
- old work is not marked `preserve_for_calibration`.

LEASED work is never auto-cancelled by v5.4E.

CERTIFICATION, PHYSICAL_VALIDATION and MANUAL_DIAGNOSTIC remain protected classes.

## Backpressure

Hard limits bound:

- total pending work;
- pending work per repository.

Soft ready limits decide whether admitted work is immediately `QUEUED` or durably `DEFERRED`.

Deferred work is not lost. `rebalance()` promotes it when capacity returns.

## Fairness

Claim ordering combines:

1. operation priority;
2. bounded age bonus;
3. repository last-claim sequence;
4. enqueue sequence.

Global and per-repository active-lease limits are enforced before claim.

## Retry

Only infrastructure-like classes can retry:

- INFRA_ERROR;
- UNKNOWN_FAILURE;
- FLAKY_SUSPECT.

Retry count is bounded per Operation and uses exponential delay.

Deterministic app/build failures are terminal for queue retry purposes even if the caller asks to retry.

Expired leases re-enter through the same bounded infrastructure retry path.

## Executor boundary

A successful claim returns a structured executor intent:

```text
executor = GITHUB_ACTIONS
dispatch_performed = false
```

v5.4E contains no GitHub API call, workflow dispatch, webhook listener or worker-network client.

Actual controlled event-driven dispatch remains v5.4G.

## Integrity

`integrity_report()` checks:

- global/per-repository active limits;
- global/per-repository pending limits;
- lease projection consistency;
- queue identity against the durable Operation;
- queue-history continuity;
- projection state reconstructed from append-only history.

## PostgreSQL compatibility

`integration/orchestration/sql/postgres-v54e-queue.sql` is an idempotent migration applied after v5.4B.

CI applies both v5.4B and v5.4E schemas twice on PostgreSQL 16 and verifies:

- queue row insertion;
- immutable queue identity;
- append-only queue history;
- queue-entry delete guard.

## Chaos/restart evidence

Contract tests cover:

- explicit ancestry proof;
- same-lineage supersession;
- cross-repository isolation;
- protected work;
- calibration-preserved work;
- soft backpressure;
- hard pending bounds;
- one active lease per repository;
- deterministic app failure;
- bounded infrastructure retry;
- expired-lease recovery;
- direct SQL tamper rejection;
- restart persistence and history reconstruction.

The next step is v5.4F: warm trusted-runtime worker lifecycle and equivalence pilot.
