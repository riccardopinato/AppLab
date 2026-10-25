# AppLab v5.4 — Durable Brain Design & Architecture Audit

Status: **DESIGN-ONLY / NOT ACTIVE IN PRODUCTION**

Factory baseline used for this audit: **App-Factory-Core Master v26.6 @ `4cc0b94467b94ab6fabe2c927fcc58afff49e39a`**.

AppLab baseline audited: **v5.3.5 @ `02f25d75b990055521869d75781e93893a6b6cdf`**.

External references reviewed for architectural patterns:

- `conductor-oss/conductor@1488804170d159021c7e62dce61514b8f31ef9ff`
- `huginn/huginn@af23181367a87efc2c5693d68b6887332b3239fd`
- `The-Vibe-Company/quivr@1f72133e27e1cc0a7a05fb35a93df0f9e33136c4`
- `Genymobile/scrcpy@a60891aea193d92e7e5c3942700eca63f9d19a5f`
- `square/leakcanary@eb60b0be53732aa016c79b7774b497770ad1e4f3`
- curated source: `riccardopinato/Analisi-delle-mie-stelle-github@493db7d438f530957ddae03a4fe1777548c5f4f6`

This document is an architecture/design audit only. It does not authorize coverage reduction, production worker activation, Conductor deployment, external actuation, new secrets, or changes to existing verification authority.

## 1. Executive conclusion

AppLab v5.3.5 already has strong verification intelligence:

- Smart Test Plan as FAST/FULL selection authority;
- trusted build/runtime separation;
- content-addressed build reuse;
- Evidence Graph and schema compatibility registry;
- history learning and failure intelligence;
- specialist Android labs;
- physical-evidence semantics;
- release assurance and production certification;
- multi-project delta calibration with coverage reduction explicitly disabled.

The main architectural limitation is no longer test depth. It is **execution continuity**.

The current Repo Watcher is an hourly GitHub Actions orchestrator. It discovers changed repositories, dispatches reusable verification jobs, aggregates results into rolling history and then exits. State continuity is reconstructed through GitHub cache/artifacts rather than through a dedicated durable operations layer.

v5.4 should therefore introduce a **Durable Brain** above the existing AppLab verification engines.

The Durable Brain must not replace Smart Test Plan, Trusted APK Verifier, Release Assurance or Production Certification. Its responsibility is narrower:

> receive events, create durable operations, prioritize and queue work, dispatch existing AppLab workers, recover from infrastructure failure, correlate evidence, and preserve an inspectable execution history.

The target architecture is event-driven, durable, idempotent and fail-closed.

## 2. Current-state audit

### A-01 — Central operational history is not a durable system of record

Severity: **HIGH**

Current watcher aggregation restores `.applab-history` from GitHub Actions cache and republishes history artifacts. That is useful CI continuity but is not an operational database with explicit transactional identity, query semantics, retention guarantees, per-operation state, retry lineage or concurrent writers.

Impact:

- H24 orchestration cannot safely depend on cache restore/save as the primary memory model.
- concurrent event-driven executions would need stronger consistency;
- retry versus intentional rerun identity is not first-class;
- historical evidence is difficult to query incrementally without loading the JSONL stream;
- cache/artifact lifecycle is infrastructure behavior rather than product-domain state.

Required design response:

- durable metadata store for Event / Operation / Attempt / Evidence metadata;
- immutable object storage for large evidence;
- projections for current app state and Control Center.

### A-02 — Global watcher cancellation is incompatible with continuous multi-repository events

Severity: **HIGH**

The current Repo Watcher uses one concurrency group:

`applab-repo-watcher`

with `cancel-in-progress: true`.

This is appropriate for an hourly polling workflow that wants to discard stale global discovery work. It is not safe as the core concurrency policy of an event-driven system.

Example failure mode:

- Battery Guard event starts watcher work;
- CamperBoss event arrives seconds later;
- the newer global watcher can cancel the earlier watcher even though the repositories are independent.

Required design response:

- scheduling and supersession must be scoped by repository + lineage/ref + operation class;
- unrelated repositories must never cancel one another;
- certification and manual/physical operations require stricter cancellation semantics.

### A-03 — Polling adds avoidable latency

Severity: **MEDIUM**

The hourly watcher at minute 17 is a reliable credential-light fallback, but a production-quality H24 brain should normally react to push / PR / workflow / security events within seconds.

