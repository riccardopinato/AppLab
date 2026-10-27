# AppLab v6.0H — Sensor Mesh

Status: implementation candidate; exact-head validation pending.

## Purpose

v6.0H turns the approved v5.6E hardening pilots into a deterministic, risk-triggered sensor routing layer. It does not create a second verifier and it cannot mint PASS or CERTIFIED.

## Producers

First wave: scrcpy physical capture, LeakCanary diagnostics, Semgrep source security, and Trivy dependency/container security. Second wave: MobSF mobile analysis and Hetty network capture/replay when the current plan contains the corresponding mobile/API/sync risk.

Every selected sensor is bound to an exact repository and 40-hex source SHA. Artifact-sensitive producers require an exact artifact SHA-256 before their evidence can be normalized.

## Authority

All normalized records remain EVIDENCE_ONLY. Sensor output cannot replace trusted runtime evidence, claim store/distribution proof, alter release-artifact identity, weaken tests, expand autonomous edit authority, or mint PASS/CERTIFIED. Missing or unavailable sensor evidence remains missing evidence; it is never converted to success.

## Planning

`scripts/sensor_mesh_v60h.py` consumes the current execution/risk plan plus project capabilities and produces a deterministic plan with selected sensor IDs and reasons. The reusable `.github/workflows/sensor-mesh.yml` materializes identity-bound inputs and publishes the plan as an artifact. It deliberately plans/routs sensors rather than silently installing unpinned third-party scanners.

The existing `advanced_hardening_v56e.py` normalizer remains the evidence boundary and now registers Hetty alongside MobSF for the second wave.

## Validation

Contract coverage proves exact-source identity, risk-triggered selection, physical-device gating, artifact binding, deterministic output, and evidence-only authority. CI compiles and self-tests the planner and runs its contract suite. The planner, contract and workflow are included in the contract fingerprint and maintainability budget.
