# AppLab Roadmap

Current production baseline: **v3.3.0 — User Journey Intelligence**

## Product rule

AppLab optimizes for the shortest verification path that preserves trustworthy
evidence. Reduced work is allowed only when impact evidence is sufficiently
strong. Missing, contradictory, oversized or low-confidence evidence must
increase coverage and may never silently become PASS.

The security boundary remains:

```
Target source -> Build job -> isolated APK contract -> Trusted verifier
```

FAST/FULL results are not production certification. Only CERTIFICATION can
publish a certified release artifact.

## Completed

### v3.3.0 — User Journey Intelligence

- [x] Add bounded multi-step Safe Journey Crawler to trusted non-FAST verification.
- [x] Reuse the existing safe-action allow/deny policy.
- [x] Reconstruct runtime states and transitions from UI hierarchy evidence.
- [x] Replay safe paths deterministically before deeper exploration.
- [x] Bound journey depth, state count and transition count.
- [x] Compare runtime journeys with the static Product Flow Graph.
- [x] Surface no-change actions, loops and safe dead-end candidates conservatively.
- [x] Expose observed journeys and review signals in AppLab Studio.
- [x] Preserve Trusted Evidence Manifest and release-verdict boundaries.


### v3.2.0 — Evidence Confidence & Contradiction Engine

- [x] Normalize product evidence into one deterministic claim graph.
- [x] Classify claims as CONFIRMED / CORROBORATED / CONTRADICTED / UNVERIFIED / STALE.
- [x] Reconcile Product Contract, Feature Truth, Product Flow, trusted UI hierarchy and runtime states.
- [x] Detect explicit contract/implementation and static/runtime contradictions.
- [x] Preserve contradictory sources rather than deleting losing evidence.
- [x] Surface evidence-state counts and top contradictions in AppLab Studio.
- [x] Make contradictions influence Autonomous Review without becoming release failures.
- [x] Preserve non-numeric confidence semantics and certification authority.


### v3.1.0 — True Autonomous App Review

- [x] Resolve the target once to an immutable SHA.
- [x] Auto-discover and build through Universal Project Runner.
- [x] Execute Trusted APK Verifier and consume same-run evidence.
- [x] Validate repository/SHA/package/run binding before product review.
- [x] Use UI hierarchy for runtime product/state observations.
- [x] Classify Product Contract claims semantically.
- [x] Require strong static/runtime evidence relations.
- [x] Validate the complete autonomous chain end-to-end.

### v3.0.1 — Trusted Evidence Chain

- [x] Generate Trusted Evidence Manifest inside the isolated verifier.
- [x] Bind runtime evidence to repository, SHA, package id and workflow run.
- [x] Hash all runtime evidence files with SHA-256.
- [x] Reject altered, missing, extra or mismatched evidence.
- [x] Reject target-authored runtime evidence in the legacy v3 workflow.

### v3.0.0 — Autonomous App Review

- [x] Orchestrate App Intelligence, Behavioral Product, State/Edge, Calibration, Contract and Decision Brief.
- [x] Reuse the existing Autonomous Audit Plan for specialist-lab selection.
- [x] Emit advisory review state without creating a release verdict.
- [x] Return EVIDENCE_INCOMPLETE when trusted runtime evidence is absent.
- [x] Publish a reusable/manual GitHub workflow.
- [x] Surface autonomous review evidence in AppLab Studio.
- [x] Preserve FAST/FULL/CERTIFICATION as independent authoritative gates.

### v2.11.0 — Decision & Opportunity Brief

- [x] Compress evidence into FIX_NOW, VERIFY_NEXT, IMPROVE and NO_ACTION.
- [x] Preserve source, evidence basis and finding provenance for every action.
- [x] Prevent automatic feature generation and opaque scoring.

### v2.10.0 — Product Contract Audit

- [x] Compare bounded product documentation with implementation provenance.
- [x] Distinguish promised, implemented, runtime-reachable and runtime-verified capability states.
- [x] Treat completed roadmap checkboxes as claims rather than automatic truth.
- [x] Flag promised capabilities without bounded implementation evidence.
- [x] Flag implemented capabilities lacking runtime verification.

### v2.9.0 — Evidence Calibration Engine

- [x] Reconcile Product Consistency with runtime Behavioral and Edge-State evidence.
- [x] Distinguish runtime-confirmed, corroborated, static-only and contradicted findings.
- [x] Suppress contradicted static findings for action without deleting their evidence.
- [x] Preserve certification independence and avoid synthetic scores.

