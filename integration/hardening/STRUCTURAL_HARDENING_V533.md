# AppLab v5.3.3 — Structural Hardening & Contract Test Foundation

## Purpose

v5.3.3 reduces structural risk before AppLab attempts coverage-reducing delta
execution. It does not create a new planning, runtime, release or certification
authority.

The trusted boundary remains:

```
Target source -> Build job -> isolated APK contract -> Trusted verifier
```

## Production-module decomposition

The patch moves non-runtime contract/test weight out of saturated modules while
preserving their public entrypoints:

- `planner_feedback.py` delegates schema, digest, compatibility and hint
  validation primitives to `planner_feedback_contract.py`;
- `studio_snapshot.py` delegates its large deterministic fixture to
  `studio_snapshot_self_test.py`;
- `evidence_graph.py` delegates its implementation-local fixture to
  `evidence_graph_self_test.py`;
- version-specific heavy audit assertions move from the audit orchestrator to
  `audit_contract_hardening.py`.

The extraction is structural. Smart Test Plan remains the sole FAST/FULL
selection authority, Evidence Graph remains evidence/advisory infrastructure,
and Production Certification remains the only certification authority.

## Independent contract coverage

v5.3.3 adds tests outside the implementation modules:

- `tests/contracts/planning_feedback_pipeline_test.py` exercises the chain
  Evidence Graph -> planner feedback -> FAST/FULL promotion -> lane telemetry ->
  execution identity and verifies fail-closed behavior for tampering, stale
  baselines and incomplete source analysis;
- `tests/contracts/workflow_structure_test.py` parses every GitHub Actions
  workflow as YAML, validates job structure, requires external actions to be
  pinned to a 40-character SHA and checks workflow-authority cleanup.

These tests complement module self-tests rather than replace them.

## Maintainability budgets

Growth ceilings now also cover the previously unbounded high-risk surfaces:

- Evidence Graph;
- versioned audit contracts;
- AppLab Studio frontend shell;
- AppLab frontend root;
- external Flutter and native Android runners.

The decomposed planner feedback and Studio modules receive materially lower
ceilings so future feature work must extend through focused modules rather than
regrowing the monoliths.

## Workflow authority cleanup

- `verify-flutter.yml` is explicitly classified as a public compatibility
  wrapper around the canonical Flutter runner and no longer exposes a stale
  v0.6.3 job label.
- `apk-emulator-smoke.yml` is explicitly classified as diagnostic-only.
- the project-specific `camperboss-16c-build-once.yml` one-off workflow is
  removed from AppLab core.
- `CANONICAL_WORKFLOWS.md` no longer claims that True Autonomous Review is
  implemented/output as v4.0.2.

## Cache/provenance impact

`planner_feedback_contract.py` is part of the central contract fingerprint,
core domain fingerprint and Repo Watcher invalidation set. A change to the
extracted contract therefore cannot silently reuse evidence produced under
different planner-feedback semantics.

## Explicit non-goals

v5.3.3 does **not**:

- reduce specialist-lab coverage;
- skip runtime based on absence of graph impact;
- merge Flutter and native runners;
- add a new evidence schema registry;
- change certification authority.

Those remain follow-up work after this structural foundation is proven green.
