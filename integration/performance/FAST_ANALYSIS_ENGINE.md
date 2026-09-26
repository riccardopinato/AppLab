# AppLab v0.9.0 — FAST Analysis & Adaptive Verification

FAST is a safety-preserving adaptive verification mode. It does not mean "skip checks for speed": it means **spend verification time only where current evidence supports doing so, and escalate when uncertainty increases**.

## Execution lanes

The pre-build Impact Engine chooses one lane:

- `NO_RUNTIME_CHANGE`: documentation/non-runtime sources only. No Flutter/Gradle setup, APK build or emulator. The result explicitly records inherited trusted runtime evidence.
- `STATIC_ONLY`: test, lint or CI/static surfaces only. Static verification runs; APK/runtime gates remain `SKIPPED`.
- `FAST_RUNTIME`: runtime change with acceptable risk/confidence. Core launch/crash/visual/interaction verification always runs; specialist labs are impact-selected.
- `FULL_RUNTIME`: complete build/runtime suite. Selected automatically for unsafe baselines, large changes, high risk or low confidence.
- `CERTIFICATION`: explicit production release gate. All mandatory labs and release-integrity checks run.

Manual verification defaults to FULL. Repo Watcher requests FAST. Production Certification requests CERTIFICATION.

## Trusted range and identity

The watcher baseline is accepted only when it matches the current repository, ref, history key, engine (where explicit) and configuration fingerprint. The build runner retrieves a bounded commit graph and AppLab proves that the baseline commit exists and `git merge-base --is-ancestor baseline HEAD` succeeds. If either condition fails, FAST escalates to FULL.

The impact range is always `last trusted verified SHA .. current resolved SHA`; it is never limited to the last commit.

## Change evidence

The planner combines `git diff --name-status --find-renames`, `git diff --numstat`, zero-context changed hunks, additions/deletions/renames, total file count and line churn, path/content signals, source dependency impact and recent AppLab failure history.

More than 500 changed files or an oversized diff is treated as low-confidence/high-risk and escalates to FULL instead of failing open.

## Dependency impact graph

Tracked source inventory comes from `git ls-files` with filesystem walking only as fallback. For Dart, AppLab resolves local relative imports and imports through the current package name. For Kotlin/Java it maps packages/imports and constructs reverse dependencies. Changed files are expanded through bounded reverse-dependency depth to identify impacted source, modules and likely tests.

The graph is deliberately lightweight and deterministic; an unavailable/oversized graph reduces confidence rather than inventing certainty.

## Risk and confidence

Risk combines change type, sensitive surfaces, code churn, breadth of dependency impact and historical failures. Confidence falls when semantic classification or dependency coverage is weak.

Typical escalation rules:

- database/schema/migration/build/manifest/service changes raise risk;
- large or cross-cutting diffs raise risk;
- previous failures in an affected lab raise risk and may force that lab into the FAST plan;
- missing/untrusted baseline, non-ancestor baseline, excessive diff, HIGH/CRITICAL risk or low confidence → FULL.

Uncertainty therefore increases coverage.

## Static verification

When safe, Flutter verification targets impacted analyzer paths and tests. If targeted inputs are unavailable or a project uses a non-standard working-directory layout, AppLab falls back to full `flutter analyze` / `flutter test`.

Native Android creates a safe Gradle execution plan. For impacted modules it first probes module-specific test/lint tasks with `--dry-run`; if Gradle does not expose those tasks, AppLab falls back to the original full task graph. Compatible test/lint/build tasks are executed in one Gradle invocation so configuration and intermediate outputs are reused.

## Runtime specialist labs

Core launch, crash/ANR detection, Maestro when enabled, Multi-Screen Visual Journey and Safe Interaction Crawler remain mandatory for runtime lanes. Specialist labs remain System, Performance, Network, Persistence, Configuration, Resource Pressure, Background, Storage and Upgrade. Skipped labs are reported as `SKIPPED`, never `PASS`.

## Shadow FULL calibration

Eligible FAST_RUNTIME commits are deterministically sampled for an additional FULL run. AppLab compares the selected FAST plan with FULL evidence and records false negatives, core-runtime divergence, over-selection and sampled-run counts. Any false negative turns the main result into FAIL and historical instability feeds future risk. Sampling frequency increases when prior false negatives exist.

## Cache and runtime acceleration

AppLab caches only reusable deterministic foundations: pinned Maestro installation, a clean Android AVD snapshot keyed by API/system image/architecture/profile, existing visual/performance/upgrade baselines and watcher verification identity. The verification emulator restores the clean snapshot with `-no-snapshot-save`; target app state is not persisted into the reusable AVD.

Verification fingerprints are domain-aware: changes to an unrelated specialist lab do not invalidate results whose selected verification contract did not include that domain.

## Metrics

Watcher history supports lane distribution, specialist skip ratio, cache-hit ratio, risk/confidence distribution, shadow false-negative/over-selection counts, and planner/build/emulator/runtime/total duration with p50/p95-ready summaries. These metrics are evidence for future tuning; AppLab does not claim arbitrary speedup percentages without measured runs.

## Release safety

FAST cannot certify production and cannot publish the verified release APK. FULL is a quality/baseline path, not production certification. Only CERTIFICATION can authorize release bytes.
