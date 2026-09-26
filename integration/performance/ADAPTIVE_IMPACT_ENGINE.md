# AppLab v0.9.0 — Adaptive Impact Engine

## Purpose

The Adaptive Impact Engine is the first decision point in a FAST pipeline. It runs immediately after target checkout and trusted-baseline retrieval, before toolchain setup, dependency resolution, static checks, APK build or emulator startup.

Its contract is fail-safe: inability to prove that reduced coverage is safe produces `FULL_RUNTIME`.

## Inputs

- target repository checkout and resolved HEAD;
- trusted watcher baseline SHA and baseline-identity flag;
- requested mode: FAST, FULL or CERTIFICATION;
- recent project/lab failure summary;
- source graph derived from tracked files.

## Evidence model

The serialized `analysis-plan.json` records baseline/head identity and ancestry, changed-file status, additions/deletions/churn, content-domain signals, reverse-dependency impact, risk/confidence, selected labs with reasons, static targets, Gradle modules, effective lane and shadow-FULL recommendation.

The plan is produced before the build and copied into the isolated build contract. Trusted verification validates that exact plan rather than recalculating a different one after expensive work has already run.

## Lane semantics

### NO_RUNTIME_CHANGE

No runtime-affecting source changed. AppLab emits a source-only PASS and records the trusted baseline whose runtime evidence is inherited. Runtime gates remain SKIPPED.

### STATIC_ONLY

Only tests/static-analysis/CI surfaces changed. Static checks run. No APK/emulator result is fabricated.

### FAST_RUNTIME

Core runtime verification plus impact-selected specialist labs.

### FULL_RUNTIME

Complete runtime lab set. This is also the safe fallback for uncertain FAST planning.

### CERTIFICATION

Production certification. Adaptive shortcuts do not reduce certification coverage.

## Failure history

Watcher history is matched by repository, ref, history key, engine and configuration fingerprint before it may define a FAST baseline. Failure counts in affected labs raise risk and can force historically unstable labs into subsequent FAST plans. Shadow-calibration false negatives also increase future sampling/risk.

## Domain fingerprints

The verification contract has a core fingerprint plus specialist-domain fingerprints. A result stores the fingerprint derived from the domains actually selected by its plan. This improves cache reuse while preserving invalidation when any relevant verifier implementation changes.

## Safety invariants

1. A baseline that is not identity-matched is untrusted.
2. A baseline that is not an ancestor of HEAD cannot drive FAST.
3. Large or unsupported diffs escalate rather than truncate silently.
4. Low planner confidence increases verification.
5. SKIPPED is never treated as PASS.
6. Source-only results never claim a newly tested APK.
7. FAST/FULL never grant production certification.
8. The trusted verifier consumes only isolated contract artifacts and never checks out target source.
