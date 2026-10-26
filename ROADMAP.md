# AppLab Roadmap

Current production baseline: **v5.5 — Multi-Project Event-Driven Rollout**

Next architecture sequence: **v5.6 — Evidence-Efficient Reliability & Physical Proof**  
Status: **v5.5A–E completed and merged; verification/certification authority boundaries preserved; v5.6 is the next execution sequence**.

## Completed — v5.5 Multi-Project Event-Driven Rollout

The v5.5 program promotes the v5.4 control plane from a self-repository canary to bounded real-project orchestration while preserving every existing verification and certification authority.

- [x] **v5.5A Pilot Set:** define a three-repository allowlist (AppLab/selftest, CamperBoss, TrailPath), use immutable target SHA admission, route real projects through the existing Universal Project Runner, preserve the hourly watcher and add repository-dispatch/manual ingress without broad cross-repository credentials.
- [x] **v5.5B Reconciliation & Recovery:** prove event loss, duplicate delivery, Actions outage, interrupted operation, Brain restart, expired lease, superseding SHA and watcher recovery semantics across the pilot set.
- [x] **v5.5C Warm Worker Real-App Pilot:** run real-app trusted-runtime equivalence on warm workers while keeping target build scripts outside the trusted worker and GitHub Actions as fallback.
- [x] **v5.5D Multi-Repo Queue:** validate fairness, priority, backpressure, repository isolation and p50/p95 queue/start/runtime telemetry under real multi-project load.
- [x] **v5.5E Controlled Expansion:** expand 3 -> 5 -> all compatible repositories with global/per-repo kill switches; only after sufficient evidence may the hourly watcher become reconciliation/watchdog rather than primary scheduler.

Promotion remains evidence-gated. v5.5 cannot mint PASS/CERTIFIED, cannot reduce Smart Test Plan coverage and cannot remove GitHub Actions fallback or watcher reconciliation by documentation alone.

## Planned — v5.6 Evidence-Efficient Reliability & Physical Proof

The v5.6 program converts the remaining open hardening priorities into five independently mergeable stages. The objective is to make AppLab faster and more operationally efficient without weakening trusted evidence, exact-artifact identity, physical-device boundaries or certification authority.

- [x] **v5.6A Runtime Stability & Failure Diagnostics:** reduce Browser E2E / emulator / WebRTC / frame / codec infrastructure flakiness without weakening assertions; preserve fail-closed app failures; improve pre-recovery diagnostics, recurrence classification and p50/p95 runtime visibility.
- [x] **v5.6B Evidence Lifecycle & Retention:** extend the existing TTL model into an explicit evidence retention / garbage-collection policy; pin release-critical, certification, physical/distribution and cross-app evidence; make cleanup provenance-aware and prevent GC from deleting evidence still required by release history.
- [x] **v5.6C Delta Execution Controlled Experiment:** use accumulated multi-project calibration to run a bounded shadow/controlled experiment for invalidation-based execution. Keep `coverage_reduction_enabled=false` by default; no production coverage reduction is permitted until false-negative, missed-warning and confidence thresholds are satisfied on real history and an explicit promotion gate passes.
- [x] **v5.6D Multi-Project Heuristic Calibration:** tune FAST/FULL selection, recurrence thresholds, risk/confidence inputs and scheduling heuristics from real multi-project history rather than speculative complexity; require repository/category diversity, stale-data handling and measurable before/after evidence.
- [x] **v5.6E Physical Evidence & Advanced Hardening Pilots:** introduce bounded physical-device evidence where emulator proof is insufficient and evaluate the already-approved evidence-only pilots: scrcpy Physical Evidence Hub, LeakCanary diagnostic lane, Semgrep + Trivy first-wave security scanning and MobSF second-wave mobile scanning. These producers remain evidence sources only and cannot mint PASS/CERTIFIED or alter release-artifact identity.

### v5.6 execution rules

**Active execution mode: ROADMAP_FAST + CONTINUOUS_MAINTENANCE.**