### v2.8.0 — State & Edge-Case Lab

- [x] Aggregate existing Network, Persistence, Configuration, Resource, Storage, Background and System evidence.
- [x] Track normal/offline/restart/configuration/process-death/storage/background/permissions states.
- [x] Detect bounded empty/loading/error/auth/permission-denied observations when evidence exists.
- [x] Mark applicable-but-unobserved states as REVIEW, never PASS.

### v2.7.0 — Behavioral Product Lab

- [x] Compare static Product Flow surfaces with Safe Interaction Crawler evidence.
- [x] Record runtime controls, state transitions and conservative interaction failures.
- [x] Flag no-change interactions for review.
- [x] Keep unobserved static surfaces informational because bounded crawling is incomplete by design.


### v2.6.0 — CI Concurrency Isolation

- [x] Isolate Emulator Self Test concurrency by Git ref.
- [x] Isolate Live Emulator Browser E2E concurrency by Git ref.
- [x] Preserve cancel-in-progress for stale runs on the same ref.
- [x] Prevent unrelated PRs/main pushes from cancelling one another's runtime gates.
- [x] Keep existing runtime verification coverage unchanged.


### v2.5.0 — Lifecycle Integrity

- [x] Audit lifecycle semantics for each bounded domain entity.
- [x] Distinguish delete, archive/trash and restore evidence.
- [x] Inspect cascade and relation-cleanup signals.
- [x] Inspect media/attachment cleanup around destructive paths.
- [x] Inspect reminder/alarm/notification cancellation around destructive paths.
- [x] Inspect remote/cloud/sync delete-propagation signals.
- [x] Inspect shared ownership/member/workspace delete semantics.
- [x] Normalize lifecycle findings into Product Consistency and expose them in Studio.


### v2.4.0 — Change Intelligence

- [x] Compare baseline/current App Intelligence snapshots deterministically.
- [x] Track Feature Truth transitions and capability additions/removals.
- [x] Track domain-entity and product-surface additions/removals.
- [x] Separate new, resolved and persistent Product Consistency findings.
- [x] Emit advisory HIGH_REVIEW / REVIEW / CHANGED / NO_MATERIAL_CHANGE state.
- [x] Surface change evidence in AppLab Studio without creating a release verdict.
- [x] Add CI self-test coverage for the Change Intelligence engine.


### v2.3.0 — Product Consistency Engine

- [x] Normalize review evidence across Product Truth, Lifecycle, Flow, UX, Architecture and Data.
- [x] Preserve source paths, subject, confidence and severity for every finding.
- [x] Distinguish HIGH_REVIEW, REVIEW and INFO without generating a synthetic score.
- [x] Surface top consistency findings and domain counts in AppLab Studio.
- [x] Keep dynamic-navigation uncertainty explicit instead of treating static gaps as defects.
- [x] Preserve all FAST/FULL/CERTIFICATION authority boundaries.
- [x] Correct the canonical roadmap baseline metadata to the current release.


### v2.2.0 — Product Flow & Feature Truth

- [x] Classify capability evidence as code, configuration, test or documentation provenance.
- [x] Expose CODE_CONFIRMED and weaker evidence classes without generating an opaque score.
- [x] Reconstruct a bounded static graph between detected product surfaces.
- [x] Collect route/path literals from navigation-like sources.
- [x] Flag candidate orphan surfaces as review targets only.
- [x] Surface Feature Truth and flow evidence in AppLab Studio.
- [x] Preserve schema compatibility and runtime/certification boundaries.


### v2.1.0 — Deep Product Model

- [x] Reconstruct bounded domain-entity candidates from source evidence.
- [x] Map create/update/delete/archive/restore/ownership lifecycle signals.
- [x] Emit entity lifecycle review targets without treating heuristics as defects.
- [x] Inventory bounded product surfaces and lightweight semantic roles.
- [x] Compare product documentation claims with detected source capabilities.
- [x] Surface lifecycle and documentation-drift evidence in AppLab Studio.
- [x] Preserve App Intelligence schema compatibility and certification boundaries.

### v2.0.0 — AppLab Studio

- [x] Unify quality/runtime and advisory product-intelligence presentation.
- [x] Keep trusted and advisory evidence planes independent.
- [x] Expose Product, UX, Architecture, Market, Cross-App and Audit evidence.

