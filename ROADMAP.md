# AppLab Roadmap

Current production baseline: **v4.3.0 — External Project Certification Adapter**

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

### v4.3.0 — External Project Certification Adapter

- [x] Define one small per-project integration contract for repository/ref, package ID, project type, toolchain, release artifact pattern and critical journeys.
- [x] Auto-detect Flutter versus native Android structure where safely possible.
- [x] Resolve package/version/build identity and expected artifact automatically.
- [x] Declare primary, settings and critical journeys in a reusable project profile.
- [x] Declare whether physical-device validation is required for each critical capability.
- [x] Keep AppLab as the external trusted authority instead of copying verifier logic into target repositories.
- [x] Validate the adapter on pinned CamperBoss and Battery Guard revisions through the real-project integration workflow.
- [x] Preserve FAST / FULL / CERTIFICATION semantics and all existing trust boundaries.

### v4.2.0 — Evidence Graph

- [x] Add one deterministic graph model across Project, Revision, BuildArtifact, Capability, Surface, Journey, Finding, Claim, Evidence, Experiment and Result.
- [x] Bind graph identity to repository, resolved SHA, workflow run, package and APK/build provenance when trusted runtime evidence is available.
- [x] Preserve every source report as authoritative evidence and record report/content provenance instead of replacing upstream engines.
- [x] Link claims/findings/experiments to their product subjects and supporting evidence.
- [x] Import longitudinal first/last observation and recurrence statistics without treating first observation as causal commit blame.
- [x] Add deterministic graph queries for unverified capabilities, recurring findings, regressions, subject history and supporting evidence.
- [x] Integrate Evidence Graph into True Autonomous Review and publish `evidence-graph.json` / `evidence-graph.md`.
- [x] Surface graph summary and high-value graph insights in AppLab Studio and the read-only Web Preview.
- [x] Add self-test, independent regression coverage and audit-contract enforcement.
- [x] Preserve FAST/FULL/CERTIFICATION, trusted runtime and Analyst authority boundaries.

### v4.1.0 — Execution Acceleration Engine

- [x] Keep Smart Test Plan as the single change-aware test-selection authority.
- [x] Add deterministic execution keys and a machine-readable execution DAG.
- [x] Make build identity content-addressed by source, toolchain, build inputs and semantic plan.
- [x] Reuse validated Flutter/native build contracts across equivalent reruns.
- [x] Restrict build reuse to artifacts produced by the same AppLab workflow revision.
- [x] Revalidate every restored build contract before trusted verification.
- [x] Extend build-contract retention to seven days for safe rerun reuse.
- [x] Build the AppLab self-test APK once and share identical bytes across Browser E2E and Emulator Self Test.
- [x] Verify canonical runtime fixture source SHA and APK SHA-256 in every consumer.
- [x] Preserve stale-run cancellation and explicit serial shared-emulator policy.
- [x] Record execution key/build-cache hit in pipeline metrics.
- [x] Add AppLab Doctor environment preflight.
- [x] Encode v4.1 invariants in heavy-audit CI contracts.
- [x] Close PR #73 with CI/security, CodeQL, canonical runtime fixture, Browser E2E, Emulator Self Test, True Autonomous Review and Repository Governance all green.

### v4.0.2 — Residual Hardening

- [x] Refresh trusted longitudinal history monthly before 90-day artifact expiry.
- [x] Add independent cross-engine regression corpus outside implementation-local self-tests.
- [x] Add blocking Python and npm dependency vulnerability audits.
- [x] Add maintainability growth ceilings for the largest high-cost modules.
- [x] Make current vs compatibility workflow authority explicit.
- [x] Add safe read-only Web Preview mode with no privileged backend/controller.
- [x] Add repository-governance audit workflow for branch-protection visibility.
- [x] Enable and verify GitHub branch protection/ruleset for `main`; Repository Governance Audit is green.

### v4.0.1 — Heavy Audit Hardening