- [x] Keep roadmap delivery and maintenance analysis in independent lanes.
- [x] Let only P0/P1, trust-boundary, false-PASS, artifact-identity, data-loss, critical-security or current-step regressions block roadmap progress.
- [x] Persist all other findings into a background maintenance queue without mutating the active roadmap PR.
- [x] Run lightweight maintenance after Repo Watcher and hourly while idle, using existing evidence/history rather than launching runtime work without a trigger.
- [x] Preserve PASS/CERTIFIED, Smart Test Plan, exact-artifact and physical/store authority boundaries.

Each A→E stage is intentionally smaller than v5.5E and must be independently branchable, reviewable, exact-head validated and mergeable. A later stage must not be bundled into an earlier PR merely to reduce PR count.

Cross-cutting guardrails for every v5.6 stage:
- keep Smart Test Plan as the sole FAST/FULL authority unless a separately approved contract explicitly changes that;
- keep Production Certification as the only certification authority;
- keep emulator/runtime, physical-device, distribution/store and cross-app evidence distinct;
- keep GitHub Actions fallback and recovery paths until real evidence supports a separate removal decision;
- keep performance, security, dependency, artifact-provenance and maintainability gates healthy as part of each stage rather than creating a sixth catch-all step;
- prefer measured reuse of existing AppLab engines and evidence producers over parallel implementations.

### v5.6 promotion rule

Completing documentation or a shadow simulation does not promote production behavior. Any coverage reduction, scheduler-role change, physical-evidence authority change or new security verdict path requires its own exact-head evidence, rollback path and explicit promotion criteria.

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

## Proposed — v5.4 Durable Brain & Event-Driven Execution

The v5.4 direction is to add a durable orchestration/control plane above the existing AppLab verification engines. It must improve continuity, queue isolation, recovery and startup latency without becoming a second verification authority.

Design artifacts:

- `integration/orchestration/V54_POST_IMPLEMENTATION_EVALUATIONS.md`
- `integration/orchestration/v54-post-implementation-decisions.json`
- `integration/orchestration/DURABLE_BRAIN_V54_DESIGN_AUDIT.md`
- `integration/orchestration/EVENT_OPERATION_EVIDENCE_V54.md`
- `integration/orchestration/CONDUCTOR_SHADOW_AND_WARM_WORKERS_V54.md`

### Design/audit completed

- [x] Audit current watcher persistence, cancellation, polling, runner-latency and retry/rerun semantics.
- [x] Define the Durable Brain architecture while preserving Smart Test Plan, Trusted APK Verifier, Release Assurance and Production Certification authority.
- [x] Define versioned Event, Operation, Attempt, EvidenceRef, Worker, Lease and transition semantics.
- [x] Define per-repository queue isolation, priority, coalescing, supersession, backpressure and reconciliation policy.
- [x] Define a Conductor `SHADOW_NO_DISPATCH` pilot with no production credentials or evidence authority.
- [x] Define a warm trusted-runtime worker model that never executes untrusted target build scripts.
- [x] Define security, observability, rollback and promotion guardrails.
- [x] Keep `coverage_reduction_enabled=false` and make delta coverage reduction explicitly independent from v5.4 orchestration work.

### Implementation sequence

