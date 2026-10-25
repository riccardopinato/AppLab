# AppLab v5.4 — Conductor Shadow Pilot and Warm Worker Design

Status: **DESIGN-ONLY / NOT ACTIVE**

This document defines how AppLab can evaluate durable orchestration and warm trusted-runtime workers without changing current production authority or activating new infrastructure.

## 1. Purpose

Two different problems are addressed here:

1. **Conductor shadow pilot** — determine whether a durable workflow engine can reproduce AppLab scheduling/state behavior safely.
2. **Warm trusted-runtime worker pilot** — reduce runner/emulator startup cost without weakening the existing untrusted-build -> trusted-verifier boundary.

They are intentionally separated. AppLab may adopt one without the other.

## 2. Conductor is a shadow orchestrator first

The initial Conductor role is:

```text
MIRROR INPUT
   |
   v
SHADOW WORKFLOW
   |
   v
SHADOW STATE / EXPECTED DAG
   |
   v
COMPARE WITH REAL APPLAB
```

It has:

- no target repository write token;
- no release/store token;
- no production certification capability;
- no worker-dispatch secret;
- no permission to cancel GitHub Actions;
- no authority to alter Smart Test Plan output;
- no authority to write trusted AppLab evidence.

The shadow workflow can consume copies of normalized control-plane records and existing AppLab outputs.

## 3. Why Conductor is being evaluated

The evaluated patterns are:

- durable workflow execution;
- persisted state through process restart;
- retry and timeout semantics;
- schedules and event-driven starts;
- `SWITCH` branching;
- `DO_WHILE` bounded loops;
- `FORK_JOIN` / dynamic fan-out;
- sub-workflows;
- pause/resume/cancel;
- worker decoupling;
- workflow versioning;
- inspectable task history.

The pilot is not an endorsement of every Conductor AI/LLM feature.

## 4. Shadow workflow boundary

A v5.4 shadow workflow should conceptually model:

```text
normalize event
  -> load exact target identity
  -> reference existing Smart Test Plan output
  -> compute queue decision
  -> model worker capability request
  -> model expected dispatch DAG
  -> model bounded retry/recovery
  -> wait for real AppLab terminal result
  -> compare predicted orchestration with actual run
  -> emit shadow comparison record
```

The workflow does not run tests.

## 5. Shadow comparison record

Proposed non-authoritative artifact:

```json
{
  "schema_version": 1,
  "record_type": "APPLAB_CONDUCTOR_SHADOW_COMPARISON",
  "authority": "NONE_SHADOW_ONLY",
  "repository": "owner/repo",
  "resolved_sha": "40hex...",
  "applab_sha": "40hex...",
  "event_id": "evt_...",
  "operation_id": "op_...",
  "shadow_workflow_version": 1,
  "identity_match": true,
  "lane_match": true,
  "selected_labs_digest_match": true,
  "queue_decision_match": true,
  "supersession_decision_match": true,
  "expected_terminal_state_match": true,
  "unexpected_side_effects": 0,
  "notes": []
}
```

This should remain outside trusted evidence authority until a later explicit registry decision.

## 6. Pilot phases

### Phase S0 — Offline replay only

Inputs:

- synthetic Event/Operation fixtures;
- historical AppLab watcher results;
- historical failure/retry cases.

Goals:

- validate workflow syntax/versioning;
- validate deterministic branching;
- test restart/recovery;
- test queue/supersession decisions;
- verify no external side effects.

No production events are consumed.

### Phase S1 — Live metadata mirror, no dispatch

Inputs:

- copies of normalized live events;
- copies of actual Smart Test Plan/results.

Goals:

- compare identity and plan mapping;
- compare queue decisions;
- measure event loss/duplication;
- observe workflow restart behavior.

Conductor still has no dispatch credentials.

### Phase S2 — Shadow scheduling against worker inventory

Inputs additionally include:

- read-only worker capability snapshots;
- queue capacity snapshots.

Goals:

- compare chosen theoretical worker/fallback with actual execution;
- validate fairness/backpressure model.

Still no dispatch.

### Phase S3 — Non-authoritative dispatch candidate

This phase is **not part of the current design-only implementation**.

A later explicit change may allow Conductor to dispatch a bounded non-certification pilot while authoritative verdicts still come from existing AppLab components.

Production activation requires separate approval and gates.

## 7. Conductor pilot acceptance gates

The pilot should not be promoted from shadow merely because it is operational.

Minimum evidence before any dispatch authority is considered:

- zero cases where repository/SHA/AppLab identity differs from the real AppLab operation;
- zero cases where shadow logic proposes a weaker lane or fewer labs than the authoritative Smart Test Plan;
- zero cross-repository cancellation decisions;
- zero normal-verification attempts to supersede protected certification/physical/manual work;
- deterministic replay of the same input/workflow version;
- successful recovery after orchestrator restart during each non-terminal state class;
- bounded retry behavior demonstrated for infrastructure failures;
- no duplicate side effects (shadow should have none);
- queue fairness/backpressure tests pass;
- explicit rollback path tested;
- independent contract tests green.

A future pilot should define a minimum real sample size before promotion rather than using one or two successful runs as proof.

## 8. Failure model for Conductor

Conductor outage:

- new shadow decisions stop;
- current production AppLab remains unaffected during shadow phases;
- events remain in the durable Event store;
- replay occurs after recovery.

Conductor state corruption or incompatible workflow version:

- affected shadow Operation becomes BLOCKED;
- no production AppLab verdict changes.

Workflow bug:

- comparison mismatch is evidence against promotion;
- never auto-correct the authoritative AppLab result to match the shadow.

## 9. Workflow versioning rule

Every Conductor workflow execution is pinned to an immutable workflow version.

A newer workflow definition:

- does not rewrite an in-flight execution;
- does not reinterpret completed shadow evidence;
- receives a new version identity;
- must pass replay/contract tests before use.

The workflow version participates in shadow comparison records.

## 10. No LLM in the critical shadow loop

The first pilot should contain no LLM-dependent branch that affects:

- queue priority;
- supersession;
- retryability;
- worker eligibility;
- test lane;
- verdict.

If an LLM is later added for diagnosis, its output is advisory and stored separately.

---

# Warm trusted-runtime workers

## 11. Objective

Reduce:

- hosted runner acquisition time;
- Android SDK setup;
- Maestro/tool setup;
- emulator cold-start time;

while preserving:

```text
Target source
   -> isolated/untrusted build
   -> APK contract
   -> trusted runtime verifier
```

The warm worker is on the **trusted runtime side only**.

## 12. What must never run on the warm trusted host

- target repository build scripts;
- arbitrary `prepare_command`;
- target Gradle/Flutter build;
- target-authored shell commands;
- target pull-request code outside the installed APK runtime;
- arbitrary event payload commands.

The worker downloads only trusted AppLab code and validated build artifacts/contracts required for runtime verification.

## 13. Worker architecture

```text
                     +----------------------+
                     | Durable Brain        |
                     +----------+-----------+
                                |
                             lease
                                |
                                v
+------------------------------------------------------+
| Warm Trusted Android Worker                          |
|                                                      |
| pinned AppLab verifier                               |
| Android SDK / platform tools                         |
| Maestro / trusted runtime tooling                    |
| KVM                                                  |
| read-only AVD base templates                         |
| worker agent / heartbeat                             |
|                                                      |
|   base template                                      |
|        |                                             |
|        +--> disposable clone for operation A         |
|        +--> disposable clone for operation B later   |
+------------------------------------------------------+
```

Only one trust-sensitive lease is active per initial worker.

## 14. Worker lifecycle

States:

```text
STARTING
  -> AVAILABLE
  -> LEASED
  -> SCRUBBING
  -> AVAILABLE

failure paths:
LEASED/SCRUBBING
  -> UNHEALTHY
  -> QUARANTINED
  -> DRAINING/OFFLINE
```

A worker cannot return directly from uncertain failure to AVAILABLE.

## 15. Capability advertisement

A worker advertises:

- exact AppLab SHA;
- Android SDK tools version;
- supported API levels;
- available AVD profiles;
- KVM state;
- Maestro version;
- host architecture;
- free disk/memory;
- base snapshot digest;
- network mode capabilities;
- whether screen/video capture is available;
- optional future physical-device capabilities.

The Brain matches the Operation's required runtime profile against this advertisement.

## 16. Lease protocol

Proposed sequence:

1. Brain atomically reserves worker.
2. Worker acknowledges lease and operation identity.
3. Worker verifies its AppLab/tool/base-image identity.
4. Disposable AVD clone is created/restored.
5. APK contract is fetched.
6. Existing trusted build-contract validation runs.
7. APK SHA-256 is recomputed.
8. Runtime verification executes.
9. Evidence uploads complete.
10. AVD clone is destroyed.
11. host/process/temp-directory scrub runs.
12. worker reports cleanup result.
13. lease is released only if cleanup is proven.

Lost heartbeat:

- Brain marks lease `UNKNOWN`;
- no second worker is immediately allowed to duplicate protected/non-idempotent work until operation ownership is reconciled;
- original worker enters quarantine if it later returns with uncertain state.