### v1.6.0 — Autonomous Audit Orchestrator

- [x] Build deterministic per-project audit plans from current evidence.
- [x] Broaden review when confidence is weak.
- [x] Preserve FAST/FULL/CERTIFICATION authority.

### v1.5.0 — Cross-App Intelligence

- [x] Aggregate project-scoped App Intelligence into portfolio evidence.
- [x] Detect recurrent patterns without automatic feature/code transfer.

### v1.4.0 — Competitor & Market Lab

- [x] Consume source-traceable market evidence.
- [x] Emit parity, differentiator, gap-review, pricing and pain signals.

### v1.1.0 → v1.3.0 — Product, UX & Architecture Intelligence

- [x] Product Analysis Engine.
- [x] UX & Product Lab.
- [x] Architecture & Data Intelligence.


### v1.3.0 — Architecture & Data Intelligence

- [x] Inventory repository/service/model/database structure from bounded source evidence.
- [x] Detect local persistence, remote/sync and offline-handling signals.
- [x] Emit conservative local-first assessments instead of unsupported claims.
- [x] Flag direct remote SDK usage in UI-like files as an advisory review target.
- [x] Detect premium-policy scattering and secret-like tracked material as review signals.
- [x] Keep architecture findings advisory and separate from runtime certification.

### v1.2.0 — UX & Product Lab

- [x] Detect loading, error, empty, confirmation, undo, onboarding, search and accessibility evidence.
- [x] Inventory navigation/UI surface from repository structure.
- [x] Add destructive-flow lifecycle evidence for delete/remove, trash/archive/restore and side-effect cleanup.
- [x] Emit explicit REVIEW findings without converting static heuristics into build failures.

### v1.1.0 — Product Analysis Engine

- [x] Detect stack, languages, product surface and test surface.
- [x] Inventory source evidence for auth, persistence, network, background work, notifications, monetization, analytics, AI/ML, export/backup, media, maps/location and cloud/sync.
- [x] Produce machine-readable JSON plus human-readable Markdown evidence.
- [x] Add a reusable/manual App Intelligence workflow that scans each target repository once.
- [x] Preserve the v1.0 trust boundary: product analysis cannot weaken verification or certification.

### v1.0.0 — Autonomous Quality Platform

- [x] Use failure intelligence in Repo Watcher scheduling.
- [x] Suppress repeated non-retryable app failures for the same SHA.
- [x] Retry transient/unknown failures with a bounded three-attempt policy.
- [x] Surface autonomous-quality evidence in Control Center.
- [x] Preserve all trust, certification and physical-device boundaries.

### v0.12.0 — SHOS / AppLab Integration

- [x] Classify changes into deterministic SHOS-oriented work categories.
- [x] Add playbook-required specialist labs to FAST verification.
- [x] Emit gate-based release-readiness evidence.
- [x] Emit knowledge-feedback evidence after verification.

### v0.11.0 — Project Intelligence

- [x] Emit compact project-state snapshots for chat/development handoff.
- [x] Track per-project learning state and learning-applied labs.
- [x] Add controlled cross-project signals as advisory evidence only.
- [x] Preserve project-specific evidence as authoritative.

### v0.10.0 — Self-Optimizing Verification

- [x] Learn recurrent specialist risk from watcher history after sufficient samples.
- [x] Detect unstable/flaky specialist domains without overriding FAIL.
- [x] Add impact graph v2 and explicit per-file import truncation evidence.
- [x] Lower confidence / broaden coverage when impact evidence is truncated.
- [x] Add lane verification budgets and budget-pressure telemetry.
- [x] Add failure taxonomy for app, visual, infrastructure, build/quality and unknown failures.


### v0.9.1 — Audit Hardening, Retry Safety & Measured FAST

- [x] Cache only successful PASS verification results; failed SHAs remain
  retryable by Repo Watcher.
- [x] Remove failed-build cache writes from Flutter/native runners.
- [x] Prevent `.github/workflows/**` from being classified as STATIC_ONLY;
  workflow changes that can affect auto-discovered build identity escalate to
  FULL_RUNTIME.
- [x] Record semantic-diff and dependency-scan truncation and lower confidence;
  dependency caps or combined truncation force FULL.
- [x] Detect nested/monorepo Flutter tests and Android `src/test` /
  `src/androidTest` paths as static-only.