- [x] **v5.4A Contracts & Simulator:** versioned Event/Operation/Attempt contracts, executable state validator, deterministic per-repo queue/supersession simulator and replay corpus; offline only, no external integration.
- [x] **v5.4B Durable Store Shadow:** provider-neutral durable persistence contract, file-backed restartable shadow adapter, PostgreSQL-compatible schema smoke, immutable Event/Attempt/Evidence/Transition history and transition-backed Operation projection; zero authority/dispatch.
- [x] **v5.4C Event Gateway Shadow:** signed GitHub push/PR/workflow normalization, persistent delivery replay protection, logical Event dedupe and watcher-compatible reconciliation comparison; zero Operation creation/dispatch.
- [x] **v5.4D Conductor Shadow Pilot:** mirror real AppLab orchestration metadata, model expected DAG/state and compare against actual execution with zero dispatch capability.
- [x] **v5.4E Durable Per-Repo Queue:** replace global event-driven cancellation semantics with repository/lineage/class isolation, bounded retries and backpressure while GitHub Actions remains executor.
- [x] **v5.4F Warm Trusted-Runtime Pilot:** isolated KVM lifecycle, lease/heartbeat/quarantine controls, pristine/disposable AVD evidence and cold-vs-warm equivalence PASS; GitHub Actions remains fallback.
- [x] **v5.4G Controlled Event-Driven Pilot:** bounded GitHub push-driven AppLab/selftest canary with durable Event/Operation/queue admission, existing trusted runner execution, kill switch, 30-day pilot evidence and hourly watcher watchdog; no certification authority change.
- [x] Evaluate scrcpy physical-device recording/control: **FUTURE_PILOT** as Physical Evidence Hub capture, evidence-only authority.
- [x] Evaluate LeakCanary: **FUTURE_PILOT** as a separate debug/instrumented memory-diagnostic lane with independent artifact identity; never mutate release-artifact identity.
- [x] Evaluate dedicated security scanners: **Semgrep + Trivy FIRST-WAVE PILOT**, **MobSF SECOND-WAVE MOBILE PILOT**; all remain registered security-evidence producers, not orchestration/verdict authority.
- [x] Consider autonomous diagnosis/fix/PR: **ELIGIBLE FOR A SEPARATE PROPOSAL-ONLY PILOT**; autonomous merge/release remains explicitly outside v5.4 and requires a separate governance decision.

### Promotion gate

No v5.4 runtime component becomes production authority from a documentation merge or from successful shadow execution. Production enablement requires a separate exact-head change, independent contract/chaos tests, bounded pilot evidence, rollback path and no weakening of existing authority boundaries.

## Completed

### v5.3.5 — Multi-Project Calibration & Delta Readiness

- [x] Operational hardening: move CamperBoss watcher lineage from stale `step-16-release-core` to `main`.
- [x] Operational hardening: expand watcher coverage from the original 5-project pilot; current inventory has 14 enabled Android/Flutter targets after the intentional FrameLab private exclusion.
- [x] Operational hardening: keep the optional `APPLAB_TARGET_TOKEN` contract available for future explicit private targets; no current enabled watcher target requires it.
- [x] Keep documentation-only and unsupported Capacitor-only repositories outside runtime calibration until an executable lane exists.
- [x] Follow-up hardening: classify missing private-repository auth as `TARGET_AUTH_REQUIRED` instead of generic 404 when a future enabled target explicitly requires private auth.
- [x] Follow-up hardening: retain FrameLab-Google-AI-Studio, Cozy and Neon in complete project inventory while excluding them from calibration with explicit reasons.
- [x] Follow-up hardening: isolate multi-task Gradle CI commands into lint/test/build commands during auto-discovery.
- [x] Follow-up hardening: retry Android preview SDK installation for valid preview compileSdk targets such as API 37.
- [x] Visibility reconciliation: treat `app-fotografia`, `PDF-Unifier` and `App-corpo-umano` as public targets and exclude intentionally private `FrameLab-Google-AI-Studio` from runtime/calibration.

- [x] Build one deterministic calibration report from cumulative real multi-project watcher/certification history.
- [x] Accept only observed shadow FULL calibration as evidence for predicted-skip safety.
- [x] Track repository, shadow-sample and change-category diversity before declaring experimental readiness.
- [x] Treat missed WARN/FAIL/ERROR as unsafe and missing baselines as incomplete rather than safe evidence.
- [x] Derive per-lab evidence candidates only after repeated safe observations across multiple repositories.
- [x] Publish versioned `delta-calibration.json/.md` evidence and expose readiness in Control Center.
- [x] Register the new evidence producer, bind it to core fingerprints and add independent CI/audit contracts.
- [x] Keep `coverage_reduction_enabled=false`; Smart Test Plan remains the sole FAST/FULL authority.
- [x] Preserve existing FAST/FULL/CERTIFICATION, trusted-runtime, exact-artifact and physical-device boundaries.

### v5.3.4 — Evidence Schema Registry & Compatibility Contracts

