# AppLab v6.2 — Exact-Head Gate & Hygiene Evidence (2026-10-28)

Authority: audit and roadmap only; does not certify repairs, physical-device runs, distribution or releases.
Factory baseline: `App-Factory-Core@7b84e33df715cf2a48bda7c7495d0690819bff0f`.
Current live stage: **SELF_CANARY**; no authorization for PILOT_3 or PILOT_5.

## Verified real executions

| Evidence | Identity | Observed result | Counts as autonomous repair? |
|---|---|---|---|
| First event/admission | [Actions #40660650650](https://github.com/riccardopinato/AppLab/actions/runs/40660650650), `079cb2708ccb673330b84b461720ea6d7e4c000e` | Durable v6 WorkItem and operation created; trusted verify `CANCELLED`, final `RUNNER_FAILED_OR_BLOCKED` | **No** |
| Recovery regression PR | [#205](https://github.com/riccardopinato/AppLab/pull/205), head `c27ba697e69be80468b82b44a374eade2dcd8cd7`, merged `7b3e723cf4c4f13c53483dcf38737654d1ad410f` | 7/7 workflow runs green, clean independent Codex exact-head review, squash merge using expected SHA | **No — tests/merge only** |
| New trusted live event | [Actions #40690909916](https://github.com/riccardopinato/AppLab/actions/runs/40690909916), `7b3e723cf4c4f13c53483dcf38737654d1ad410f` | Runner build/verify/finalization success; `op_216bb4fdd014fe467dbfba059d8cbd5d`, `wrk_4ba75596b7f340a3f93a889d`; `VERIFY_ONLY_RUNNER_SUCCEEDED`, `promotion_counted=false` | **No — verify-only** |
| Review permission diagnostic | [#203](https://github.com/riccardopinato/AppLab/pull/203), merged `ae5fb719c317366c9c5f800bfbbe4df9821e4444` | HTTP 403 now produces explicit blocked diagnostics instead of false success; a post-merge scheduled watchdog run is **not yet verified** | **No** |
| Operations read-only bridge | [#206](https://github.com/riccardopinato/AppLab/pull/206) | Proposed v6.2C observation; not authoritative for a repair until exact-head checks, review and real push proof | **No** |

The cancelled job's cause is not established by the GitHub Actions run metadata.
[Issue #204](https://github.com/riccardopinato/AppLab/issues/204) remains open. Never retroactively convert the cancelled receipt into success.

## v6.2D post-gate merge evidence and separate pilot decision

PR #205 passed 7 applicable successful workflows (including CI, CodeQL, Emulator Self Test, governance and pilot contract), then independent Codex review completed on exact head `c27ba697...` with no findings or unresolved threads. The external merge action required a clean mergeable state and `expected_head_sha`. Main was checked at exact squash result `7b3e723...`; the triggered push performed real trusted verification. This demonstrates the external merge **procedure** for that PR. It does not prove a bounded causal repair, or that every future PR is safe to merge.

**PILOT_3 decision: HOLD.** There are 0/3 independent successful autonomous bounded-repair receipts. The v6.2B real failure/recovery campaign is incomplete, v6.2C has no actual causal repair SLO samples and v6.2D authorization requires a distinct future policy review. No automatic promotion, release, modified certification authority, or policy mutation is allowed.

## v6.2E legacy open PR triage — explicit no-merge dispositions

The below is the observed GitHub open-PR backlog; do not assume an open PR is obsolete or safe to merge without exact-head rebase/CI/review. No legacy PR was merged or closed by this audit.

| PR cohort | Examples | Disposition |
|---|---|---|
| Legacy feature against non-main base | [#120](https://github.com/riccardopinato/AppLab/pull/120) Milestone E, base `v54d-final` | **HOLD / MANUAL RECONCILIATION**: not eligible for automatic main merge |
| Runtime/emulator bugfixes | [#98](https://github.com/riccardopinato/AppLab/pull/98), [#97](https://github.com/riccardopinato/AppLab/pull/97), [#82](https://github.com/riccardopinato/AppLab/pull/82), [#77](https://github.com/riccardopinato/AppLab/pull/77), [#72](https://github.com/riccardopinato/AppLab/pull/72) | **REVIEW ONE BY ONE** for relevance against latest main, fresh tests and evidence; no speculative closure |
| Dependency updates | [#113](https://github.com/riccardopinato/AppLab/pull/113), [#112](https://github.com/riccardopinato/AppLab/pull/112), [#81](https://github.com/riccardopinato/AppLab/pull/81), [#80](https://github.com/riccardopinato/AppLab/pull/80), [#79](https://github.com/riccardopinato/AppLab/pull/79), [#78](https://github.com/riccardopinato/AppLab/pull/78), [#70](https://github.com/riccardopinato/AppLab/pull/70) and other Dependabot PRs | **BACKGROUND MAINTENANCE / HOLD** pending separate compatibility and security checks; avoid mixing major upgrades into v6.2 authority gates |

## Remaining release blockers, not silent completions

1. Prove three **distinct real** event → WorkItem → causal investigation → bounded repair (<=5 files, <=250 lines, <=2 attempts) → focused verify → immutable trusted artifact → draft PR → independent review/check-gated external merge receipts. The existing v6.1A workflow admits but does not yet execute the whole causal repair lifecycle. Neither the #205 recovery test nor an Android PASS satisfies this.
2. Investigate #204 cancellation with causal evidence; run real v6.2B failure/recovery scenarios and preserve FAIL/STOP outcomes.
3. Validate v6.2C with real eligible repair receipts and p50/p95 sample counts; unmeasured metrics remain unknown, never zero by default. Confirm review watchdog actual post-merge permissions.
4. Complete exact-head gate/review validation on every subsequent step, update the roadmap only after evidence exists, and conduct a **separate explicit** PILOT_3 policy decision when all safety gates pass.

No Production Certification, physical/store authority or Factory Core changes are implied.
