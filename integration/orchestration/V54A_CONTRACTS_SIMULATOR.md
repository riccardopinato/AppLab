# AppLab v5.4A — Contracts & Simulator

Status: **IMPLEMENTED OFFLINE / NO PRODUCTION ACTIVATION**

Baseline: AppLab `a0a5dcfaf58d5e1e7f96954c2b9836ce0fec222c`.

v5.4A implements the first executable slice of the Durable Brain design while preserving the v5.3.5 verification authority model.

## Delivered

- versioned control-plane contract:
  - `integration/orchestration/contracts/durable-brain-contract-v1.json`
- offline deterministic engine:
  - `scripts/durable_brain_v54a.py`
- replay corpus:
  - `integration/orchestration/v54a-replay-corpus.json`
- independent contract/replay test:
  - `tests/contracts/durable_brain_v54a_test.py`
- CI compilation, self-test, replay and contract test.

## Implemented contracts

### Event

Validates:

- schema and record identity;
- durable IDs;
- exact repository/ref/SHA identity;
- deterministic dedupe key;
- explicit admission state;
- signature/replay/authentication trust booleans;
- admitted events fail closed unless all trust checks are true.

### Operation

Validates:

- immutable target/AppLab SHA identity;
- operation class and analysis mode;
- deterministic queue key;
- deterministic idempotency key;
- priority bounds;
- `ORCHESTRATION_ONLY` authority;
- certification mode/class consistency.

### Attempt

Validates:

- attempt identity and numbering;
- executor;
- attempt state;
- failure class;
- retryability;
- deterministic app/build/visual failures cannot be marked retryable;
- successful attempts must use `failure_class=NONE`.

## State validator

The operation state machine is executable.

Terminal states cannot mutate back to active states.

Examples:

```text
QUEUED -> PLANNING       valid
RUNNING -> WAITING_RETRY valid
FAILED -> SUCCEEDED      rejected
SUPERSEDED -> RUNNING    rejected
```

The simulator has no concept of PASS/CERTIFIED authority and cannot mint either.

## Queue simulator

Queue identity is:

```text
repository | source_ref | operation_class
```

Implemented rules:

- unrelated repositories are independent;
- automatic supersession applies only to normal `VERIFICATION`;
- newer work must be a proven descendant;
- queued/ready/waiting-retry work can be superseded safely; `CREATED` work cannot be superseded before it enters the queue;
- running verification requires explicit `cancel_safe=true`;
- protected running stages cannot be superseded;
- certification/physical/manual classes are protected by class isolation;
- calibration-preserved/release-critical work cannot be superseded;
- identical idempotency keys reuse the existing logical Operation;
- dispatch projection is deterministic by priority, arrival order and operation ID and includes only `QUEUED`/`READY` work.

No GitHub API is consulted by the simulator. Commit ancestry is supplied explicitly by the replay input.

## Retry semantics

Infrastructure retry:

```text
same operation_id
attempt_number + 1
```

Intentional rerun remains a new Operation under the v5.4 design.

The simulator rejects retry semantics for deterministic:

- application runtime failure;
- visual failure;
- build/quality failure.

Retry is authorized only from a completed `FAILED` Attempt. `CREATED`/`RUNNING`/other unfinished states never authorize a parallel retry. Retry budget exhaustion is explicit and deterministic.

## Replay corpus

The initial corpus covers:

1. duplicate push delivery dedupe;
2. valid state transition;
3. illegal terminal mutation;
4. bounded infrastructure retry;
5. deterministic application failure without retry;
6. descendant superseding queued verification;
7. cross-repository isolation;
8. non-descendant supersession rejection;
9. certification isolation;
10. safe running supersession;
11. protected running-stage preservation;
12. operation idempotent reuse;
13. reconciliation window identity versus same-window redelivery;
14. unfinished Attempt no-retry;
15. `CREATED` operation supersession rejection;
16. conflicting immutable identity under the same `operation_id` rejection.

The complete report has a deterministic SHA-256 replay digest. Running the same corpus twice must produce byte-equivalent logical output.

## Offline-only guard

v5.4A deliberately contains no:

- webhook receiver;
- HTTP client;
- database client;
- Postgres connection;
- Conductor client;
- worker dispatch;
- repository mutation;
- production queue;
- runtime verifier integration.

The contract test scans operational workflows and fails if `durable_brain_v54a.py` is wired outside the ordinary static CI validation workflow.

## CLI

```bash
python scripts/durable_brain_v54a.py --self-test
python scripts/durable_brain_v54a.py replay

python scripts/durable_brain_v54a.py validate-event event.json
python scripts/durable_brain_v54a.py validate-operation operation.json
python scripts/durable_brain_v54a.py validate-attempt attempt.json
python scripts/durable_brain_v54a.py validate-transition QUEUED PLANNING
```

## Authority boundary

v5.4A remains below the production-enablement line:

```text
Durable Brain contracts/simulator
        |
        +-- NO dispatch
        +-- NO verdict authority
        +-- NO certification authority
        +-- NO coverage reduction
```

Smart Test Plan, Trusted APK Verifier, specialist labs, Release Assurance, Physical Evidence and Production Certification remain unchanged.

## Exit gate

v5.4A is complete only when the exact-head PR has:

- contract self-test PASS;
- replay corpus PASS;
- independent contract test PASS;
- existing AppLab CI PASS;
- dependency security audit PASS;
- CodeQL PASS;
- applicable governance/review gates PASS;
- no production workflow wiring.

Only after that evidence may v5.4B Durable Store Shadow begin.
