# AppLab v6.0 — Closed-Loop Agentic Engineering

Status: **PLANNED / IMPLEMENTATION PROGRAM**  
Factory baseline: `App-Factory-Core@ed6466e774a28e95f9f371cd56bbf7278428776a`

## 1. Why v6

AppLab already owns durable orchestration, exact-artifact verification, adaptive FAST/FULL planning, evidence graphs, failure intelligence, journey-aware execution, warm-runtime routing, watchdogs and proposal-only triage.

The missing capability is the bounded engineering loop:

```
evidence -> diagnosis -> localization -> modification -> test
        -> new evidence -> bounded correction -> draft PR
```

v6 must compose existing capabilities rather than introduce a second orchestration framework.

## 2. Unified work model — v6.0A

Canonical graph:

```
Trigger
  -> WorkItem
  -> EvidenceContext
  -> Decision
  -> ActionPlan
  -> Attempt
  -> ObservedEvidence
  -> Verdict
  -> NextAction | Stop
```

Every WorkItem records:
- repository and exact source SHA;
- baseline SHA;
- authority envelope;
- allowed tools and paths;
- risk;
- acceptance criteria;
- attempt/runtime/change budgets;
- required evidence;
- rollback;
- terminal conditions.

Durable Brain remains the orchestration source. Existing Event/Operation/Attempt/EvidenceRef data is adapted into this graph rather than duplicated.

Acceptance:
- versioned schema;
- deterministic state validator;
- restart-safe durable projection;
- immutable attempt/evidence history;
- idempotent replay;
- no change to PASS/CERTIFIED authority.

## 3. Causal Repo Investigator — v6.0B

Inputs, in descending trust:
1. exact diff and changed hunks;
2. failing test/runtime stack trace;
3. logs and specialist-lab evidence;
4. dependency/reverse-dependency graph;
5. code search and ownership/surface mapping;
6. Git history and prior fixes;
7. compressed episodic memory.

Output:
- ranked candidate files with evidence confidence;
- explicit causal links;
- required regression targets;
- unresolved uncertainty;
- stop/escalation decision.

LLM synthesis may explain or propose a patch, but deterministic evidence constructs the causal graph.

Acceptance:
- candidate files no longer default to an empty list for supported deterministic failures;
- confidence trace is inspectable;
- UNKNOWN remains fail-closed;
- regression corpus covers false localization and truncated evidence.

## 4. Bounded Autonomous Fix Worker — v6.0C

Default capability envelope:
- isolated ephemeral workspace;
- new repair branch only;
- max 5 files;
- max 250 changed lines;
- max 2 attempts;
- exact source SHA mandatory;
- protected paths denied;
- workflow/policy/release edits denied by default;
- secrets unavailable;
- tests/assertions cannot be weakened to obtain green.

Worker sequence:
```
exact failing SHA
 -> isolated workspace
 -> candidate-file validation
 -> bounded patch
 -> code-hygiene sweep
 -> focused regression
 -> diff audit
 -> evidence bundle
 -> publish repair branch only if coherent
```

No merge/release authority.

## 5. Verify–Repair Loop — v6.0D

Loop:
```
FAIL
 -> Investigator
 -> Fix Worker
 -> focused tests
 -> AppLab FAST
 -> new evidence
 -> PASS | second bounded attempt | STOP
```

Terminal conditions:
- UNKNOWN classification;
- scope expansion;
- protected/security-sensitive path;
- assertion weakening required;
- same signature after second attempt;
- unexplained failure mutation;
- evidence/source/artifact identity loss.

Failed attempts remain immutable evidence and are never rewritten as PASS.

## 6. Autonomous PR Steward — v6.0E

Allowed:
- create draft PR;
- append bounded repair commits;
- update PR evidence summary;
- react to fresh CI/review findings through the Investigator;
- retrigger exact-head verification through existing safe mechanisms;
- mark own PR superseded only with ancestry/equivalence evidence.

Forbidden:
- approve own PR;
- dismiss/resolve external findings unilaterally;
- merge;
- release;
- alter branch protection.

## 7. Agent Memory & Policy Learning — v6.0F

No new generic memory database.

Build a compressed retrieval view over existing history, durable store, Evidence Graph, planner feedback and failed attempts.

Example episodic record:
```
failure signature
repository/surface
prior occurrences
successful repair pattern
required regressions
failed approaches
evidence confidence
source attempt refs
```

Learning may rank strategies. It may not self-modify guardrails or protected policy.

## 8. Self-Dogfooding Throughput — v6.0G

### Emulator Self Test
Split internal coverage into journey/lab units:
- runtime-core
- maestro-core
- lifecycle
- network
- persistence
- configuration
- resource-pressure
- background
- storage
- upgrade
- certification-contract

Use the existing Smart Test Plan/journey selection for FAST while FULL keeps depth unchanged.

### Autonomous Review
Build an Evidence DAG:
- node input fingerprint;
- content-addressed output;
- safe reuse when exact inputs are unchanged;
- parallel fan-out for independent producers;
- deterministic aggregate.

### CI
Keep umbrella required checks but make sublanes path-aware. Avoid runtime work for unrelated docs/config/script changes when the existing risk authority says it is unnecessary.

## 9. Sensor Mesh — v6.0H

Registered producer -> real sensor -> risk-triggered execution -> normalized evidence.

First wave:
- scrcpy physical capture/QA cockpit integration;
- LeakCanary diagnostic lane;
- Semgrep;
- Trivy.

Second wave:
- MobSF;
- Hetty/network replay when API/sync evidence justifies it.

Sensors are evidence producers only and cannot mint PASS/CERTIFIED.

## 10. Agentic Operations Studio — v6.0I

Expose:
- WorkItems;
- queue/ownership;
- decisions;
- attempts;
- evidence;
- repair budget consumption;
- stop reasons;
- PR state;
- cost/runtime;
- authority envelope;
- blockers and human-decision points.

Studio is an operational view, not a second source of truth.

## 11. Program order

1. v5.9.1 Truth & Debt Closure
2. v6.0A Unified Agent Work Graph
3. v6.0B Causal Repo Investigator
4. v6.0C Bounded Autonomous Fix Worker
5. v6.0D Verify–Repair Loop
6. v6.0G Self-Dogfooding Throughput
7. v6.0E Autonomous PR Steward
8. v6.0F Agent Memory / Policy Learning
9. v6.0H Sensor Mesh / Physical QA
10. v6.0I Agentic Operations Studio

## 12. Global invariant

v6 is successful only if autonomy increases while the blast radius remains bounded and evidence becomes more inspectable, not less.

```
proposal-only
 -> branch writer
 -> self-verifying repair agent
 -> draft PR steward
```

Auto-merge and autonomous release remain outside this program.
