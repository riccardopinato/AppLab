# AppLab v6.2 — implementation handoff / live proof continues independently
Date: 2026-10-29

## Decision
Close **v6.2 feature-development scope** after this PR passes required exact-head
checks, receives independent review, and merges. Do **not** mark v6.2
production-proven, real autonomous repair certified, or PILOT_3 enabled.
Factory baseline: App-Factory-Core@174a05e165076c9e4b2d61a20acd85ca6b215f12
(CURRENT Master v27 ACTIVE, Golden Index 23).
Input baseline: AppLab/main@7604a2c82812c743c5c10649251d40942c6378e1,
PR #209 merged 2026-10-29.

## Delivered implementation and trust boundaries
- v6.2A: exact-sha real-main admission, durable v6 WorkItem, causal investigator,
  bounded worker, focused regressions, immutable local patch artifact and draft
  stewardship. This handoff adds a distinct GitHub Actions **draft-only** publisher:
  re-read authentic failure, independently rerun the deterministic repair,
  require equality to the existing patch SHA-256 before any remote write,
  and create a draft PR on a nonprotected repair branch. Only AppLab itself
  is allowlisted. A draft is not an approved fix.
- v6.2B: cancelled-run/duplicate event regression and recovery path remain active;
  root cause of first real cancellation stays open in #204.
- v6.2C: read-only live receipt/operational evidence with missing fields never
  defaulted to success. Existing v6.1E is the only production evidence authority.
- v6.2D: independent exact-head review, protected branch gates and external
  merge remain mandatory. The autonomous draft steward cannot self-approve,
  merge, release or promote a rollout stage.
- v6.2E: roadmap/README/hygiene alignment. Existing hourly Continuous Maintenance
  now samples recent real AppLab push/canary runs and bounded repair artifact
  metadata and uploads a report for ongoing observation.

## Three proofs: background operational campaign, NOT deleted
Issue #208 continues to require three distinct genuine, successfully completed
causal repairs with immutable source/operation/WorkItem, bounded patch,
trusted exact-head verification, actual draft PR, independent review and
external protected merge. Each evidence chain must also satisfy v6.1E operations
and recovery safety gates. Observed complete count **0/3** at handoff.
A green CI, merely observed artifact name, proposed patch or generated draft
cannot increment the count. This background data collection must not silently
promote SELF_CANARY -> PILOT_3 or PILOT_5. Explicit separate policy and gate
review are still needed before any new repository acquires mutation authority.

## Running in the meantime
Users can continue working on other apps while AppLab's existing watcher and
maintenance workflows collect evidence. The new observer is read-only and
non-authoritative: `.applab-maintenance/v62-background-proof.json` and `.md`
are uploaded alongside regular maintenance artifacts. The sample is bounded to
GitHub's newest API page, not a fabricated lifetime total; candidate artifact
metadata is never called a complete repair.

## Exact-head release acceptance
- Source and workflow changes reviewed on the same immutable PR head.
- CI, CodeQL, emulator, canonical fixture, governance, live browser and
  controlled event checks all applicable and green.
- No unresolved blocking independent-review findings or review threads.
- Protected squash merge performed by external post-gate authority.
- New main SHA and post-merge observation checked independently.
Until those checks finish, the state is **IMPLEMENTATION_HANDOFF_PENDING**.
