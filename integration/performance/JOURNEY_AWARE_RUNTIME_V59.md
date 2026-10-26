# AppLab v5.9 — Journey-Aware Runtime

Status: **v5.9A IMPLEMENTED / PLANNING ONLY / COVERAGE REDUCTION DISABLED**

## Goal

Reduce ordinary commit-to-green time by making custom Maestro coverage aware of
the exact change, without weakening FULL, certification, artifact identity or
physical/store evidence boundaries.

## v5.9A contract

The optional `journeys.catalog` object in `applab.project.json` may declare up
to 32 journeys. Each entry contains:

- `flow`: repository-relative Maestro YAML/YML path;
- `paths`: bounded repository path globs that can impact the journey;
- `labs`: specialist labs whose selection also implies the journey;
- `surfaces`: semantic product surfaces for evidence/review;
- `capabilities`: semantic capabilities for evidence/review;
- `risk_class`: `core | normal | deep`;
- `always_fast`: explicit core sentinel selection.

Example:

```json
{
  "schema_version": 1,
  "journeys": {
    "catalog": {
      "shell-smoke": {
        "flow": ".maestro/journey/shell-smoke.yaml",
        "paths": ["lib/app/**", "lib/navigation/**"],
        "labs": ["configuration"],
        "surfaces": ["home", "navigation"],
        "capabilities": ["navigation"],
        "risk_class": "core",
        "always_fast": true
      },
      "vault-deep": {
        "flow": ".maestro/journey/vault-deep.yaml",
        "paths": ["lib/**/vault*.dart", "lib/security/**"],
        "labs": ["persistence", "storage"],
        "surfaces": ["vault"],
        "capabilities": ["crypto", "secure_storage"],
        "risk_class": "deep",
        "always_fast": false
      }
    }
  }
}
```

## Selection semantics

For `FULL_RUNTIME` and `CERTIFICATION`, every declared journey is selected.

For `FAST_RUNTIME`, a journey is selected when at least one of these holds:

1. it is `risk_class=core`;
2. it is `always_fast=true`;
3. a changed/impacted path matches one of its declared path globs;
4. one of its declared specialist labs is selected by Smart Test Plan.

Changed runtime paths not covered by a catalog path are retained in
`journey_selection.unmatched_paths`. Such a plan is not eligible for selective
runtime enforcement.

## v5.9A authority boundary

v5.9A is deliberately observational/planning-only:

```text
coverage_reduction_enabled = false
```

The existing primary Maestro flow remains runtime authority. Invalid catalog
metadata cannot reduce coverage. Recomputed post-build selection must exactly
match preflight selection, and the selection participates in execution identity.

v5.9B is the first stage allowed to execute journeys atomically, and only after
its own fallback/retry contract and exact-head validation.

## Expected Anna's Diary pilot

Anna's Diary is the first intended downstream pilot because its current primary
flow embeds a costly Vault deep lifecycle. v5.9A allows AppLab to measure when
`vault-deep` would or would not be selected before any actual skip is enabled.

The target is not to make FULL cheap. The target is to keep deep Vault/security
coverage for relevant changes and FULL/certification while removing it from
ordinary unrelated UI/navigation changes once v5.9B is proven.
