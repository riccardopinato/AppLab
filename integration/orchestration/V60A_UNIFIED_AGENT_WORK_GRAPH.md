# AppLab v6.0A — Unified Agent Work Graph

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Scope

v6.0A introduces one durable agent work model above the existing v5.4 Durable
Brain. It does **not** introduce a second orchestrator, a second database or a
new verification authority.

Canonical graph:

```
Trigger
  -> WorkItem
  -> Decision
  -> Action
  -> Attempt / EvidenceRef
  -> WorkVerdict
  -> Next Action | Stop
```

Existing v5.4 records remain canonical for provider events, Operations,
Attempts, EvidenceRefs, queueing and transition history. v6.0A adds the agentic
projection and appends its records to the **same SQLite durable control-plane
file**.

## Files

- `integration/orchestration/contracts/agent-work-graph-v1.json`
- `scripts/agent_work_graph_v60a.py`
- `tests/contracts/agent_work_graph_v60a_test.py`

## Authority envelope

A WorkItem carries its own explicit capability envelope.

Supported capabilities can include repository/evidence reads, focused tests,
AppLab FAST/FULL, bounded code edit and future draft-PR stewardship.

The following remain mandatory denials in every v1 WorkItem:

- WRITE_MAIN
- WRITE_FACTORY_CORE
- READ_SECRETS
- EDIT_WORKFLOW
- EDIT_BRANCH_PROTECTION
- RELEASE
- WEAKEN_TESTS
- SELF_APPROVE
- SELF_MERGE

Security-risk WorkItems cannot enable autonomous code edit.

## Budgets

Contract ceilings:

- max files: 5
- max changed lines: 250
- max repair attempts: 2
- max agent actions: 24

v6.0A does not execute repair. These budgets become enforceable inputs for
v6.0C and v6.0D.

## Durable semantics

The work graph adds append-only:

- decisions;
- actions;
- action-to-attempt links;
- work verdicts;
- WorkItem transitions.

WorkItem identity is immutable. Current state is a rebuildable projection over
append-only transitions. Reopening the same v5.4 SQLite database reconstructs
the same WorkItem state.

## Verification authority

`APPLAB_WORK_VERDICT` is strictly `ORCHESTRATION_ONLY`.

It can say:

- CONTINUE;
- STOP;
- COMPLETE.

It can never mint:

- PASS;
- CERTIFIED;
- physical-device proof;
- distribution/store proof.

Trusted runtime and Production Certification remain unchanged.

## Acceptance

- [x] versioned schema;
- [x] deterministic validators;
- [x] v5.4 Operation -> WorkItem adapter;
- [x] same durable SQLite substrate;
- [x] append-only decision/action/attempt-link/verdict/transition history;
- [x] action -> durable Attempt -> EvidenceRef lineage enforcement;
- [x] restart-safe projection;
- [x] idempotent replay;
- [x] explicit authority envelope;
- [x] bounded budgets;
- [x] security-risk code-edit denial;
- [x] no PASS/CERTIFIED authority;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] merged on top of v5.9.1.

## Code hygiene

No v5.4 Event/Operation/Attempt/EvidenceRef path is replaced by this step.
Those records remain intentional owners of their existing semantics. v6.0A
adds only the missing agent-work projection and therefore removes no historical
or compatibility path.