- [x] Use targeted Dart analysis for safe STATIC_ONLY changes.
- [x] Track true GitHub workflow wall-clock time plus orchestration/setup
  overhead.
- [x] Aggregate p50/p95 wall-clock metrics separately by execution lane.
- [x] Track shadow FULL missed WARNs and missing-baseline evidence separately
  from hard false negatives/over-selection.
- [x] Collapse clean AVD preparation into Trusted Verify while saving the
  pristine snapshot before the target APK is installed.
- [x] Add lifecycle process-reclaim/fatal regression coverage and align
  Configuration Lab version to 0.7.7.1.
- [x] Align backend, frontend, runtime, certification and watcher identity to
  v0.9.1.
- [x] Update README, roadmap, adaptive engine docs and workflow contract tests.

### v0.9.0 — Adaptive Impact Analysis & Incremental Verification

- [x] Harden Configuration/Lifecycle background-return checks: allow one bounded cold relaunch when Android reclaims the process after foreground transition, while still failing on target ANR/fatal evidence.
- [x] Move impact planning before expensive analyze/test/build/runtime work.
- [x] Add five lanes: NO_RUNTIME_CHANGE, STATIC_ONLY, FAST_RUNTIME,
  FULL_RUNTIME and CERTIFICATION.
- [x] Analyze trusted `baseline..HEAD` using name-status, rename/delete
  information, numstat churn and bounded changed-hunk evidence.
- [x] Validate baseline SHA existence and ancestry; progressively deepen shallow
  clones and fall back to FULL if ancestry still cannot be proven.
- [x] Scope watcher baselines by repository + history key + ref.
- [x] Convert oversized diffs and planner uncertainty into FULL rather than a
  planner failure.
- [x] Add deterministic risk score and confidence calculation.
- [x] Add bounded reverse-import dependency impact analysis for Dart/Kotlin/Java.
- [x] Add historical specialist-lab failure risk from central watcher history,
  scoped by repository + history key + source ref.
- [x] Add targeted Flutter analyze/test execution with conservative fallback.
- [x] Add native Gradle task consolidation and safe single-module targeting.
- [x] Preserve core launch/crash/visual/interaction checks for runtime lanes.
- [x] Add deterministic shadow FULL calibration while retaining the original
  FAST prediction.
- [x] Record shadow divergence and potential false-negative labs.
- [x] Add planner regression corpus/self-tests for docs, static-only, database,
  oversized diff, dependency impact, missing baseline and non-ancestor baseline.
- [x] Add clean AVD cache preparation isolated from target app state.
- [x] Add pinned Maestro cache.
- [x] Add per-domain verification fingerprints.
- [x] Cache successful NO_RUNTIME_CHANGE/STATIC_ONLY resolved SHAs so unchanged
  analysis-only commits are not rescheduled by the hourly watcher.
- [x] Add adaptive metrics: planner latency, changed/impacted files, selected
  labs, quality/runtime timings, AVD/Maestro cache hits and shadow divergence.
- [x] Aggregate p50/p95 planner, quality, runtime and observed pipeline latency
  from central history and expose them in Control Center.
- [x] Surface lane/risk/confidence in watcher history and Control Center.
- [x] Prefer `git ls-files` for project auto-discovery.
- [x] Keep Universal Runner discovery checkout separate from target build
  checkout intentionally: merging them would couple auto-discovery and build
  trust boundaries for a small network-only saving.
- [x] Update backend/frontend/runtime identity to v0.9.0.
- [x] Update README and canonical ROADMAP.
- [x] Classify renames with both source and destination paths so runtime code
  moved into tests/docs cannot downgrade verification.
- [x] Restrict documentation-only shortcuts to known documentation locations;
  shipped `.md`/`.txt` assets remain runtime changes.
- [x] Preserve full Flutter unit-test fallback when no safe targeted test exists.
- [x] Refuse unsafe Gradle command consolidation when an option carries an
  argument or otherwise cannot be reordered safely.
- [x] Treat trusted empty target diffs after contract/cache invalidation as FULL.
- [x] Persist effective FULL fallback lane/mode into trusted result evidence.
- [x] Make domain fingerprints cover every contract-affecting input by default.
- [x] Preserve exact APK bytes, restore/clean target source, and recompute/compare
  the adaptive plan after untrusted build execution before trusted packaging.
