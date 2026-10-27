# AppLab v6.0B — Causal Repo Investigator

Status: **IMPLEMENTED CANDIDATE / EXACT-HEAD VALIDATION REQUIRED**

## Goal

Turn deterministic AppLab failure evidence into an inspectable repository
localization result before any repair worker is allowed to edit code.

The investigator ranks files from deterministic signals:

1. exact changed-file evidence;
2. dependency-impact evidence;
3. exact path in diagnostic/stack text;
4. diagnostic basename matches;
5. failed specialist-lab path signals;
6. product/surface path signals;
7. Evidence Graph changed/impacted file nodes;
8. prior successful-repair path evidence.

Every score exposes its contributing signals and weights.

## Fail-closed classes

The following never become autonomous code-repair candidates:

- UNKNOWN_FAILURE;
- INFRA_ERROR;
- FLAKY_SUSPECT;
- NONE.

They return `NON_CODE_FAILURE` and `DENY_AUTONOMOUS_EDIT`.

## Deterministic failure classes

Localization is available for:

- APP_RUNTIME_FAILURE;
- APP_VISUAL_FAILURE;
- BUILD_OR_QUALITY_FAILURE.

A deterministic failure can still return `INSUFFICIENT_EVIDENCE` when no
repository file crosses the bounded causal threshold.

## Ambiguity

The investigator records uncertainty rather than hiding it:

- truncated impact analysis lowers confidence;
- bounded repository inventory truncation lowers confidence;
- closely scored top candidates block autonomous repair eligibility;
- absence of an explicit diagnostic path is flagged and blocks multi-candidate repair eligibility;
- stale/mismatched Evidence Graph identity is ignored instead of influencing scores;
- protected paths may be localized but cannot be declared eligible for bounded
  autonomous repair.

## Output

`CAUSAL_REPO_INVESTIGATION_V60B` contains:

- ranked candidate files;
- candidate kind;
- score;
- confidence;
- contributing signals;
- paired regression tests when discoverable;
- required regression targets;
- unresolved uncertainty;
- bounded evidence summary;
- edit recommendation.

The investigator is proposal-only and performs no repository mutation.

## Acceptance

- [x] versioned contract;
- [x] changed/impacted-file scoring;
- [x] diagnostic/stack path scoring;
- [x] specialist-lab and surface scoring;
- [x] Evidence Graph signal support with repository/SHA identity binding;
- [x] prior successful-repair signal support;
- [x] paired test discovery;
- [x] ambiguity/truncation handling;
- [x] protected-path handling;
- [x] UNKNOWN/infra/flaky fail closed;
- [x] CI/self-test wiring;
- [ ] exact-head required checks GREEN;
- [ ] merged after v6.0A.

## Authority

This step does not:

- edit files;
- retry verification;
- create PRs;
- merge;
- release;
- mint PASS/CERTIFIED.