Required design response:

- signed event gateway as primary trigger;
- hourly watcher retained as reconciliation/watchdog fallback;
- event deduplication and replay protection.

### A-04 — Ephemeral worker startup remains a meaningful latency component

Severity: **MEDIUM**

v4.1 already eliminates duplicated build work through Build Once / Verify Many and stable execution keys. Remaining wall-clock waste includes hosted-runner acquisition, SDK/tool bootstrapping and emulator startup.

Required design response:

- warm trusted-runtime worker pool;
- preinstalled AppLab toolchain;
- pre-created read-only AVD templates/snapshots;
- disposable per-operation emulator clones;
- GitHub Actions retained as burst/fallback capacity.

### A-05 — Retry, rerun and supersession are not modeled as durable domain concepts

Severity: **MEDIUM**

Failure intelligence already classifies retryable infrastructure failures. The missing layer is durable execution identity.

Required design response:

- infrastructure retry keeps the same `operation_id` and creates a new immutable Attempt;
- intentional rerun creates a new Operation with `previous_operation_id`;
- a newer descendant SHA may supersede queued/running non-authoritative work under explicit policy;
- supersession is not PASS and does not erase prior evidence.

### A-06 — There is no explicit backpressure model

Severity: **MEDIUM**

GitHub matrix jobs provide parallelism, but the future system needs to reason about:

- worker capacity;
- repository fairness;
- hot repositories;
- low-priority canaries;
- certification urgency;
- retry storms;
- external provider degradation.

Required design response:

- bounded queues;
- worker capability leases;
- weighted fairness;
- coalescing of stale pending work;
- circuit-breaker/degraded modes.

### A-07 — Documentation retention wording has drifted from the current watcher workflow

Severity: **LOW**

`integration/flutter/WATCHER.md` describes a 90-day history artifact, while the current Repo Watcher uploads the central-history artifact with `retention-days: 7`.

This is not by itself an evidence-authority failure because other evidence classes have their own retention contracts, but it reinforces that long-lived operational memory should not depend on watcher artifact wording or transient CI storage.

Required design response:

- v5.4 durable store becomes the operational history source;
- artifact retention remains an evidence-export/backup policy;
- documentation must distinguish operational state from exported artifacts.

## 3. v5.4 design principles

1. **Orchestration is not authority.**  
   The Durable Brain may decide when and where work runs. It may not redefine what constitutes PASS, CERTIFIED, trusted runtime or physical evidence.

2. **Smart Test Plan remains the sole FAST/FULL authority.**  
   Brain scheduling consumes the plan; it does not invent an alternate test selector.

3. **Exact identity remains mandatory.**  
   Repository, immutable source SHA, AppLab revision, plan digest, build contract and APK SHA-256 remain bound through the existing chain.

4. **Missing state fails closed.**  
   Unknown worker outcome, missing artifact, incomplete callback or incompatible schema becomes BLOCKED/ERROR/UNKNOWN, never PASS.

5. **Every side effect is idempotent or explicitly non-repeatable.**  
   Event redelivery and worker retry must not create duplicate authoritative effects.

6. **Untrusted build and trusted runtime stay isolated.**  
   Warm runtime hosts never execute target source/build scripts.

7. **The brain is deterministic where authority matters.**  
   LLM/agent reasoning can assist triage, explanation and later repair proposals, but cannot override deterministic verification verdicts.

8. **Shadow before authority.**  
   Conductor is first evaluated as a zero-side-effect mirror.

9. **Continuous observation is preferred over continuous waste.**  
   H24 means the brain is always available; it does not mean rerunning unchanged applications in an infinite loop.

## 4. Target architecture

```text
GitHub / CI / security / device / schedule events
                     |
                     v
              +--------------+
              | Event Gateway |
              +------+-------+
                     |
        normalize / verify / dedupe
                     |
                     v
             +---------------+
             | Durable Store  |
             | Event          |
             | Operation      |
             | Attempt        |
             | Evidence meta  |
             +-------+-------+
                     |
                     v
             +---------------+
             | Durable Brain  |
             | state machine  |
             | priority/queue |
             | recovery       |
             +--+----------+--+
                |          |
                |          +----------------------+
                v                                 v
        Existing AppLab planner             Reconciliation
        Smart Test Plan                     / watchdog
                |                                 |
                v                                 |
        +-------------------+                     |
        | Dispatch decision |<--------------------+
        +----+---------+----+
             |         |
             |         +--------------------------+
             v                                    v
 GitHub Actions build/burst                Warm trusted-runtime
 untrusted build remains isolated          worker pool
             |                                    |
             +----------------+-------------------+
                              |
                              v
                     Existing trusted AppLab
                     verifier / specialist labs
                              |
                              v
                        Evidence ingestion
                              |
                              v
                 Control Center / decisions
```

