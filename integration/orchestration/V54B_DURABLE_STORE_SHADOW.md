# AppLab v5.4B — Durable Store Shadow

Status: **IMPLEMENTED SHADOW-ONLY / NO PRODUCTION ACTIVATION**

Baseline: AppLab `be0f0ac67127cada443f01b37c1003b5367386ed`.

v5.4B gives the Durable Brain its first persistent operational memory while preserving the v5.4A authority boundary.

It does not receive events from GitHub, dispatch workers, call Conductor, alter verification coverage or mint verification verdicts.

## 1. Delivered artifacts

- store contract:
  - `integration/orchestration/contracts/durable-store-shadow-contract-v1.json`
- canonical PostgreSQL-compatible schema:
  - `integration/orchestration/sql/postgres-v54b-shadow.sql`
- shadow durable-store implementation:
  - `scripts/durable_store_v54b.py`
- contract/integrity test:
  - `tests/contracts/durable_store_v54b_test.py`
- CI PostgreSQL 16 schema smoke.

## 2. Storage model

The store persists operational metadata for:

- Event;
- Operation;
- Attempt;
- EvidenceRef;
- OperationTransition.

Large evidence bytes are not stored in the relational database.

The database stores immutable references and content hashes only.

Conceptually:

```text
Event
  |
  v
Operation current projection
  |
  +--> Attempt (append-only)
  |
  +--> EvidenceRef (append-only metadata)
  |
  +--> OperationTransition (append-only)
```

## 3. Shadow-only authority

The store metadata is fixed to:

```text
mode      = SHADOW_NO_DISPATCH
authority = NONE
```

The relational store is an operational memory, not verification evidence authority.

It cannot:

- decide FAST/FULL;
- produce PASS;
- produce CERTIFIED;
- downgrade a trusted failure;
- dispatch a workflow;
- mutate a repository;
- reduce coverage.

## 4. Append-only records

The following record classes are immutable once inserted:

- Event;
- Attempt;
- EvidenceRef;
- OperationTransition.

Both the local shadow adapter and the PostgreSQL schema enforce this boundary.

The PostgreSQL schema uses mutation-rejection triggers.

The local persistent adapter also installs database triggers so append-only behavior is not merely an application convention.

## 5. Operation projection

Operation is the only mutable projection in this step.

Its identity remains immutable:

- operation ID;
- idempotency key;
- repository;
- ref;
- target SHA;
- AppLab SHA;
- operation class;
- analysis mode;
- queue key;
- priority;
- initial state;
- original payload.

Only `current_state` and its projection timestamp may change.

Every state change requires an append-only OperationTransition in the same transaction.

## 6. Crash/restart recovery

The durable state can be rebuilt from:

```text
Operation.initial_state
        +
ordered OperationTransition records
        =
Operation.current_state
```

`integrity_report()` replays every stored operation and reports any projection mismatch.

The test suite closes the database, reopens it and proves that:

- current state survives restart;
- transition sequence survives restart;
- reconstructed state equals persisted current state;
- no evidence/history record disappears.

## 7. Event semantics

v5.4A Event validation remains authoritative for control-plane shape.

The store adds persistence semantics:

- same `event_id` + same immutable payload -> `REPLAY`;
- same `event_id` + different immutable payload -> reject;
- different event ID + same dedupe key -> `DEDUPED`;
- otherwise -> `INSERTED`.

This is the persistence primitive required for future at-least-once event delivery.

No webhook ingestion is present in v5.4B.

## 8. Operation semantics

- first unique operation -> `INSERTED`;
- same operation ID + same immutable payload -> `REPLAY`;
- different operation ID + same idempotency key -> `IDEMPOTENT_REUSE`;
- same operation ID + conflicting immutable payload -> reject.

Operation identity therefore cannot drift after persistence.

## 9. Attempt semantics

Attempts remain immutable.

The store enforces:

- referenced Operation must already exist;
- Attempt ID cannot mutate;
- `operation_id + attempt_number` is unique;
- replay of the exact same Attempt is harmless;
- conflicting reuse is rejected.

Retry policy itself remains in v5.4A.

v5.4B only persists the resulting Attempts.

## 10. EvidenceRef semantics

EvidenceRef stores durable metadata only.

Required bindings include:

- Operation;
- optional Attempt;
- repository;
- target SHA;
- AppLab SHA;
- content SHA-256;
- byte size;
- immutable/reference storage URI;
- evidence class;
- registry state;
- retention class.

The adapter rejects an EvidenceRef when repository/SHA/AppLab identity does not match the persisted Operation.

An EvidenceRef cannot claim `trusted=true` when registry state is not `COMPATIBLE`.

The store never upgrades Evidence Schema Registry trust.

## 11. Atomic transitions

A transition succeeds only when:

1. the Operation exists;
2. persisted `current_state` equals transition `from_state`;
3. v5.4A state-machine validation accepts `from_state -> to_state`;
4. transition ID is not conflicting;
5. the append-only transition is inserted;
6. Operation projection is updated in the same database transaction.

A stale writer therefore cannot silently overwrite a newer durable state.

## 12. Local persistent reference adapter

The CI/self-test reference implementation uses Python standard-library SQLite.

Reason:

- no new runtime/dependency surface;
- real file-backed persistence;
- transaction semantics;
- foreign keys;
- unique constraints;
- restart/reopen testing;
- deterministic local contract testing.

This is **not** a decision to use SQLite as production infrastructure.

The provider-neutral semantics and PostgreSQL schema remain the deployment contract.

## 13. PostgreSQL compatibility proof

CI starts an ephemeral `postgres:16-alpine` container and:

1. waits for readiness;
2. applies the canonical v5.4B SQL schema;
3. applies it a second time to prove migration idempotency for this initial schema;
4. verifies `mode=SHADOW_NO_DISPATCH`;
5. verifies the expected AppLab tables exist;
6. destroys the container.

No persistent PostgreSQL instance or secret is created.

## 14. PostgreSQL schema protections

The schema includes:

- primary keys;
- unique Event dedupe key;
- unique Operation idempotency key;
- unique Attempt number per Operation;
- ordered transition uniqueness;
- foreign-key bindings;
- queue lookup index;
- evidence lookup index;
- append-only triggers;
- Operation immutable-identity guard.

## 15. Offline/shadow boundary

v5.4B contains no:

- webhook server;
- GitHub event consumer;
- `repository_dispatch`;
- Conductor SDK/client;
- worker lease/dispatch;
- production database connection;
- Postgres credentials;
- object-store upload;
- autonomous source mutation.

The contract test scans operational workflows and fails if `durable_store_v54b.py` is wired outside static CI validation.

## 16. CLI

Self-test:

```bash
python scripts/durable_store_v54b.py --self-test
```

Inspect an explicitly supplied local shadow database:

```bash
python scripts/durable_store_v54b.py \
  --db /path/to/shadow.sqlite3 \
  --integrity-report
```

There is intentionally no command that dispatches work.

## 17. Exit gate

v5.4B is complete only if the exact-head PR proves:

- v5.4A tests remain green;
- v5.4B self-test PASS;
- durable-store contract test PASS;
- restart persistence PASS;
- append-only mutation rejection PASS;
- state reconstruction PASS;
- PostgreSQL 16 schema smoke PASS;
- dependency/security audit PASS;
- CodeQL PASS;
- AppLab runtime regression gates PASS;
- no operational workflow wiring.

After that evidence, v5.4C may add a **signed Event Gateway Shadow** that writes normalized events to this store while still having zero dispatch authority.