- [x] Add one deterministic registry for stable planning, trusted-runtime, release/certification and advisory evidence boundaries.
- [x] Declare exact schema/component versions, producers, consumers and fixed authority/record-type fields for registered artifacts.
- [x] Reject registered schema/version incompatibility before Evidence Graph, Release Reality, Release Assurance or trusted-manifest consumption.
- [x] Validate registered review evidence before Studio projection without treating the registry as a new evidence authority.
- [x] Add independent contract coverage for compatible fixtures, tampered schema/version fields, producer drift and unknown evidence.
- [x] Bind registry semantics to central/core fingerprints and Repo Watcher invalidation.
- [x] Add CI/audit coverage, maintainability ceilings and release documentation.
- [x] Preserve FAST/FULL/CERTIFICATION, trusted-runtime, exact-artifact and physical-device authority boundaries.

### v5.3.3 — Structural Hardening & Contract Test Foundation

- [x] Extract planner-feedback schema/digest/compatibility primitives from the saturated planner-feedback module without changing planner authority.
- [x] Move large deterministic Studio and Evidence Graph fixtures out of production modules while preserving their self-test entrypoints.
- [x] Split version-specific heavy audit assertions out of the audit-contract orchestrator.
- [x] Add independent end-to-end planning-feedback contract coverage for exact baseline, tamper, truncation and FAST-to-FULL promotion behavior.
- [x] Parse every workflow structurally in CI and independently enforce SHA-pinned external actions.
- [x] Add maintainability ceilings for Evidence Graph, audit contracts, Studio frontend and both external runners.
- [x] Bind the extracted planner-feedback contract to central/core fingerprints and Repo Watcher invalidation.
- [x] Reconcile workflow authority documentation, classify the Flutter compatibility wrapper and APK diagnostic workflow, and remove the CamperBoss one-off workflow.
- [x] Preserve all FAST/FULL/CERTIFICATION, exact-artifact and physical-evidence authority boundaries.

### v5.3.2 — Graph-aware Planning Feedback Hardening

- [x] Define a versioned planner-feedback record derived only from prior Evidence Graph evidence.
- [x] Bind feedback to repository, exact source/baseline SHA, lineage, graph version/digest and analysis-plan digest.
- [x] Reject missing, malformed, digest-mismatched, cross-repository, cross-lineage, stale-baseline or truncated feedback without weakening the existing planner.
- [x] Feed compatible prior graph impact/invalidated-evidence signals into Smart Test Plan as bounded escalation-only risk hints.
- [x] Keep Smart Test Plan as the sole FAST/FULL authority; graph feedback cannot reduce lab/build/runtime coverage.
- [x] Prevent the current run's graph from retroactively changing the lane that produced it.
- [x] Persist planner feedback inside repository-scoped 90-day longitudinal evidence and restore it automatically for future FAST runs.
- [x] Pass the same feedback into trusted post-build plan recomputation and make it part of immutable plan comparison.
- [x] Include planner-feedback producer/restore logic in core contract fingerprints and watcher invalidation.
- [x] Add self-tests, CI/audit/workflow contracts, documentation and maintainability ceilings.

### v5.3.1 — Evidence-Driven Technical Hardening

- [x] Add one bounded browser-peer recovery for the observed WebRTC connected/no-decoded-frame infrastructure signature without weakening frame or input assertions.
- [x] Capture video/track, gateway, runtime and browser-error diagnostics before every WebRTC recovery attempt.
- [x] Fail invalid frontend dependency/lock graphs before expensive Docker/emulator runtime work.
- [x] Validate dependency-manifest pull requests without allowing the lock workflow to push back into the PR.
- [x] Keep the read-only Studio build green and inspectable when GitHub Pages is not configured, while explicitly skipping deployment.
- [x] Define and CI-enforce evidence-retention classes and minimum artifact TTLs.
- [x] Raise certified release, final certification and certification-history retention from 7 to 90 days.
- [x] Retain transient Live WebRTC diagnostic evidence for 7 days instead of one day.
- [x] Preserve FAST/FULL/CERTIFICATION, exact-artifact provenance and physical-device authority boundaries.

