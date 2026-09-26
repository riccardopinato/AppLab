# AppLab v0.9 — Adaptive Impact Analysis & Incremental Verification Engine

## Objective

FAST must be selective, not superficial. AppLab v0.9 moves impact analysis in
front of expensive build/runtime work and spends verification time according to
evidence, risk and confidence.

The fail-safe rule is absolute:

> uncertainty can broaden coverage, but can never reduce it.

## Execution lanes

| Lane | Static checks | APK build | Trusted runtime | Specialist labs |
| --- | --- | --- | --- | --- |
| NO_RUNTIME_CHANGE | no | no | no | no |
| STATIC_ONLY | targeted/full as needed | no | no | no |
| FAST_RUNTIME | targeted/full as needed | yes | yes | impact-selected |
| FULL_RUNTIME | full | yes | yes | all |
| CERTIFICATION | release-quality | release APK | yes | all + certification matrix |

Reduced lanes explicitly record that runtime was not executed and which prior
trusted SHA supplies runtime evidence.

## Trusted diff

For FAST, AppLab requires a valid 40-character baseline SHA, verifies that the
commit exists, then proves:

```
git merge-base --is-ancestor BASELINE HEAD
```

External runners progressively deepen shallow clones (32, 128, 512 commits)
before planning. If ancestry still cannot be established, the plan becomes
FULL_RUNTIME.

Evidence is collected from:

```
git diff --name-status --find-renames BASELINE..HEAD
git diff --numstat --find-renames BASELINE..HEAD
git diff --unified=0 BASELINE..HEAD
```

The plan therefore distinguishes additions, modifications, deletions and
renames, records aggregate line churn and keeps a bounded set of changed hunk
lines for semantic risk signals.

Large diffs (>500 changed files or >20,000 added/deleted lines) do not crash
FAST. They escalate to FULL_RUNTIME.

## Dependency impact

Tracked files are obtained with `git ls-files`. For Dart, Kotlin and Java,
AppLab builds a bounded reverse-import approximation: changed source-file stems
are matched against imports in tracked source files and up to 200 dependents are
added to the impact set.

This graph is deliberately bounded and deterministic. It is not a substitute
for a compiler dependency graph. Its output increases risk/coverage; ambiguity
never authorizes an unsafe skip.

## Risk and confidence

Risk starts from the type and size of the change and is increased by signals
including:

- deletion/rename;
- dependency/build files;
- Android manifest;
- application/package identity;
- minSdk/targetSdk;
- signing configuration;
- database/schema/migration;
- impacted dependent files;
- previous failures in specialist labs relevant to the current change.

Confidence decreases with larger changed/impacted sets and missing supporting
evidence.

High risk (>=70) or low confidence (<0.60) escalates automatically to
FULL_RUNTIME.

## Specialist-lab selection

Path/content/dependency evidence maps changes to:

- System UI / permissions / notifications;
- Performance;
- Network / offline;
- Persistence / restart;
- Configuration / lifecycle;
- Resource pressure / process death;
- Background / Doze / recovery;
- Storage / data integrity;
- Upgrade / migration.

Core launch, crash/ANR, visual journey/regression and safe interaction coverage
remain part of runtime verification and are not represented as specialist skips.

## Targeted quality checks

### Flutter

For high-confidence FAST changes AppLab derives impacted Dart paths and mirrored
test candidates. It can execute:

```
dart analyze <impacted files>
flutter test <matching test files>
```

When targeting is ambiguous, the project has no safe target, risk is elevated,
or the lane is FULL/CERTIFICATION, AppLab uses the complete Flutter checks.

### Native Android / Gradle

Compatible test/lint/build commands are parsed into one Gradle invocation so
configuration and task-graph work are reused. When exactly one affected Gradle
module is unambiguous and risk/confidence permit, unqualified tasks are scoped
to that module. Any command shape that cannot be parsed safely is executed using
the original project commands.

## Historical risk

Repo Watcher restores central history. The planner inspects the last bounded
history window and adds risk for previous FAIL/ERROR specialist-lab outcomes
that are relevant to the current selected domains. Historical evidence is
scoped by repository, watcher history key and source ref; legacy rows that stored
a pinned SHA as their ref are accepted only as a migration compatibility case.

Manual runs without history remain valid: they simply receive no historical
boost. Successful NO_RUNTIME_CHANGE and STATIC_ONLY results are cached by the
same resolved-SHA watcher identity as runtime results, avoiding repeated hourly
analysis of an unchanged commit.

## Shadow FULL calibration

Eligible FAST_RUNTIME target SHAs are sampled deterministically at a 1/10
default cadence. The plan retains `predicted_selected_labs` but executes all
specialist labs as FULL_RUNTIME.

After runtime, `shadow_calibration.py` compares labs FAST predicted it could
skip with the actual FULL results and records:

- divergence list;
- false-negative lab list;
- false-negative count;
- safe/unsafe calibration verdict.

This is the evidence used to tune future thresholds. Thresholds must not be
relaxed based on intuition alone.

## Caching

### Clean AVD

A separate job creates/restores a clean AVD cache keyed by API, architecture and
hardware profile. The verification job uses restore-only semantics, so target
app state is never written back into the shared pristine cache.

### Maestro

The pinned Maestro 2.10.0 installation is cached by runner OS and exact version.

### Domain fingerprints

AppLab fingerprints core/visual verification plus every specialist domain
separately. Repo Watcher uses the domains exercised by the previous trusted run
when constructing the verification cache fingerprint. If no reliable previous
domain set exists it conservatively includes all domains.

## Metrics

`pipeline-metrics.json` records:

- planner latency;
- lane;
- risk score;
- confidence;
- changed file count;
- impacted file count;
- selected specialist-lab count;
- shadow flag/divergence/false negatives;
- available static/test/build stage timings.

Watcher history and Control Center surface lane, risk and confidence.

## Regression corpus

Planner self-tests cover at minimum:

- docs-only change;
- test/static-only change;
- database/persistence change;
- >500-file oversized change;
- dependency impact;
- missing baseline;
- non-ancestor baseline;
- certification forcing full coverage.

New planner rules must add a regression case when they fix a real blind spot.
