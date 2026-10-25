# AppLab v5.4 — Event / Operation / Evidence Contracts and Queue Policy

Status: **DESIGN-ONLY / NOT ACTIVE**

This document defines the proposed durable control-plane data model for AppLab v5.4. It does not change the v5.3.5 evidence schema registry or any current production workflow.

## 1. Contract goals

The control-plane model must make these distinctions explicit:

- provider event versus AppLab operation;
- operation versus execution attempt;
- infrastructure retry versus intentional rerun;
- current state versus immutable history;
- orchestration metadata versus verification evidence;
- queue supersession versus verification PASS/FAIL;
- large evidence bytes versus durable evidence metadata.

No Event, Operation or queue state is itself proof that an app passed verification.

## 2. Common identity fields

Every durable control-plane record that refers to target work should carry, when applicable:

| Field | Meaning |
|---|---|
| `schema_version` | exact schema contract version |
| `correlation_id` | end-to-end trace identity |
| `repository` | exact `owner/name` |
| `source_ref` | source lineage/ref requested |
| `resolved_sha` | immutable target commit |
| `applab_sha` | exact AppLab implementation revision |
| `created_at` | UTC timestamp |
| `updated_at` | UTC timestamp for mutable projection only |

SHA-bearing fields are never replaced by branch names in trust-sensitive records.

## 3. Event v1

An Event is an immutable normalized observation.

Example:

```json
{
  "schema_version": 1,
  "record_type": "APPLAB_EVENT",
  "event_id": "evt_01...",
  "correlation_id": "cor_01...",
  "source": "github",
  "source_event_type": "push",
  "source_delivery_id": "provider-id",
  "observed_at": "2026-10-25T00:00:00Z",
  "repository": "riccardopinato/CamperBoss",
  "source_ref": "refs/heads/main",
  "resolved_sha": "40hex...",
  "previous_sha": "40hex-or-empty",
  "priority_hint": "MAIN_CHANGE",
  "dedupe_key": "sha256:...",
  "payload_digest_sha256": "sha256:...",
  "admission": "ADMITTED",
  "admission_reason": "WATCHLIST_ENABLED",
  "raw_payload_ref": "object://...",
  "trust": {
    "signature_verified": true,
    "replay_window_valid": true,
    "source_authenticated": true
  }
}
```

### 3.1 Event invariants

- `event_id` is globally unique.
- `source_delivery_id` is stored when the provider exposes one.
- `dedupe_key` is deterministic for equivalent normalized events.
- duplicate delivery creates no second logical admitted Event.
- raw payload bytes may be retained separately and hashed.
- event admission does not imply an Operation must run.
- malformed/untrusted events are stored as rejected audit records when safe to do so, but cannot enter the execution queue.

### 3.2 Dedupe examples

GitHub push:

```text
github|push|repository|ref|after_sha
```

Manual forced request:

```text
manual|request_id
```

Schedule/reconciliation:

```text
schedule|repository|ref|resolved_sha|window_id
```

Dedupe must prevent provider retries from multiplying work while still allowing an explicit forced rerun.

## 4. Operation v1

An Operation is one durable orchestration intent against one exact target identity.

Example:

```json
{
  "schema_version": 1,
  "record_type": "APPLAB_OPERATION",
  "operation_id": "op_01...",
  "correlation_id": "cor_01...",
  "trigger_event_ids": ["evt_01..."],
  "previous_operation_id": null,
  "operation_class": "VERIFICATION",
  "analysis_mode": "fast",
  "repository": "riccardopinato/CamperBoss",
  "source_ref": "main",
  "resolved_sha": "40hex...",
  "baseline_sha": "40hex-or-empty",
  "applab_sha": "40hex...",
  "contract_fingerprint": "sha256:...",
  "plan_digest_sha256": "sha256:...",
  "idempotency_key": "sha256:...",
  "queue_key": "riccardopinato/CamperBoss|main|VERIFICATION",
  "priority": 200,
  "state": "QUEUED",
  "state_reason": "EVENT_ADMITTED",
  "created_at": "2026-10-25T00:00:00Z",
  "started_at": null,
  "finished_at": null,
  "superseded_by_operation_id": null,
  "retry_policy": {
    "max_infra_attempts": 2,
    "backoff": "BOUNDED_EXPONENTIAL"
  },
  "authority": "ORCHESTRATION_ONLY"
}
```

### 4.1 Operation classes

Minimum set:

- `VERIFICATION` — normal FAST/FULL execution;
- `CERTIFICATION` — explicit certification intent;
- `PHYSICAL_VALIDATION`;
- `MANUAL_DIAGNOSTIC`;
- `CANARY`;
- `RECONCILIATION`;
- future `SECURITY_RECHECK`.

Operation class affects queue/cancellation policy, never verdict semantics.

### 4.2 Operation idempotency key

Proposed inputs:

```text
repository
resolved_sha
source_ref/lineage
operation_class
analysis_mode
AppLab SHA
contract fingerprint
semantic Smart Test Plan digest
explicit force generation
```

Two requests with the same idempotency key converge on the same existing Operation unless a policy explicitly requires a new intentional rerun.

## 5. Operation state machine

Allowed states:

```text
CREATED
  |
  v
QUEUED
  |
  v
PLANNING
  |
  +--> BLOCKED
  |
  v
READY
  |
  v
RUNNING
  |   |  +--> WAITING_RETRY --> RUNNING
  |
  +--> WAITING_EXTERNAL --> RUNNING
  |
  +--> SUCCEEDED
  +--> FAILED
  +--> BLOCKED
  +--> CANCELED
  +--> SUPERSEDED
```

### 5.1 Terminal meanings

- `SUCCEEDED`: orchestration completed and authoritative outputs were collected. It does **not** by itself mean AppLab PASS; the evidence/verdict fields must be read.
- `FAILED`: operation could not complete successfully under policy.
- `BLOCKED`: required evidence/capacity/identity/trust condition is missing or incompatible.
- `CANCELED`: canceled under an allowed explicit policy.
- `SUPERSEDED`: newer eligible work made this orchestration unnecessary. This is never PASS.

### 5.2 Illegal examples

The state validator must reject:

- `FAILED -> SUCCEEDED` mutation of the same historical Operation;
- `SUPERSEDED -> RUNNING`;
- changing `resolved_sha` after creation;
- changing `operation_class` after creation;
- replacing a target failure with an infrastructure retry state;
- creating `CERTIFIED` from the Brain.

An intentional rerun after a terminal state creates a **new Operation** linked by `previous_operation_id`.

## 6. Attempt v1

An Attempt is one concrete worker execution belonging to an Operation.

Example:

```json
{
  "schema_version": 1,
  "record_type": "APPLAB_ATTEMPT",
  "attempt_id": "att_01...",
  "operation_id": "op_01...",
  "attempt_number": 1,
  "executor": "github_actions",
  "worker_id": "gha-run-123",
  "worker_class": "BURST",
  "started_at": "2026-10-25T00:01:00Z",
  "finished_at": "2026-10-25T00:06:00Z",
  "state": "FAILED",
  "failure_class": "INFRA_ERROR",
  "retryable": true,
  "exit_identity": {
    "workflow_run_id": "123",
    "workflow_url": "..."
  }
}
```

### 6.1 Retry semantics

Infrastructure retry:

```text
same operation_id
attempt 1 = INFRA_ERROR
attempt 2 = PASS/FAIL/...
```

Intentional rerun:

```text
operation A terminal
user/policy explicitly reruns
operation B previous_operation_id = A
attempt numbering restarts inside B
```

An App/runtime FAIL is not retried merely to seek a green result. Existing failure intelligence determines retryability, and bounded policy remains conservative.

## 7. EvidenceRef v1

EvidenceRef stores durable metadata for evidence bytes or structured artifacts.

It does not duplicate the existing AppLab evidence-contract payload. It points to it and binds it to the Operation.

Example:

```json
{
  "schema_version": 1,
  "record_type": "APPLAB_EVIDENCE_REF",
  "evidence_ref_id": "evr_01...",
  "operation_id": "op_01...",
  "attempt_id": "att_01...",
  "artifact_name": "trusted-evidence-manifest.json",
  "evidence_class": "TRUSTED_RUNTIME",
  "producer": "trusted-apk-verifier",
  "registry_state": "COMPATIBLE",
  "content_sha256": "sha256:...",
  "byte_size": 12345,
  "storage_uri": "object://immutable/...",
  "repository": "riccardopinato/CamperBoss",
  "resolved_sha": "40hex...",
  "applab_sha": "40hex...",
  "apk_sha256": "sha256:...",
  "generated_at": "2026-10-25T00:05:00Z",
  "retention_class": "RELEASE_CRITICAL",
  "expires_at": "2027-01-23T00:05:00Z"
}
```

### 7.1 Evidence rules