## 5. Component boundaries

### 5.1 Event Gateway

Responsibilities:

- validate webhook/provider signatures;
- enforce timestamp/replay window;
- assign `event_id`;
- normalize provider-specific payloads to the v5.4 Event contract;
- compute deterministic `dedupe_key`;
- persist the event before acknowledging it;
- emit no verification verdict.

Primary future inputs:

- GitHub push;
- pull request changes;
- workflow completion/failure;
- manual AppLab request;
- schedule/reconciliation;
- security/dependency signal;
- physical-device availability;
- future external monitoring signals.

The hourly Repo Watcher remains a fallback reconciliation source until event delivery has demonstrated sufficient reliability.

### 5.2 Durable Store

Recommended implementation boundary:

- **PostgreSQL-compatible database** for structured operational metadata;
- **S3-compatible/object storage** for APKs, video, screenshots, logs, heap dumps and other large evidence;
- provider-neutral interfaces so the design is not coupled to Appwrite/Supabase/one cloud.

The database is not an evidence authority. It is the durable record of execution identity and references to evidence produced by authoritative AppLab components.

Append-only by default:

- raw Events;
- Attempts;
- Evidence metadata;
- operation transitions/audit records.

Mutable projections are allowed for:

- current operation state;
- worker lease state;
- latest project status;
- queue counters;
- Control Center views.

### 5.3 Durable Brain

Responsibilities:

- create Operations from admitted Events;
- request/consume the existing Smart Test Plan;
- assign queue key and priority;
- coalesce/supersede work under explicit rules;
- allocate a compatible worker;
- apply bounded infrastructure retry;
- wait for external signals;
- persist state transitions;
- recover after process restart;
- dispatch GitHub Actions fallback work when warm capacity is unavailable;
- never reinterpret test evidence.

The Brain must be restart-safe: a process restart may delay work but may not lose operation identity or silently repeat a non-idempotent action.

### 5.4 Existing AppLab engines

These remain authoritative and are treated as workers/services by the Brain:

- Smart Test Plan;
- execution acceleration/build contract;
- external Flutter/native/universal build runners;
- Trusted APK Verifier;
- specialist labs;
- Evidence Graph;
- Release Reality / Release Assurance;
- Production Certification;
- Physical Evidence Hub.

v5.4 is therefore an orchestration layer **above**, not a rewrite **inside**, v5.3.5.

## 6. Authority matrix

| Concern | Authority after v5.4 design |
|---|---|
| FAST/FULL lane | Smart Test Plan |
| selected specialist labs | Smart Test Plan |
| build identity/reuse | existing Execution Acceleration + build contract |
| trusted runtime verdict | Trusted APK Verifier / labs |
| physical-device evidence | Physical Evidence Hub |
| release assurance | Release Assurance |
| CERTIFIED | Production Certification Gate only |
| queue ordering | Durable Brain |
| worker allocation | Durable Brain |
| infrastructure retry | Durable Brain within bounded policy |
| operation recovery | Durable Brain |
| Conductor shadow output | ADVISORY / NO AUTHORITY |
| LLM diagnosis | ADVISORY |
| autonomous source modification | OUT OF SCOPE for initial v5.4 |

## 7. Storage and consistency model

The minimum operational tables/entities are defined in the companion schema document:

- `Event`;
- `Operation`;
- `Attempt`;
- `EvidenceRef`;
- `Worker`;
- `WorkerLease`;
- `OperationTransition`.

Key consistency rules:

- event ingestion is at-least-once safe because normalized events are deduplicated;
- exactly one active Operation may own a given idempotency key unless explicitly forced;
- attempts are never updated into a different historical outcome;
- terminal AppLab evidence is immutable;
- a superseded operation remains queryable;
- current-state projections are rebuildable from durable records.

## 8. Queue and scheduling model

The Brain uses a logical queue key:

```text
<repository>|<lineage/ref>|<operation-class>
```

Operation classes must distinguish at least:

