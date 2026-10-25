# AppLab v5.4G — Controlled Event-Driven Pilot

Status: **CONTROLLED LIVE CANARY IMPLEMENTED / AUTHORITY UNCHANGED**

v5.4G is the first bounded live event-driven execution path in the v5.4 program.

It does **not** replace AppLab verification authority. It only moves one tightly scoped canary from periodic discovery to immediate GitHub event admission.

## 1. Live scope

The live allowlist contains exactly one target:

```text
repository: riccardopinato/AppLab
source_ref: refs/heads/main
project: selftest
engine: native_android
requested analysis_mode: fast
```

A GitHub `push` event on `main` for the controlled-pilot/selftest paths may create one real verification Operation.

Pull-request runs are admission-only dry runs.

Manual workflow dispatch is dry-run by default and can request live execution only on `main`.

No external application repository is live in v5.4G.

## 2. Event trust boundary

v5.4C remains the raw GitHub webhook/HMAC normalization design.

The v5.4G canary uses GitHub Actions' authenticated platform event delivery directly.

The normalized Event explicitly records:

```text
source = github_actions_platform
trust_attestation.method = GITHUB_ACTIONS_PLATFORM_EVENT
raw_webhook_hmac_observed_by_applab = false
```

The existing Event contract trust booleans represent inherited provider authentication for this platform-delivered path. v5.4G does not pretend to have observed a raw webhook HMAC header.

## 3. Execution path

```text
GitHub push
  -> controlled-event-pilot.yml
  -> durable Event persistence
  -> idempotent VERIFICATION Operation
  -> durable per-repo queue
  -> GitHub Actions lease intent
  -> existing external-native-android-runner.yml
  -> Smart Test Plan
  -> existing trusted build/runtime verification
  -> Attempt + terminal Operation/queue evidence
```

Smart Test Plan remains the FAST/FULL authority.

The runner/verifier remains verdict authority.

Production Certification remains the only certification authority.

## 4. Pilot ledger

The canary uses the existing v5.4B/v5.4E SQLite reference store during the workflow.

For best-effort cross-run continuity, the finalized database is saved in an Actions cache and every admission/finalization is uploaded as a 30-day artifact.

This continuity layer is explicitly:

```text
NON_AUTHORITATIVE_PILOT_CONTINUITY
```

Actions cache is not promoted to the production durable database.

Loss or eviction of the cache cannot convert missing evidence to PASS.

## 5. Idempotency

The logical Event dedupe key remains repository/ref/SHA based.

Operation identity additionally binds the AppLab SHA and contract fingerprint.

Therefore:

- redelivery of the same target under the same AppLab revision does not redispatch after terminal completion;
- the same target SHA under a new AppLab revision is a distinct Operation;
- unrelated repository/ref/SHA identities do not collide.

## 6. Kill switch

`integration/orchestration/v54g-pilot.json` contains:

- `enabled`;
- `kill_switch`;
- exact pilot target allowlist;
- one-operation-per-event bound.

When the kill switch is true, the Event/Operation may still be recorded in dry-run form, but no live runner dispatch can occur.

## 7. Failure behavior

A successful runner job records:

- immutable Attempt;
- queue `DONE`;
- Operation `SUCCEEDED`.

A failed/cancelled runner job records:

- immutable failed Attempt;
- queue `BLOCKED`;
- Operation `FAILED`;
- `watchdog_required = true`.

The pilot itself does not retry a failed runner merely to seek green.

The hourly Repo Watcher remains the independent recovery/watchdog path.

## 8. Watcher remains active

v5.4G does not alter the hourly watcher schedule.

The existing periodic watcher remains responsible for:

- catching missed event-driven activity;
- independent repository head reconciliation;
- normal portfolio-wide verification;
- fallback after event-driven canary failure.

The event-driven pilot is additive, not a replacement.

## 9. GitHub Actions fallback

The live canary deliberately uses `GITHUB_ACTIONS` as executor.

v5.4F warm-worker evidence is a promotion study, not permission to make self-hosted warm runtime the live authority.

Future use of a persistent warm worker requires a separate operational infrastructure decision and exact worker identity/cleanup evidence.

## 10. Certification boundary

v5.4G cannot:

- request certification mode;
- publish a certified artifact;
- create CERTIFIED;
- bypass Release Assurance;
- bypass Physical Evidence requirements;
- mutate Production Certification.

The canary requests `analysis_mode=fast`; Smart Test Plan can still escalate coverage.

## 11. PR behavior

On pull requests the same admission code executes with:

```text
live_requested = false
```

This verifies:

- allowlist matching;
- Event validation;
- Operation idempotency;
- queue integrity;
- output contracts;

without executing the live reusable runner.

## 12. Live workflow evidence

The workflow publishes:

- `APPLAB_V54G_ADMISSION`;
- the pilot control-plane database;
- `APPLAB_V54G_FINAL` after a live dispatch.

Artifacts are retained for 30 days.

The live reusable runner continues to publish its normal AppLab evidence independently.

## 13. Rollback

Rollback is immediate and bounded:

1. set `kill_switch=true` in the pilot config; or
2. disable/remove the controlled event workflow.

The hourly watcher remains available throughout rollback.

No target repository configuration must be changed to roll back the self-repo canary.

## 14. Exit criteria

v5.4G is considered technically implemented when exact-head gates prove:

- A-F contracts remain green;
- G admission/finalization self-test PASS;
- dry-run PR workflow PASS;
- live self-repo `main` canary runs through the existing trusted runner;
- failure remains FAIL/BLOCKED;
- duplicate terminal Operation does not redispatch;
- kill switch prevents dispatch;
- no external repo is admitted;
- hourly watcher remains scheduled;
- certification authority is unchanged.

A future expansion beyond the self-repo canary is a separate rollout decision, not implied by completion of v5.4G.