- [x] Bind the privileged Live Controller to loopback by default.
- [x] Replace remote Maestro installer execution with versioned SHA-256-verified release bytes.
- [x] Pin external GitHub Actions to immutable commit SHAs.
- [x] Bind reusable Flutter verification to the same AppLab revision instead of `@main`.
- [x] Make Longitudinal Product Intelligence branch-lineage aware and exclude sibling-branch history.
- [x] Preserve lineage independently while keeping immutable reviewed SHA binding.
- [x] Generate `studio.json` automatically from trusted review evidence.
- [x] Preserve forward-compatible Control Center and Studio summary metrics through backend adapters.
- [x] Align backend/frontend/Studio/CI version contracts to 4.0.1.
- [x] Add CI audit-contract enforcement for hardening invariants.
- [x] Add Dependabot governance for Python, npm and GitHub Actions.
- [x] Enable GitHub branch protection/ruleset for `main` (completed during subsequent hardening; current Repository Governance Audit verifies it).

### v4.0.0 — AppLab Analyst

- [x] Synthesize product, runtime, evidence, longitudinal and experiment evidence into one deterministic report.
- [x] Preserve source-report provenance rather than replacing underlying evidence.
- [x] Expose descriptive Analyst states without creating a release verdict or numeric score.
- [x] Build evidence-backed observations only from existing AppLab evidence.
- [x] Derive next actions only from FIX_NOW, Experiment Planner and IMPROVE evidence.
- [x] Distinguish product context, evidence posture, change context and experiment context.
- [x] Include market context only when traceable Market Intelligence already exists.
- [x] Add explicit "do not conclude" boundaries to prevent overclaiming.
- [x] Surface Analyst state, headline, observations and actions in AppLab Studio.
- [x] Keep LLM usage optional: v4.0 core analysis is deterministic and local to AppLab evidence.

### v3.6.0 — Autonomous Experiment Planner

- [x] Convert Decision Brief VERIFY_NEXT/FIX_NOW signals into deterministic experiments.
- [x] Promote longitudinal regression candidates into high-priority verification hypotheses.
- [x] Convert Evidence Confidence contradictions into explicit reconciliation experiments.
- [x] Reuse existing specialist runtime labs and safe journey tooling before adding new machinery.
- [x] Define preconditions, actions, observations and sufficient-evidence criteria for every experiment.
- [x] Preserve SUPPORTED / CONTRADICTED / UNVERIFIED semantics without numeric scoring.
- [x] Deduplicate equivalent experiments while preserving every trigger source.
- [x] Surface next experiment, priorities and target labs in AppLab Studio.
- [x] Keep planner output advisory and independent from FAST/FULL/CERTIFICATION.

### v3.5.0 — Longitudinal Product Intelligence

- [x] Persist a bounded repository-scoped history of trusted Autonomous Review snapshots.
- [x] Classify findings as new, returned, persistent and resolved across revisions.
- [x] Track severity escalation/de-escalation for persistent findings.
- [x] Track Evidence Confidence claim-status transitions across revisions.
- [x] Reuse Change Intelligence for pairwise capability/entity/surface deltas.
- [x] Surface regression candidates without turning them into automatic defects.
- [x] Preserve current trusted evidence as authoritative over historical evidence.
- [x] Expose longitudinal state, counts and top regression candidates in AppLab Studio.
- [x] Keep FAST/FULL/CERTIFICATION outcomes independent from longitudinal analysis.

### v3.4.0 — UX Friction & Discoverability Lab

- [x] Detect safe runtime actions whose reduced crawler signature remains stable, without claiming visual feedback is absent.
- [x] Detect repeated stable-signature patterns without treating them as automatic defects.
- [x] Surface navigation-loop candidates from trusted journeys.
- [x] Surface deep-journey candidates while excluding obvious settings/help-style paths.
- [x] Detect high clickable-density states as inspectable heuristics.
- [x] Detect ambiguous runtime labels from one state to multiple targets.
- [x] Review discoverability of unmatched core-role static surfaces.
- [x] Surface unverified empty/error/permission-denied UX states.
- [x] Route UX findings into VERIFY_NEXT/IMPROVE, never automatic FIX_NOW.
- [x] Expose UX friction metrics and findings in AppLab Studio.


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

## Planned direction after v4.2

The next phase is not to add more isolated analyzers for their own sake. AppLab
must evolve from a strong autonomous technical QA platform into the central
release-assurance and virtual product-review system of the App Factory.

The long-term direction is:

```
Source / Product intent
        ↓
Technical analysis
        ↓
Trusted runtime verification
        ↓
Evidence Graph
        ↓
Release Reality
        ↓
Physical / distribution evidence
        ↓
Simulated human review
        ↓
UX / design / product review
        ↓
Competitive intelligence
        ↓
Release decision support
```

