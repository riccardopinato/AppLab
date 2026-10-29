# AppLab v6.3B — journey coverage telemetry (diagnostic-only)

App Factory baseline: `174a05e165076c9e4b2d61a20acd85ca6b215f12` (v27).
AppLab parent: `79309588e117ca5481822cd6394a9ad8ecc338e7`.

## Purpose
The FAST planner can be unable to run atomic Maestro journeys because modified runtime/test files are not represented by a trustworthy journey catalog. For example, the Anna's Diary run 40847530142 selected FAST but reported `CATALOG_PARTIAL_UNMATCHED`; `.maestro/applab-smoke.yaml` and `.maestro/journey/personalization.yaml` were unmatched, requiring a LEGACY_FALLBACK. The trusted Android verifier step took 1192 s in that run. This is historical evidence, **not** a measurement of the new cache pilot.

## Change
Add bounded fields to the existing schema 3 `pipeline_metrics.json` produced by AppLab:
- `journey_selection_state`
- `journey_catalog_count`, `journey_selected_count`
- `journey_unmatched_path_count` and up to 25 unmatched paths (count bounded to the already capped planner evidence)
- `journey_enforcement_eligible`

These fields are **informational only**. No change to journey selector, lane selection, FAST/FULL/CERTIFICATION coverage, retries, fallback authority, SHA or APK identity. A missing/malformed selection remains non-eligible, not an inferred PASS.

## Test and rollout
The existing pipeline metrics self-test now covers unmatched, eligible and malformed inputs. CI must run the unchanged required workflow contracts. Observe this telemetry in downstream AppLab artifact evidence before changing any Anna's Diary journey mapping or promoting shadow sharding. A catalog correction may only replace legacy checks when the complete relevant test coverage is independently established, including real Vault PBKDF2, wrong-password and persistence checks. Otherwise preserve the authoritative legacy behavior.

This pilot does not itself reduce build or runtime latency.