## 17. AVD warm strategy

Preferred initial design:

- keep **read-only base templates** per supported API/profile;
- create/restore a disposable copy for each operation;
- never reuse app data from a prior operation;
- clear logcat before runtime evidence windows as current v5.3.5 already requires;
- destroy or cryptographically/structurally verify reset after use.

The goal is fast environment creation, not stateful emulator reuse.

## 18. Worker security

Minimum controls:

- dedicated host/user;
- no persistent target repository credentials;
- no broad GitHub write token;
- outbound network constrained where practical;
- secrets exposed only for the specific trusted adapter that requires them;
- no target-controlled Docker socket;
- no target-controlled privileged container;
- evidence/object credentials scoped to operation paths;
- host filesystem partitions/quotas to avoid evidence exhaustion;
- worker agent accepts structured commands only;
- command allowlist/versioned protocol.

## 19. Worker quarantine triggers

Examples:

- ADB/emulator state cannot be reset confidently;
- KVM/device becomes unstable repeatedly;
- disk fills below safety threshold;
- AppLab SHA/tool version mismatch;
- base snapshot digest mismatch;
- evidence upload reports hash mismatch;
- host loses time synchronization materially;
- cleanup script fails;
- unexpected process remains from prior operation;
- worker agent state differs from Brain lease state.

Quarantine is fail-closed and does not imply application failure.

## 20. GitHub Actions as burst/fallback

Warm workers should not make GitHub Actions obsolete.

Dispatch policy:

```text
eligible warm worker available?
  yes -> warm runtime
  no  -> protected/normal work may use GitHub burst budget
          low-priority work may remain queued
```

Benefits:

- resilience if local/self-hosted capacity is offline;
- elastic spikes;
- independent comparison baseline during pilot;
- easier rollback.

## 21. Warm-worker equivalence pilot

The first pilot runs a bounded set of operations both ways when cost allows:

```text
same APK contract
       |
       +--> existing GitHub trusted runtime
       |
       +--> warm trusted runtime shadow
```

Compare:

- package/APK identity;
- selected labs;
- runtime outcome;
- specialist-lab outcomes;
- visual/runtime evidence;
- performance measurements with environment caveat;
- evidence hashes where deterministic;
- infrastructure failure class;
- wall-clock timing.

The warm path cannot become primary merely because it is faster.

## 22. Warm-worker promotion gates

Before real primary dispatch:

- zero APK/source identity mismatch;
- zero cross-run app-data contamination in isolation tests;
- zero evidence-authority divergence attributable to worker reuse;
- cleanup/quarantine contract passes chaos tests;
- worker restart/recovery passes;
- GitHub fallback tested;
- capability mismatch fails closed;
- measurable reduction in startup or wall-clock time;
- no weakening of current trusted verifier assertions.

## 23. scrcpy future integration point

scrcpy is a good fit for **physical-device evidence and operator/debug cockpit**, not a requirement for the initial warm emulator worker.

Future physical worker:

```text
Physical Android device
  + ADB trusted controls
  + scrcpy recording/control
  + AppLab scenario execution
  + evidence bundle
```

Video/screen evidence must remain explicitly physical-device evidence and exact-artifact bound.

## 24. LeakCanary future integration point

LeakCanary should be evaluated as a separate debug/instrumented memory diagnostic lane.

It must not alter the exact release APK and then masquerade as release-artifact verification.

Possible future flow:

```text
source SHA
 -> dedicated diagnostic build
 -> instrumentation/UI journey
 -> LeakCanary / heap-growth evidence
 -> ADVISORY memory finding initially
```

Promotion to a blocking regression rule requires calibration and a separate contract.

## 25. Recommended infrastructure topology for pilot

A minimal future pilot can be:

```text
Event Gateway
   |
Postgres-compatible durable store
   |
Durable Brain service
   |
Conductor shadow service
   |
read-only comparison

separate:
one warm trusted Android worker
   |
object/evidence storage

GitHub Actions remains production executor/fallback
```

This minimizes blast radius.

## 26. Rollback model

During shadow:

- stop shadow consumers;
- production AppLab unchanged.

During a future event-gateway pilot:

- disable event-driven dispatch;
- retain hourly watcher reconciliation.

During warm-worker pilot:

- mark worker class DRAINING/OFFLINE;
- route all work to GitHub Actions.

No rollback requires changing verification semantics.

## 27. Final design rule

Conductor and warm workers are infrastructure optimizations.

They are successful only if they make AppLab more continuous and faster **without becoming a new source of truth for application correctness**.
