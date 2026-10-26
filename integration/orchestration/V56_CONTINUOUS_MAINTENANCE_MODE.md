# AppLab v5.6 — Roadmap Fast + Continuous Maintenance

Status: ACTIVE CROSS-CUTTING EXECUTION MODE

## Goal

AppLab must improve quickly enough to accelerate the rest of the App Factory.
Roadmap delivery and maintenance analysis therefore run as two independent lanes.

## Lane 1 — ROADMAP_FAST

The roadmap lane optimizes for short time-to-merge while preserving trustworthy
evidence.

Rules:

- keep each roadmap change small and independently mergeable;
- perform the minimum preflight needed to catch obvious contract/workflow errors;
- open the PR early;
- use exact-head validation before merge;
- do not pull unrelated maintenance work into the active roadmap PR;
- only BLOCKING_NOW or FIX_CURRENT_STEP findings may stop the current roadmap step.

The roadmap lane does not weaken assertions, trust boundaries or certification
rules to obtain faster green checks.

## Lane 2 — CONTINUOUS_MAINTENANCE

The maintenance lane runs independently from active product development.

It consumes existing Repo Watcher history and explicit findings, deduplicates
signals and persists a maintenance queue with four lanes:

- BLOCKING_NOW — P0/P1 or critical trust/security/data-integrity finding;
- FIX_CURRENT_STEP — a non-P0/P1 problem proven to have been introduced by the
  active roadmap step;
- BACKGROUND_MAINTENANCE — real technical debt, flakiness, regression or
  diagnostic work that must not stall unrelated roadmap delivery;
- FUTURE — optional refactors, product opportunities and advisory ideas.

Background sweeps are evidence-only. They do not launch an emulator merely
because the system is idle.

## Automatic execution

.github/workflows/continuous-maintenance.yml runs:

1. after AppLab Repo Watcher completes;
2. once per hour as a lightweight idle sweep;
3. on explicit manual dispatch;
4. when the maintenance implementation itself changes on main.

The workflow restores central watcher history, restores the previous maintenance
queue, updates/deduplicates the queue and persists the result for the next run.

This lets AppLab continue observing the App Factory when no interactive ChatGPT
session is active.

## Escalation contract

A finding blocks roadmap progress only when one of these is true:

- severity is P0 or P1;
- category is TRUST_BOUNDARY;
- category is FALSE_PASS;
- category is ARTIFACT_IDENTITY;
- category is DATA_LOSS;
- category is CRITICAL_SECURITY;
- it is explicitly proven to have been introduced by the current roadmap step.

Everything else is retained without mutating the active roadmap PR.

## Authority boundary

Continuous Maintenance is not a verifier or release authority.

It cannot:

- mint PASS;
- mint CERTIFIED;
- reduce Smart Test Plan coverage;
- change release-artifact identity;
- reinterpret emulator evidence as physical-device evidence;
- mutate the active roadmap PR.

Runtime/emulator, physical-device, distribution/store and certification evidence
remain separate.

## Cost model

Idle analysis should prefer already-produced evidence and history.

Expensive runtime work remains event/risk driven:

- no change / idle -> evidence-only maintenance;
- repository change -> Smart Test Plan / watcher path;
- elevated risk -> appropriate runtime verification;
- release/certification -> trusted full release path.

The objective is to spend compute where it changes confidence, not to keep
emulators busy continuously.

## Artifacts

- policy: integration/orchestration/contracts/continuous-maintenance-v56.json
- engine: scripts/continuous_maintenance_v56.py
- workflow: .github/workflows/continuous-maintenance.yml
- persisted queue: .applab-maintenance/maintenance-queue.json
- human summary: .applab-maintenance/maintenance-queue.md

The persisted queue is operational evidence, not a second Product Bible or
Roadmap.
