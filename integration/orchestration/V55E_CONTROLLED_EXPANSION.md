# v5.5E — Controlled Expansion

v5.5E expands the v5.5 event-driven orchestration boundary in explicit stages: **3 -> 5 -> all compatible repositories**.

## Guardrails

- Global kill switch and per-repository kill switches remain fail-closed admission controls.
- Only enabled watchlist entries with a supported Android/Flutter engine are compatible.
- The original AppLab/CamperBoss/TrailPath pilot remains the immutable stage-3 prefix.
- Stage 5 adds exactly two compatible watchlist repositories; all-compatible is derived from the current enabled watchlist.
- GitHub Actions remains the fallback executor.
- Smart Test Plan, Trusted Verifier, Release Assurance and Production Certification authority are unchanged.
- `coverage_reduction_enabled=false`.
- The hourly watcher remains scheduler + reconciliation until sufficient all-compatible rollout evidence exists. Only then may its role become reconciliation/watchdog; this proof does not remove the watcher.

## Evidence semantics

The v5.5E contract self-test proves stage monotonicity, global kill-switch rejection, isolated per-repository rejection, unchanged fallback/reconciliation and the evidence gate on watcher-role transition. It does not claim physical-device, store/distribution or production certification evidence.