- normal FAST/FULL verification;
- CERTIFICATION;
- physical validation;
- manual/forced diagnostic;
- scheduled canary/reconciliation.

High-level policy:

- unrelated repositories run independently;
- only work sharing the same queue key may supersede one another;
- queued non-certification work for an older SHA may be coalesced when a newer SHA is a proven descendant;
- running normal verification may be canceled only when the replacement is a proven descendant and no protected/non-repeatable stage has started;
- certification, physical validation and explicit manual runs are never automatically canceled by a normal newer commit;
- retries never change a target SHA or plan silently;
- retry storms are bounded and backpressured.

Detailed policy is in the companion schema/queue document.

## 9. Warm-worker architecture

The first warm pool is **trusted-runtime only**.

It must not execute target repository build scripts.

A warm worker contains:

- pinned AppLab verifier revision;
- Android SDK/platform tools;
- Maestro and required trusted tooling;
- KVM support;
- prepared AVD base images;
- read-only pristine AVD snapshots/templates;
- local cache for trusted AppLab tooling only.

Per operation:

1. Brain acquires an exclusive worker lease.
2. Worker creates or restores a disposable emulator instance from the pristine template.
3. Worker downloads the previously built APK contract/evidence.
4. Existing trusted validation verifies repository/SHA/mode/contract/APK hash.
5. Runtime and specialist labs execute.
6. Evidence is uploaded.
7. Emulator instance is destroyed/reset.
8. Worker performs health/scrub checks.
9. Lease is released or worker enters quarantine.

A worker that encounters uncertain isolation, host disk exhaustion, KVM corruption or repeated ADB failure becomes `UNHEALTHY/QUARANTINED` and must not accept new trusted work.

GitHub Actions remains the fallback/burst executor.

## 10. Conductor role

Conductor is a **reference and shadow candidate**, not a production dependency in this design commit.

Why it fits:

- durable workflow state;
- restart/retry semantics;
- event handlers and schedules;
- branching and loops;
- dynamic fan-out;
- worker decoupling;
- pause/resume/cancel;
- inspectable execution history;
- workflow versioning.

Why it is not immediately authoritative:

- AppLab already has mature verification authority;
- introducing an orchestrator creates a new stateful dependency and failure domain;
- queue/supersession semantics must be proven against real AppLab behavior;
- dynamic/agentic features must not bypass deterministic AppLab contracts.

The initial Conductor pilot is therefore **SHADOW_NO_DISPATCH**.

See `CONDUCTOR_SHADOW_AND_WARM_WORKERS_V54.md`.

## 11. H24 operating model

H24 means:

- Event Gateway is always ready;
- Brain state survives restart;
- queues are durable;
- worker health is known;
- reconciliation catches missed events;
- retries are bounded;
- current state can be queried at any time.

It does **not** mean continuously retesting an unchanged SHA.

Recommended triggers:

- event-driven verification on meaningful source/PR/main changes;
- periodic low-frequency canary for environment drift;
- periodic reconciliation between GitHub head and last known operation;
- security/dependency-triggered targeted verification;
- certification only on explicit release/certification intent.

## 12. Observability requirements

Every path must carry:

- `correlation_id`;
- `event_id`;
- `operation_id`;
- `attempt_id`;
- repository;
- immutable target SHA;
- AppLab revision;
- worker identity;
- workflow/plan digest when applicable.

Minimum metrics:

- event ingest latency;
- event-to-operation latency;
- queue wait p50/p95;
- operation duration p50/p95 by lane;
- worker utilization;
- warm-worker hit rate;
- AVD reset/start duration;
- GitHub fallback rate;
- retry rate by failure class;
- superseded/coalesced operation count;
- duplicate event rate;
- infrastructure failure rate;
- orphaned/unknown operation count;
- evidence upload/fetch failures.

Logs must be structured and correlation-aware.

## 13. Security and trust requirements

### Event boundary

- signed webhook verification;
- replay protection;
- bounded payload size;
- explicit event allowlist;
- no arbitrary command execution from event payload.

### Brain boundary

- least-privilege token per integration;
- no target-provided executable orchestration;
- workflow definitions/version pinned;
- transition audit log;
- secrets never copied into Evidence records.

### Worker boundary

- untrusted target build does not run on trusted-runtime warm hosts;
- worker leases are exclusive;
- disposable emulator state;
- network policy may be narrowed per lab;
- evidence uploads are content-hashed;
- host quarantine on uncertain cleanup.