- [x] Bound Flutter/native `workflow_dispatch` and `workflow_call` contracts to
  25 inputs, eliminating historical GitHub Actions startup-failures.
- [x] Make Flutter quality checks and native APK signature verification mandatory
  while keeping adaptive scope selection and centralized certification publication.

### v0.8.1 — Certification Integrity & Release Artifact Hardening

- [x] Last verified SHA range planning.
- [x] Release build identity/signing validation.
- [x] Primary + compatibility production certification lanes.
- [x] Byte-identical certified release publication.
- [x] Current versus stale certification state.
- [x] Real-device-required projects remain BLOCKED when hosted CI cannot provide
  trusted physical-device evidence.

### v0.8.0 — Production Certification Gate

- [x] Explicit CERTIFICATION mode.
- [x] Evidence bundle and APK identity integrity.
- [x] Release publication restricted to certified evidence.

### v0.7.x — Runtime specialist labs and FAST foundation

- [x] Performance.
- [x] Network/offline.
- [x] Persistence/restart.
- [x] Upgrade/migration.
- [x] Configuration/lifecycle stress.
- [x] Resource pressure/process death.
- [x] Background/Doze/recovery.
- [x] Storage/data integrity.
- [x] FAST/FULL smart specialist-lab orchestration.

### v0.6.x and earlier — Trusted Android verification platform

- [x] Smart Visual QA and visual regression.
- [x] Multi-screen visual journeys.
- [x] Safe interaction crawler.
- [x] Permissions/notifications/system UI lab.
- [x] Build -> Artifact -> Trusted Verify isolation.
- [x] Universal Flutter/native Android project runners.
- [x] Repo Watcher and Control Center.
- [x] Browser-controlled live emulator stack.

## v1.0 evidence contract

Every adaptive plan records:

- requested and effective mode;
- execution lane;
- baseline and target SHA;
- diff trust state;
- file status, additions and deletions;
- dependency-impacted files plus dependency scan/cap metadata;
- semantic diff evidence count and truncation state;
- selected specialist labs and reasons;
- risk score and confidence;
- targeted source/test/module scope;
- FULL fallback reason;
- shadow FULL decision;
- workflow profile-change escalation state;
- impact graph v2 edges and per-file import truncation state;
- per-project learning profile and learning-applied labs;
- SHOS playbook classification and required labs;
- verification budget, historical lane p95 and budget pressure;
- failure intelligence, flaky detection, release readiness, project state and knowledge feedback.

A reduced lane is never represented as a fake runtime PASS. NO_RUNTIME_CHANGE
and STATIC_ONLY explicitly record `runtime_executed=false` and the SHA whose
trusted runtime evidence is being reused.

## Current hardening limits

These are explicit engineering boundaries, not hidden assumptions:

1. The dependency graph is a bounded static import heuristic, not compiler-level
   whole-program analysis. Ambiguity lowers confidence or broadens coverage.
2. Historical risk is available when central watcher history is restored;
   standalone manual runs remain valid without it and simply omit that boost.
3. A new AVD cache key has one cold creation run before later jobs benefit from
   reuse.
4. Universal auto-discovery still performs a lightweight source checkout before
   the build runner performs its own checkout. This duplication is retained to
   preserve reusable-job boundaries and source/build isolation.
5. Physical-hardware-only behavior is not inferred from emulator evidence.
   Projects declaring `requires_real_device=true` remain BLOCKED for production
   certification until trusted device evidence exists.

## Next validation targets

- Integrate App Intelligence summaries into the Control Center after enough real-project reports exist.
- Use real audits to refine heuristics and reduce false-positive review signals.
- Calibrate the v1.4 capability taxonomy against real competitor evidence before broadening aliases or automating acquisition.
- Calibrate Cross-App recurrence thresholds against real multi-project corpus runs.
- Design v1.6 Autonomous Audit Orchestrator so audit selection follows project type, evidence and risk rather than a fixed checklist.

- Accumulate enough real watcher samples for statistically meaningful p50/p95.
- Measure shadow false-negative, missed-WARN and over-selection rates over a meaningful sample.
- Compare per-lane wall-clock p50/p95 and setup overhead after enough watcher samples.
- Tune risk thresholds only from measured calibration evidence.
- Expand dependency adapters when real projects demonstrate a repeatable blind
  spot; do not add speculative complexity.
- Evaluate trusted physical ARM64/device lanes independently from emulator FAST
  optimization.