- authoritative artifact content continues to follow the existing Evidence Schema Registry;
- EvidenceRef cannot upgrade `NOT_REGISTERED` evidence to trusted;
- bytes are content-hashed before final acceptance;
- storage URI is immutable/content-addressed where practical;
- deleting expired bytes does not rewrite historical Operation state; the reference becomes expired/unavailable according to retention policy;
- release-critical evidence follows the stricter existing retention contract.

## 8. OperationTransition v1

Every state transition is append-only.

Example:

```json
{
  "schema_version": 1,
  "record_type": "APPLAB_OPERATION_TRANSITION",
  "transition_id": "trn_01...",
  "operation_id": "op_01...",
  "from_state": "RUNNING",
  "to_state": "WAITING_RETRY",
  "reason_code": "TRANSIENT_EMULATOR_START_FAILURE",
  "actor": "durable-brain",
  "occurred_at": "2026-10-25T00:02:00Z",
  "metadata_digest_sha256": "sha256:..."
}
```

This record is the basis for crash recovery and audit.

## 9. Worker v1

A Worker advertises capabilities, not authority.

Required fields:

- `worker_id`;
- `worker_class`: `GITHUB_BURST`, `WARM_TRUSTED_ANDROID`, future `PHYSICAL_DEVICE`;
- supported API levels/profiles;
- AppLab SHA;
- tool versions;
- state: `AVAILABLE`, `LEASED`, `DRAINING`, `UNHEALTHY`, `QUARANTINED`, `OFFLINE`;
- last heartbeat;
- current lease;
- health reason;
- isolation generation/base snapshot digest.

A worker with mismatched AppLab SHA or required verifier/tool identity is not eligible.

## 10. WorkerLease v1

A lease prevents concurrent trust-sensitive reuse.

Rules:

- one exclusive active lease per warm runtime worker;
- lease has bounded expiry/heartbeat;
- lost heartbeat does not cause immediate reassignment until ownership is reconciled;
- recovered worker with uncertain state is quarantined before reuse;
- lease release requires cleanup outcome.

## 11. Queue key and isolation

Canonical queue key:

```text
repository | lineage/ref | operation_class
```

Examples:

```text
riccardopinato/CamperBoss|main|VERIFICATION
riccardopinato/CamperBoss|main|CERTIFICATION
riccardopinato/Battery_Guard|main|VERIFICATION
```

Consequences:

- CamperBoss verification cannot cancel Battery Guard.
- CamperBoss verification cannot silently cancel CamperBoss certification.
- a feature branch can be independent from main unless policy explicitly relates them.

## 12. Priority policy

Priority is explicit and deterministic.

Recommended baseline:

| Priority band | Work |
|---|---|
| 500 | explicit certification / release-blocking manual validation |
| 400 | main/default-branch regression after accepted change |
| 350 | pull request/head validation |
| 300 | security/dependency-triggered recheck |
| 200 | ordinary watched branch verification |
| 100 | canary/reconciliation |
| 50 | research/advisory/background analysis |

Priority affects dispatch order only.

A lower-priority operation with excessive wait time receives bounded aging so a hot repository cannot starve the rest of the portfolio.

## 13. Per-repository concurrency policy

Initial conservative policy:

- maximum one heavy runtime Operation per repository lineage;
- cheap/static preparation may execute concurrently when it cannot affect shared runtime state;
- certification gets a separate protected class;
- physical device operations are bounded by device availability/capability;
- global capacity is enforced separately from repository isolation.

This intentionally avoids over-parallelizing stateful specialist labs that currently share an emulator.

## 14. Supersession and coalescing

### 14.1 Queued normal verification

Operation A may be marked `SUPERSEDED` by B only when all are true:

- same repository;
- same lineage/ref;
- same normal `VERIFICATION` class;
- B SHA is proven descendant of A SHA;
- A has not entered a protected/non-repeatable stage;
- no policy requires A as calibration/shadow evidence.

Events that caused A remain persisted.

### 14.2 Running normal verification

Running A may be canceled/superseded only when:

- same conditions as above;
- AppLab can safely cancel the current executor;
- no certification/physical/manual protected evidence is being produced;
- cancellation does not destroy required shadow-calibration evidence.

Otherwise A finishes and B waits.

### 14.3 Never auto-supersede

- `CERTIFICATION`;
- `PHYSICAL_VALIDATION`;
- explicit `MANUAL_DIAGNOSTIC`;
- an operation marked `preserve_for_calibration=true`;
- an operation already producing release-critical evidence.

## 15. Backpressure policy

The Brain must not accept infinite runnable work.

Required controls:

