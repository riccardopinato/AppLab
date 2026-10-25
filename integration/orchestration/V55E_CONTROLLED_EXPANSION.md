# AppLab v5.5E — Controlled Expansion

Status: **IMPLEMENTED AS EVIDENCE-GATED EXPANSION CONTROL / LIVE PROMOTION NOT INFERRED**

v5.5E defines and tests the complete bounded rollout sequence from the original three-repository pilot to a five-repository cohort and then to every currently enabled compatible watcher target. The policy is intentionally fail-closed: a stage can promote only when every repository in the next stage has the configured successful-operation evidence and no failures.

The implementation provides both a global kill switch and independent per-repository kill switches. A killed repository cannot dispatch even when it belongs to the active stage. Repositories outside the selected stage cannot dispatch.

The `ALL_COMPATIBLE` inventory is checked against the enabled `watchlist.json` inventory on every proof run, so adding or removing an enabled compatible target requires the expansion policy to be reconciled before CI can pass.

This milestone does **not** claim that all repositories have already accumulated live promotion evidence. It implements the controlled 3 -> 5 -> all-compatible mechanism and proves that insufficient or failed evidence holds promotion. Live stage advancement remains an operational evidence decision.

The hourly Repo Watcher remains `PRIMARY_SCHEDULER_PLUS_RECONCILIATION`. v5.5E explicitly sets `watcher_demotion_allowed=false`; changing it to reconciliation/watchdog-only requires separate sufficient production evidence and is not inferred from CI.

Authority remains unchanged. The expansion controller is `ORCHESTRATION_ONLY`; Smart Test Plan remains FAST/FULL planning authority, Trusted Verifier remains runtime evidence authority, Release Assurance remains assurance authority, Production Certification remains the sole certification authority, GitHub Actions remains fallback, and `coverage_reduction_enabled=false`.
