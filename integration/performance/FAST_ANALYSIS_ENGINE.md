# AppLab v0.9.0 — FAST Analysis Compatibility Contract

> v0.9 supersedes the v0.8.1 path-only Smart Test Planner with the Adaptive Impact Engine. The historical details below remain valid for compatibility, but current lane/risk/confidence semantics are defined in `ADAPTIVE_IMPACT_ENGINE.md`.

Current FAST invariants:
- trusted range is still last matching verified SHA → current SHA;
- the baseline must now also be an ancestor of HEAD;
- FAST can terminate as NO_RUNTIME or STATIC_ONLY before APK/emulator work;
- runtime FAST keeps core launch/crash/visual/interaction checks and selects specialist labs using path, content, dependency blast radius, risk and history;
- unsafe/oversized/low-confidence/high-risk changes escalate to FULL;
- deterministic shadow FULL sampling measures false negatives;
- FAST cannot publish a production-certified APK and SKIPPED is never PASS.

## Historical v0.8.1 design

AppLab keeps three explicit verification modes:

- `fast`: continuous analysis with core launch/crash/visual/interaction checks plus only the specialist labs relevant to the changed files;
- `full`: the complete diagnostic suite and normal baseline-seeding path;
- `certification`: the production release gate.

Repo Watcher defaults to FAST. Manual project verification defaults to FULL.

## Trusted changed-file range

v0.8.1 does **not** classify only the last commit. Repo Watcher restores central history and supplies the most recent verified SHA for the target repository. The build runner retrieves that commit when available and the Smart Test Planner calculates:

```
last verified SHA .. current SHA
```

Every changed path across that whole range participates in specialist-lab selection. This prevents an intermediate database/network/background change from being hidden by a later documentation-only commit.

The range is stored in the isolated contract as `analysis_baseline_sha` and in `analysis-plan.json` as `baseline_sha`. The trusted verifier requires both values to agree.

If the previous SHA is missing, invalid or cannot be retrieved, changed-file discovery yields no trusted range and FAST safely falls back to FULL.

## Specialist selection

Core launch, crash/ANR detection, Maestro when enabled, Visual Journey and Safe Interaction Crawler remain outside selective specialist skipping.

Typical selections include:

- UI/Compose/Flutter screen change → Configuration + Performance;
- networking/API/sync → Network and related background/performance coverage;
- Room/database/migration → Persistence + Storage + Upgrade;
- service/worker/notification → Background + Resource Pressure/System as matched;
- manifest/permissions → System UI and Upgrade where applicable.

Skipped specialist labs remain explicitly `SKIPPED`; they are never converted to PASS.

## Baseline safeguards

FAST still falls back to FULL when trusted visual/upgrade baselines required by the runtime verifier are unavailable. FAST does not promote Performance or Upgrade baselines and cannot publish a production release APK.

## Evidence

- `contract.json`: requested mode and last verified SHA;
- `analysis-plan.json`: complete changed-file range, selected labs and reasons;
- `result.json`: effective analysis mode;
- Control Center: latest FAST/FULL/CERTIFICATION result plus separate production-certification state.

The planner self-test creates a real temporary Git repository with multiple commits and verifies that a database change in an intermediate commit is still detected even when the final commit changes only documentation.