- bounded ready queue;
- maximum active operations globally;
- maximum heavy runtime operations per repository;
- bounded infra retries;
- per-source event ingestion rate limits;
- duplicate/coalescing before dispatch;
- low-priority canary suppression during high load;
- circuit breaker for repeatedly unhealthy worker class/provider;
- GitHub Actions burst fallback only within an explicit concurrency budget.

### 15.1 Degraded mode

When warm capacity is unavailable:

1. protected/urgent work may fall back to GitHub Actions;
2. normal work remains queued or falls back according to budget;
3. canaries/research are delayed;
4. no missing capacity becomes PASS.

## 16. Reconciliation policy

Event-driven delivery is primary, but reconciliation remains mandatory.

A periodic reconciler compares:

- enabled watchlist repository;
- configured source ref;
- current GitHub resolved SHA;
- latest admitted Event;
- latest non-superseded Operation.

If GitHub head is newer and no admitted event/operation exists, reconciliation creates a normalized `RECONCILIATION` Event.

This preserves the reliability benefit of the current hourly watcher without making polling the normal latency path.

## 17. Persistence schema sketch

A provider-neutral SQL shape:

```text
events(
  event_id PK,
  dedupe_key UNIQUE,
  source,
  source_event_type,
  repository,
  source_ref,
  resolved_sha,
  observed_at,
  payload_digest,
  admission,
  raw_payload_ref
)

operations(
  operation_id PK,
  idempotency_key UNIQUE,
  previous_operation_id FK nullable,
  repository,
  source_ref,
  resolved_sha,
  applab_sha,
  operation_class,
  analysis_mode,
  queue_key,
  priority,
  state,
  plan_digest,
  contract_fingerprint,
  created_at,
  started_at,
  finished_at
)

operation_events(
  operation_id FK,
  event_id FK,
  PRIMARY KEY(operation_id,event_id)
)

attempts(
  attempt_id PK,
  operation_id FK,
  attempt_number,
  executor,
  worker_id,
  state,
  failure_class,
  retryable,
  started_at,
  finished_at,
  UNIQUE(operation_id,attempt_number)
)

operation_transitions(
  transition_id PK,
  operation_id FK,
  sequence UNIQUE per operation,
  from_state,
  to_state,
  reason_code,
  actor,
  occurred_at
)

evidence_refs(
  evidence_ref_id PK,
  operation_id FK,
  attempt_id FK nullable,
  artifact_name,
  evidence_class,
  content_sha256,
  storage_uri,
  repository,
  resolved_sha,
  applab_sha,
  apk_sha256 nullable,
  generated_at,
  retention_class,
  expires_at
)

workers(...)
worker_leases(...)
```

## 18. Current-state projections

Control Center should read projections such as:

- current repository head;
- last verification operation;
- last trusted PASS/FAIL/BLOCKED;
- last certified SHA;
- queued/running operation;
- queue age;
- worker assigned;
- retry count;
- latest failure class;
- current calibration state.

The projections are convenience views. They must be rebuildable from durable records/evidence.

## 19. Compatibility with Evidence Schema Registry

Initial v5.4 control-plane records are **not automatically part of the v5.3.4 evidence registry**.

Reason:

- Event/Operation/Attempt are orchestration/control records, not verification evidence;
- prematurely registering them as evidence could blur authority.

When a stable v5.4 producer/consumer boundary exists, dedicated stable artifacts may be registered, for example:

- `operation-manifest.json`;
- `queue-decision.json`;
- `worker-attestation.json`.

Any future registration must explicitly declare `evidence_class` and fixed authority fields and must not imply verification authority.

## 20. Contract-test requirements

Before production activation, independent tests must cover:

- duplicate Event delivery;
- invalid webhook signature;
- event replay outside window;
- identical idempotency convergence;
- explicit forced rerun creates linked Operation;
- illegal state transition rejection;
- crash between Attempt result and state projection;
- retry preserves Operation identity;
- intentional rerun changes Operation identity;
- cross-repository events do not cancel each other;
- same-repo descendant supersession;
- non-descendant commit cannot supersede;
- certification protected from normal supersession;
- worker heartbeat loss;
- worker cleanup uncertainty causes quarantine;
- object/evidence hash mismatch fails closed;
- projection rebuild reproduces current state;
- no control-plane state can mint PASS/CERTIFIED.

## 21. Design invariant

The most important invariant is:

> **The Durable Brain may lose availability, but it must never manufacture verification truth.**

If the Brain, database, queue, worker or object store is uncertain, AppLab may become delayed or BLOCKED. It must not become falsely green.