### v5.3.0 — Virtual Product Review Council

- [x] Run specialized virtual reviewers for QA, UX, accessibility, product, design and market context.
- [x] Preserve each reviewer's evidence, uncertainty, scope and source-record state instead of producing an opaque consensus score.
- [x] Detect cross-review agreement, action contradiction and missing/invalid evidence.
- [x] Produce a prioritized Product Review Brief with FIX_NOW, VERIFY_NEXT, IMPROVE, CONSIDER and NO_ACTION.
- [x] Distinguish technical defects, usability/accessibility risks, design-fit questions and product/market opportunities.
- [x] Restrict FIX_NOW to existing technical/runtime evidence and demote advisory conflicts to VERIFY_NEXT.
- [x] Keep real-user validation, physical-device validation and release certification as separate evidence classes.
- [x] Bind the Council to the exact Evidence Graph source/artifact identity and fail closed in Studio.
- [x] Integrate the Council into True Autonomous Review, Studio, Control Center and CI.
- [x] Use the Council to reduce manual triage without replacing final product ownership.

### v5.2.0 — Competitive Product Intelligence

- [x] Maintain source-traceable competitor sets per app/category with stable set identity.
- [x] Compare capabilities, workflows, onboarding, pricing, visual patterns and recurring user pain points.
- [x] Separate common market expectations from genuine project differentiation opportunities.
- [x] Highlight missing parity only when Product Bible/product-contract relevance and target-user context are both established.
- [x] Convert recurring competitor weaknesses into bounded simplify/improve opportunities instead of copying directives.
- [x] Track market-evidence freshness, observation age and source provenance.
- [x] Bind competitive conclusions to the exact Evidence Graph source/artifact identity.
- [x] Integrate fail-closed competitive evidence into True Autonomous Review and AppLab Studio.
- [x] Guarantee no automatic feature addition and no competitor feature copying.

### v5.1.0 — Design System & UI Library Advisor

- [x] Infer bounded product context and interaction style before reviewing visual-system fit.
- [x] Review hierarchy, typography, spacing, density, component consistency, feedback, empty/loading/error states and interaction affordances.
- [x] Compare detected Material, Cupertino, custom and common third-party UI-system choices against product needs.
- [x] Emit only KEEP, ADAPT, REPLACE_CANDIDATE or EVIDENCE_INCOMPLETE; replacement requires concrete evidence and is never automatic.
- [x] Evaluate accessibility, responsive behavior, dark mode and localization together with visual fit.
- [x] Preserve the no-style-churn rule: a different library is not automatically an improvement.
- [x] Bind advisory evidence to canonical Evidence Graph repository/source/package/APK/version identity.
- [x] Add fail-closed Studio projection, Control Center exposure, deterministic self-tests and CI/audit/workflow contract gates.
- [x] Keep all design/product recommendations advisory and unable to override FAST/FULL/CERTIFICATION or Release Assurance.

### v5.0.0 — Simulated Human QA

- [x] Add task-driven simulated usability sessions over trusted product/runtime evidence and canonical Evidence Graph identity.
- [x] Define exactly seven bounded personas: beginner, power user, older user, accessibility-focused, privacy-conscious, impatient and offline user.
- [x] Give each persona explicit goals and classify outcomes as FRICTION_SIGNAL, EVIDENCE_INCOMPLETE, NO_STRONG_SIGNAL or NOT_APPLICABLE.
- [x] Add cognitive walkthrough criteria and bounded heuristic UX review.
- [x] Aggregate multi-persona consensus while preserving non-supporting personas and disagreement counts.
- [x] Classify all output as SIMULATED USER REVIEW, never REAL USER VALIDATION or physical-device evidence.
- [x] Route recurring simulated findings only to VERIFY_NEXT / IMPROVE / NO_ACTION; never automatic FIX_NOW.
- [x] Bind the record to repository, immutable source SHA, workflow run, package, exact APK SHA-256 and version identity from Evidence Graph.
- [x] Keep deterministic FAST/FULL/CERTIFICATION and release-assurance authorities independent from simulated review.
- [x] Add fail-closed Studio projection, Control Center exposure, self-tests and CI/audit/workflow contract gates.