Simulated-human, design and market conclusions are advisory evidence. They must
never be represented as real-user research, physical-device evidence or trusted
runtime PASS.

### v4.4 — Release Reality Engine

Goal: make AppLab state exactly how far a release has really progressed instead
of treating a green build or emulator run as "finished".

Planned:
- [ ] Track the release-evidence ladder: IMPLEMENTED -> STATICALLY CHECKED -> TESTED -> CI GREEN -> ARTIFACT BUILT -> TRUSTED RUNTIME VERIFIED -> PHYSICAL DEVICE VERIFIED -> DISTRIBUTION VERIFIED -> STORE READY -> PRODUCTION RELEASED.
- [ ] Create a canonical release evidence record bound to source SHA, package, version/build, artifact SHA-256, signing identity and workflow run.
- [ ] Distinguish PASS, FAIL, BLOCKED and NOT VERIFIED at every applicable stage.
- [ ] Enforce same-artifact semantics: rebuilt bytes are a new artifact unless provenance is explicitly re-established.
- [ ] Surface exact certification blockers instead of a synthetic numeric product score.
- [ ] Preserve risk-based validation so projects are not forced through irrelevant checks.

### v4.5 — Physical Evidence Hub

Goal: extend AppLab beyond hosted emulator evidence without pretending that
emulator PASS proves hardware/OEM behavior.

Planned:
- [ ] Define a trusted physical-validation record bound to the exact artifact SHA-256.
- [ ] Record device model, OS version, scenario, preconditions, observed result, logs and screenshots.
- [ ] Support evidence ingestion for GPS/background, sensors, camera/scanner, biometrics/Keystore, notifications, file/storage flows, OEM battery behavior, OAuth release callbacks, billing and Play-delivered assets/models.
- [ ] Mark required-but-missing physical validation as BLOCKED, never PASS.
- [ ] Keep physical-device evidence separate from emulator, Web Preview and simulated-human evidence.
- [ ] Design the first version for real devices already available to the App Factory before considering a large device farm.

### v4.6 — Evidence Graph 2: Impact, Freshness & Temporal Intelligence

Goal: use the v4.2 graph to understand which evidence is still valid after a
change and which product areas are affected.

Planned:
- [ ] Add evidence freshness and stale-evidence propagation.
- [ ] Add impact paths from changed files/components to capabilities, surfaces, journeys and evidence.
- [ ] Track finding lifecycle as first observed, persistent, resolved and returned without inventing causal blame.
- [ ] Invalidate or downgrade only the evidence actually affected by a change.
- [ ] Use graph impact to improve risk-based FAST/FULL selection.
- [ ] Make graph subjects directly queryable from Studio with provenance and history.
- [ ] Keep source reports authoritative and the graph as index/query infrastructure.

### v4.7 — Certification Studio / Release Cockpit

Goal: make the real state of each app understandable at a glance.

Planned:
- [ ] Show current Release Reality level per project/release.
- [ ] Show exact certification blockers and missing evidence.
- [ ] Show artifact identity, source SHA, runtime state, evidence freshness and physical requirements.
- [ ] Add "Why is this not CERTIFIED?" drill-down.
- [ ] Surface regression candidates, recurring findings and stale evidence without opaque scoring.
- [ ] Keep Studio read-only for trust-sensitive evidence unless an explicit trusted action path exists.

### v4.8 — Cross-App Verification

Goal: verify real interactions between two App Factory apps rather than proving
each side independently.

Planned:
- [ ] Define paired-artifact verification with producer and consumer source/artifact identities.
- [ ] Execute explicit cross-app scenarios such as COPY, LINK, deep-link handoff and documented fallback transport.
- [ ] Verify idempotency, provenance, ownership and fail-closed behavior across the pair.
- [ ] Record paired physical-device evidence when the transport depends on installed apps.
- [ ] Keep single-app AppLab PASS distinct from cross-app round-trip PASS.
- [ ] Use Shared Ecosystem Core contracts where applicable instead of inventing parallel protocols.

### v5.0 — Simulated Human QA

Goal: add a human-like review layer that tries to use the app as different types
of users and identifies usability problems that technical PASS cannot detect.