### AI boundary

An AI/LLM component may later:

- summarize failure evidence;
- suggest probable root cause;
- propose a bounded fix;
- rank existing evidence.

It may not:

- change FAIL to PASS;
- mint CERTIFIED;
- fabricate evidence;
- suppress required physical validation;
- remove required tests outside the approved Smart Test Plan/delta policy.

## 14. Explicit non-goals for initial v5.4 implementation

- no coverage reduction;
- no replacement of GitHub Actions for all work;
- no autonomous merge/release/store publishing;
- no autonomous target-source edits in the first orchestration milestone;
- no Conductor authority;
- no new certification semantics;
- no generic multi-agent framework;
- no migration to Appwrite solely for this feature;
- no continuous rerun loop for unchanged apps;
- no physical-device farm in the first implementation step.

## 15. Implementation sequence

### v5.4A — Contracts and deterministic simulator

Deliver:

- versioned Event/Operation/Attempt/EvidenceRef schemas;
- state-transition validator;
- queue/supersession simulator;
- synthetic and historical replay tests;
- zero production integration.

Exit gate:

- deterministic replay;
- invalid transitions fail closed;
- no change to current workflows.

### v5.4B — Durable Store in shadow

Deliver:

- Postgres-compatible schema;
- migration scripts;
- append-only event/transition/attempt writes;
- evidence-reference metadata;
- Control Center shadow projection.

Exit gate:

- rebuildable projection;
- crash/restart test;
- no authority consumption.

### v5.4C — Event Gateway shadow ingestion

Deliver:

- signed GitHub webhook adapter;
- dedupe/replay protection;
- event persistence;
- periodic reconciliation comparison.

Exit gate:

- no missed normalized target changes in the pilot sample;
- duplicate deliveries create one logical event identity;
- still no worker dispatch.

### v5.4D — Conductor shadow pilot

Deliver:

- versioned shadow workflow;
- mirror Event -> planned operation DAG;
- zero dispatch credentials;
- comparison against actual AppLab planner/workflow outcome.

Exit gate defined in companion document.

### v5.4E — Per-repository durable queue

Deliver:

- queue state;
- priority/fairness;
- supersession/coalescing;
- bounded retry;
- GitHub Actions remains executor.

Exit gate:

- unrelated repositories cannot cancel each other;
- certification/manual protected classes survive normal supersession;
- chaos/restart tests pass.

### v5.4F — Warm trusted-runtime pilot

Deliver:

- one isolated worker;
- lease/heartbeat;
- pristine AVD snapshot;
- disposable emulator clone/reset;
- GitHub fallback.

Exit gate:

- artifact/verdict equivalence with GitHub trusted verifier;
- no cross-run state leak;
- measurable startup/wall-clock improvement;
- worker quarantine tests.

### v5.4G — Controlled event-driven execution

Only after A-F evidence is satisfactory:

- webhook-triggered real operations for a small pilot set;
- hourly watcher remains watchdog;
- GitHub Actions remains burst fallback;
- no certification authority change.

### Later milestone — autonomous triage/fix proposal

Only after durable orchestration is stable:

- diagnosis agent;
- issue/update automation;
- isolated fix branch generation;
- AppLab validation of proposed fix;
- PR creation under explicit governance.

Autonomous merge/release remains a separate governance decision.

## 16. Promotion rules

No v5.4 design component becomes production authority merely because its code exists.

Promotion requires:

- independent contract tests;
- replay/chaos evidence;
- exact-head CI gates;
- bounded pilot;
- no weakened authority boundary;
- explicit production-enablement change separate from this design;
- rollback path.

Conductor specifically must remain shadow until its scheduling/state output has been compared against real AppLab behavior and the pilot gates in the companion document are met.

## 17. Success definition

v5.4 is successful when AppLab can eventually operate as a persistent control plane for the app portfolio while preserving the v5.3.5 trust model.

The desired operational outcome is:

```text
change arrives
 -> event persisted
 -> operation created
 -> correct existing plan selected
 -> work queued without cross-repo cancellation
 -> compatible worker assigned
 -> infra failure recovered safely
 -> evidence persisted and correlated
 -> deterministic verdict preserved
 -> current state visible immediately
```

The primary performance win should come from lower orchestration/startup latency and better reuse/capacity management, not from prematurely deleting verification coverage.