### v4.9.0 — Autonomous Release Assurance

- [x] Reconcile source/build identity, static/test/CI, trusted runtime, Evidence Graph and risk-based validation into one release-assurance record.
- [x] Preserve exact-artifact semantics and fail closed on repository, source SHA, package/version or APK SHA-256 mismatch.
- [x] Consume required physical evidence without treating emulator evidence as physical-device proof.
- [x] Consume trusted distribution evidence only when it is exact-artifact-bound; never infer distribution from certification or build/runtime PASS.
- [x] Consume cross-app pair evidence conditionally while keeping pair PASS independent from single-app PASS/CERTIFICATION.
- [x] Preserve Production Certification Gate as the only certification authority; Release Assurance cannot mint or promote CERTIFIED.
- [x] Emit deterministic PASS / FAIL / BLOCKED assurance plus explicit blockers, failures, next required stage and assurance digest.
- [x] Integrate Release Assurance into True Autonomous Review and AppLab Studio without introducing an opaque numeric score.
- [x] Protect the contract with self-test, workflow/audit invariants and the normal AppLab CI/runtime/governance gates.

### v4.8.0 — Cross-App Verification

- [x] Define paired-artifact verification with producer and consumer source/artifact identities.
- [x] Execute and evaluate explicit COPY, LINK, deep-link handoff and documented fallback transport scenarios.
- [x] Verify idempotency, provenance, ownership and fail-closed behavior across the pair.
- [x] Require paired physical-device evidence when the transport depends on installed apps.
- [x] Keep single-app AppLab PASS/CERTIFICATION distinct from cross-app round-trip PASS.
- [x] Reuse Shared Ecosystem Core v1 instead of inventing a parallel cross-app protocol.
- [x] Reconcile optional Release Reality identities and fail closed on source/artifact mismatch.
- [x] Add trusted-main workflow attestation, deterministic pair digest, 90-day evidence retention and CI/audit-contract gates.

### v4.7.0 — Certification Studio / Release Cockpit

- [x] Show current Release Reality level per project/release.
- [x] Show exact certification blockers and missing evidence.
- [x] Show artifact identity, source SHA, runtime state, evidence freshness and physical requirements.
- [x] Add "Why is this not CERTIFIED?" evidence-driven drill-down.
- [x] Surface regression candidates, recurring findings and stale evidence without opaque scoring.
- [x] Keep Studio read-only for trust-sensitive evidence.
- [x] Add deterministic preview fixture that cannot masquerade as trusted evidence.
- [x] Add implementation self-test, Studio integration, frontend build and CI/version gates.

### v4.6.0 — Evidence Graph 2: Impact, Freshness & Temporal Intelligence

- [x] Extend the canonical graph with deterministic File and Component nodes without inventing semantic architecture.
- [x] Track finding lifecycle as FIRST_OBSERVED, PERSISTENT, RETURNED and RESOLVED while preserving non-causal observation semantics.
- [x] Classify evidence as CURRENT / HISTORICAL / STALE / INVALIDATED.
- [x] Invalidate only historical/stale evidence whose referenced file intersects the trusted changed/dependency-impact set.
- [x] Preserve fresh current-revision evidence even when its source file changed.
- [x] Build bounded impact paths File -> Component -> Capability -> Surface -> Journey -> Evidence from explicit provenance and exact observed journey aliases.
- [x] Add impact, stale-evidence, lifecycle and subject queries with provenance/history.
- [x] Surface changed files, impact paths, invalidated evidence and lifecycle counts in Studio / Control Center.
- [x] Keep source reports authoritative and preserve trusted-runtime, Physical Evidence, Release Reality and Certification authority boundaries.
- [x] Protect the new semantics with implementation-local self-tests, independent regression coverage and audit-contract invariants.

### v4.5.0 — Physical Evidence Hub