Planned:
- [ ] Add task-driven simulated usability sessions over trusted screenshots, UI hierarchy, product flows and runtime journeys.
- [ ] Define bounded personas such as beginner, power user, older user, accessibility-focused user, privacy-conscious user, impatient user and offline user.
- [ ] Let each persona attempt explicit goals and record friction, confusion, dead ends, excess taps and recovery problems.
- [ ] Add cognitive walkthrough and heuristic UX review.
- [ ] Aggregate multi-persona consensus while preserving disagreements and evidence.
- [ ] Classify findings as SIMULATED USER REVIEW, never REAL USER VALIDATION.
- [ ] Route strong recurring simulated findings into VERIFY_NEXT / IMPROVE rather than automatic product defects.
- [ ] Preserve deterministic technical gates independently from model-based human simulation.

### v5.1 — Design System & UI Library Advisor

Goal: judge whether the visual language and component library fit the type of
product instead of applying one design system to every app.

Planned:
- [ ] Infer product context and interaction style before reviewing visual-system fit.
- [ ] Review hierarchy, typography, spacing, density, component consistency, feedback, empty/loading/error states and interaction affordances.
- [ ] Compare current Material, Cupertino, custom or third-party component choices against product needs.
- [ ] Recommend keeping, adapting or replacing a UI library only when evidence shows a concrete product-fit benefit.
- [ ] Evaluate accessibility, responsive behavior, dark mode and localization impact together with visual fit.
- [ ] Avoid style churn: a different library is not automatically an improvement.
- [ ] Keep aesthetic/product recommendations advisory and traceable to observed evidence.

### v5.2 — Competitive Product Intelligence

Goal: use competitors as evidence for product decisions without turning AppLab
into a feature-copying engine.

Planned:
- [ ] Maintain source-traceable competitor sets per app/category.
- [ ] Compare product capabilities, workflows, onboarding, pricing, visual patterns and recurring user pain points.
- [ ] Separate common market expectations from genuine differentiation opportunities.
- [ ] Highlight missing parity only when it is relevant to the Product Bible and target user.
- [ ] Identify competitor weaknesses that create an opportunity for a simpler or better App Factory implementation.
- [ ] Track market evidence freshness and provenance.
- [ ] Never auto-add a feature merely because competitors have it.

### v5.3 — Virtual Product Review Council

Goal: combine technical QA, simulated users, UX, design and competitor evidence
into one review meeting-like output without collapsing authorities.

Planned:
- [ ] Run specialized virtual reviewers for QA, UX, accessibility, product, design and market context.
- [ ] Preserve each reviewer's evidence, uncertainty and scope instead of producing an opaque consensus score.
- [ ] Detect cross-review agreement, contradiction and missing evidence.
- [ ] Produce a prioritized Product Review Brief: FIX_NOW, VERIFY_NEXT, IMPROVE, CONSIDER and NO_ACTION.
- [ ] Distinguish technical defects, usability risks, design-fit questions and product opportunities.
- [ ] Keep real-user validation, physical-device validation and release certification as separate evidence classes.
- [ ] Use the council to reduce manual triage, not to replace final product ownership.

### v5.x ongoing technical hardening

The strategic roadmap above does not postpone technical quality. Every version
may include targeted hardening when real AppLab evidence demonstrates a need.

Continuous priorities:
- [ ] Reduce runtime/browser E2E flakiness without weakening assertions.
- [ ] Improve diagnostics for WebRTC/frame/codec/runtime infrastructure failures.
- [ ] Add schema/version contracts for new evidence producers and consumers.
- [ ] Add evidence retention/garbage-collection policy while pinning release-critical evidence.
- [ ] Improve delta execution so small changes rerun only the evidence that can actually be invalidated.
- [ ] Tune heuristics from real multi-project data rather than speculative complexity.
- [ ] Keep performance, security, dependency, artifact-provenance and maintainability gates healthy as AppLab grows.

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

## Current validation priorities

- Validate the v4.3 external-project adapter first on a real Flutter app, then on a second App Factory project.
- Promote AppLab QA/certification process only from real trusted evidence, not from AppLab self-tests alone.
- Accumulate multi-project runtime/evidence samples to calibrate heuristics, FAST/FULL selection and recurrence thresholds.
- Measure and reduce Browser E2E / emulator infrastructure flakiness without converting transient uncertainty into PASS.
- Introduce physical-device evidence incrementally for capabilities that materially depend on real hardware, OEM behavior or store services.
- Use v4.2 Evidence Graph data to drive freshness/impact work before adding additional standalone intelligence engines.
- Treat simulated-human, design and competitor review as advisory layers that complement rather than replace deterministic QA and real-user validation.
