# AppLab v6.2 — Operational Proof & Reliability

Status: **ACTIVE / v6.2A witness integrated, real repair proof still NOT VERIFIED**.
Baseline: `AppLab/main@ac87ae7cd4fd8ceb4f279847f714257b7c730397`.
Factory baseline: `App-Factory-Core@7b84e33df715cf2a48bda7c7495d0690819bff0f` (Master 26.6 / Golden Index 23).

## Objective

Close the gap between `v6.1 IMPLEMENTATION COMPLETE` and `REAL OPERATIONAL CLOSED LOOP PROVEN`.
Do not treat simulated tests, component CI, v5.5 pilot records, or ordinary APK/runtime PASS as independent closed-loop repair evidence.
The active stage remains `SELF_CANARY`; `PILOT_3` and `PILOT_5` are *not* authorized by this document.

## Stage order, evidence and exit gates

| Step | Objective | Acceptance / gate |
|---|---|---|
| **v6.2A — Self-Canary Real-Evidence Bridge** | Connect existing v6.1 admission/durable operation/WorkItem, investigator, bounded repair, focused verify, exact trusted evidence and draft PR through existing execution authority. | At least 3 independent, real, successful self-canary repair operation receipts with immutable AppLab SHA, operation/WorkItem and GitHub run/PR identity; observed source and artifact identity; zero failures, false repairs, authority breaches, recovery failures or identity violations. No synthetic fixture or plain verification run counts. |
| **v6.2B — Failure & Recovery Campaign** | Exercise real bounded outages, duplicate events, restarted coordinator, expired lease, superseding SHA, stale review/check states, repeated signature STOP and global kill switch. | Immutable negative-case evidence, no terminal redispatch, no false green, deterministic recovery or safe STOP; production fallback kept; recovery decisions independently auditable. |
| **v6.2C — Live Operations Pipeline** | Populate v6.1E read-only report and Studio from real validated closed-loop events without a second evidence authority. | No default zero latency; p50/p95 and sample counts per latency field; event/reconciliation/fallback costs; missing or contradictory evidence fails closed; promotion/rollback recommendation remains advisory. |
| **v6.2D — Post-Gate Merge & Pilot_3 Decision** | Verify actual external merge executor with protected branch, immutable PR head, independent review, exact required checks, and no self-approval. | Green exact-head + independent review + no blocking findings + expected head SHA; no ungated merge; pilot promotion only via separate authorized policy PR after complete live safety evidence, never as side effect of self-canary. |
| **v6.2E — Hygiene & Reliability Closure** | Align README/AGENTS/release docs, triage legacy PRs, extract modules only where bounded budgets demand, and complete final regression. | No stale candidate claims, explicit open-PR decisions, exact-head CI/review green, no reduced FAST/FULL/certification or physical/store authority. |

## Real-self-canary receipt requirements (v6.2A)

Each independently evidenced operation must include:
- actual GitHub event/run identity, immutable source/ref and AppLab verifier SHA;
- persisted event/operation + WorkItem identifiers and serialized repair attempt;
- causal investigation / bounded patch within authorized non-protected files;
- focused test results and new trusted verification evidence bound to exact identity;
- resulting draft PR plus external code-review/check outcomes;
- explicit operation end state, STOP reasons, rollback and whether an external gated merge occurred;
- raw evidence artifact pointers and content hashes suitable for independent audit.

A dry run, unit-test fixture, successful CI on the implementation PR, or successful read-only verification must have `promotion_counted=false`.
Missing evidence => `NOT_VERIFIED` / `HOLD`, not success.
The existing v6.1D threshold of 3 successful operations *and zero* safety violations applies; v6.1E's independent operational gate must also be satisfied.

## Deployment and authority boundaries

- `SELF_CANARY` only until the real evidence gates are met.
- No new scheduler, duplicate queue, verifier, certification authority or unbounded polling.
- Reuse v5.4/v5.5 durable store, queue, watcher and GitHub Actions fallback.
- Repair scope max 5 files, 250 changed lines, 2 attempts; LOW/NORMAL mutation only.
- No writes to App-Factory-Core, workflows/policy, branch protection, secrets, release or main by the autonomous fix worker.
- No autonomous self-review, unreviewed merge, bypass, release or promotion.
- Stage transitions remain `SELF_CANARY -> PILOT_3 -> PILOT_5`, with separate explicit policy change each time.
- `ALL_COMPATIBLE` is not authorized.

## Work classification

P0/P1 or trust-boundary, artifact identity, data loss, false PASS or critical security => `BLOCKING_NOW`.
Changes introduced by the current step => `FIX_CURRENT_STEP`.
Old dependency PRs, documentation drift and bounded refactor => `BACKGROUND_MAINTENANCE`, unless newly shown to be blocking.

## Current evidence status

- v6.1A–E: merged and exact-head CI validated; closure evidence in `integration/roadmap/V61_COMPLETION_EVIDENCE_2026-10-27.md`.
- Live v6.1 closed-loop repairs: **NOT VERIFIED / insufficient evidence**.
- Promotion: **HOLD AT SELF_CANARY**.
- v6.2A bridge: PR #202 merged to `main@079cb2708ccb673330b84b461720ea6d7e4c000e` with independent exact-head review and CI. This is a witness implementation, **not** repair proof.
- v6.2A live receipt: run https://github.com/riccardopinato/AppLab/actions/runs/40660650650 bound a real operation/WorkItem and finalized a `CANCELLED` runner as `RUNNER_FAILED_OR_BLOCKED`, `promotion_counted=false`. Root cancellation actor/cause remains **UNPROVEN**; see issue #204.
- v6.2B recovery regression candidate: cancellation remains terminal/blocked under exact-source replay; a different immutable SHA can open a separate safe admission. This regression is NOT a real successful retry or repair.
- Watchdog diagnostics: PR #203 merged to `main@ae5fb719c317366c9c5f800bfbbe4df9821e4444`; HTTP 403 audit receipts are fail-closed. A successful post-merge scheduled review request is still **NOT VERIFIED**.
- Three distinct real autonomous causal repair operations: **0/3 VERIFIED**. v6.2B/C/D/E production gates remain open.
- Promotion: **HOLD AT SELF_CANARY**.