- [x] Define a trusted physical-validation record bound to the exact artifact SHA-256.
- [x] Record device model/manufacturer, OS version/build, scenario, preconditions, steps, observed result and hashed evidence references.
- [x] Support capability-labelled evidence for GPS/background, sensors, camera/scanner, biometrics/Keystore, notifications, storage/file flows, OEM battery behavior, OAuth, billing, Play/model delivery and cross-app scenarios.
- [x] Preserve required physical capabilities in the certification policy and require trusted evidence coverage before physical PASS.
- [x] Mark required-but-missing or incomplete physical validation BLOCKED, never PASS.
- [x] Keep physical evidence separate from emulator, Web Preview, simulated-human and distribution/store evidence.
- [x] Retrieve physical evidence by trusted AppLab workflow run id rather than accepting target-authored PASS metadata.
- [x] Revalidate repository/SHA/package/version/exact APK bytes in Trusted APK Verifier before certification or Release Reality consumes the record.
- [x] Keep v4.5 focused on operator-driven real devices already available to the App Factory instead of introducing a device farm.

### v4.4.0 — Release Reality Engine

- [x] Track the release-evidence ladder from IMPLEMENTED through PRODUCTION_RELEASED.
- [x] Create a canonical release record bound to source SHA, package, version/build, APK SHA-256, signing identity and workflow run.
- [x] Distinguish PASS, FAIL, BLOCKED and NOT_VERIFIED at every applicable stage, with policy-driven N/A where a stage is genuinely irrelevant.
- [x] Enforce same-artifact semantics by recomputing the exact APK SHA-256/size before release-state promotion.
- [x] Surface exact certification blockers/failures without a synthetic numeric product score.
- [x] Preserve risk-based validation and keep emulator, physical-device, distribution, store and production evidence as separate authorities.
- [x] Generate release-reality.json / release-reality.md inside the Trusted APK Verifier before Trusted Evidence Manifest hashing.
- [x] Carry Release Reality into Autonomous Review Studio-ready evidence for the future Release Cockpit.

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

### v5.x ongoing technical hardening

The strategic roadmap above does not postpone technical quality. Every version
may include targeted hardening when real AppLab evidence demonstrates a need.

Completed evidence-driven hardening:
- [x] Scope Safe Interaction / Safe Journey crawler ANR and fatal attribution to
  explicit launch/action log windows, preventing stale prior-lab evidence from
  being assigned to a later control while preserving fail-closed target crashes.
- [x] Add deterministic regression coverage proving stale-ANR isolation and
  fresh post-action ANR failure semantics.

Continuous priorities are no longer an unowned backlog. They are now mapped into the formal v5.6 sequence:

- **v5.6A** owns Browser E2E / emulator / WebRTC stability and diagnostics.
- **v5.6B** owns evidence retention, pinning and garbage collection.
- **v5.6C** owns delta-execution experiments and any future coverage-reduction promotion.
- **v5.6D** owns real-data heuristic calibration across repositories.
- **v5.6E** owns physical-device evidence and bounded advanced diagnostic/security pilots.
- Performance, dependency, artifact-provenance and maintainability remain cross-cutting gates in every v5.6 stage.

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

- [x] Validate the external-project adapter on two independent real App Factory Flutter projects:
  Anna's Diary and CamperBoss.
- [x] Promote the AppLab QA/certification process only from real trusted evidence:
  App-Factory-Core now records `CERTIFIED PROCESS` after the Anna's Diary and
  CamperBoss pilots (Core `main@5f6b2489df2ac85fb85ccfea059983a090689de4`).
- Accumulate multi-project runtime/evidence samples to calibrate heuristics, FAST/FULL selection and recurrence thresholds.
- Measure and reduce Browser E2E / emulator infrastructure flakiness without converting transient uncertainty into PASS.
- Introduce physical-device evidence incrementally for capabilities that materially depend on real hardware, OEM behavior or store services.
- Use v4.2 Evidence Graph data to drive freshness/impact work before adding additional standalone intelligence engines. v5.3.2 now feeds compatible prior graph impact back into planning; collect real multi-project samples before allowing any coverage-reducing optimization.
- Treat simulated-human, design and competitor review as advisory layers that complement rather than replace deterministic QA and real-user validation.
