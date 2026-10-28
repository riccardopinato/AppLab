# v6.2A — Live Self-Canary Witness

Status: **INTEGRATION CANDIDATE; no autonomous repair proof yet**.

The existing v5.4G live GitHub Actions canary is the only dispatcher. The v6.1A
component reuses its durable SQLite event/operation identity and persists a
v6 WorkItem; it does not dispatch again. A v6.2A witness binds these two records
to GitHub run ID/attempt and the exact self-repository SHA, and then records
the v5.4G trusted-runner job outcome.

Each witness deliberately includes `promotion_counted=false` and
`bounded_repair_verified=false` even if the runner succeeded: validation of an
APK is *not* evidence of a causal bounded repair, draft PR, external review,
or post-gate merge. The witness is non-authoritative operation observation,
not an independent trusted evidence manifest or cryptographic proof of the
upstream GitHub event. Raw JSON artifacts remain available for review.

Initial acceptance requires one real main-branch run that emits:
- `v54g-admission.json` with dispatch=true;
- `v61a-closed-loop.json` with shared durable operation, exact SHA and WorkItem;
- `v62a-admission-witness.json` with GitHub run/delivery binding;
- `v54g-final.json` and `v62a-final-witness.json` if execution finishes.

The actual three successful repair operations and all v6.1D/v6.1E safety
thresholds remain PENDING. No promotion beyond SELF_CANARY is performed.
