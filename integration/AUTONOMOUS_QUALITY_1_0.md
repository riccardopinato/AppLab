# AppLab v1.0 — Autonomous Quality Platform

AppLab v1.0 completes the roadmap from adaptive verification to a project-aware
quality platform. The trust boundary is unchanged:

```
Target source -> Build job -> isolated APK contract -> Trusted verifier
```

Learning may increase coverage or force FULL. It may never turn failing evidence
into PASS and may never bypass certification requirements.

## v0.10 — Self-Optimizing Verification

- Per-project learning profiles are built from central watcher history only after
  a minimum useful sample is available.
- Recurrent WARN/FAIL/ERROR domains can be added to FAST coverage.
- Multiple severe historical domains can conservatively escalate FAST to FULL.
- Dependency impact metadata now records an explicit impact graph v2.
- The per-file 100-import bound is explicit; truncation lowers confidence and
  can force FULL rather than silently trusting partial evidence.
- Each execution lane has a wall-clock budget and records budget pressure.
- Failure intelligence separates trusted application failures from probable
  transient infrastructure failures and unknown failures.
- Flaky detection is advisory only and never converts FAIL to PASS.

## v0.11 — Project Intelligence

Every verification emits a compact `project-state.json` containing:

- repository/ref/resolved SHA and trusted baseline SHA;
- result, lane, risk and confidence;
- selected SHOS playbook;
- project-learning influence;
- verification budget;
- release-readiness state;
- explicit platform limits.

Cross-project learning is deliberately controlled. Signals require repeated
evidence across multiple repositories and are advisory only; project-specific
evidence remains authoritative.

## v0.12 — SHOS / AppLab Integration

Changes are deterministically classified into a SHOS-oriented work category.
The corresponding playbook can add mandatory specialist coverage:

- database migration -> persistence + storage + upgrade;
- UI redesign -> configuration + performance;
- release/operations -> configuration + performance + upgrade;
- tests/docs remain on their safe reduced lanes when applicable.

The final result also emits a deterministic release-readiness scorecard and
knowledge-feedback sidecar. Readiness is gate based, not a subjective numeric
score.

## v1.0 — Autonomous Quality Platform

Repo Watcher now consumes failure intelligence:

- non-retryable application defects at the same SHA are not scheduled again;
- transient/unknown failures receive bounded retries;
- retryable failures stop after three attempts unless the user forces a run;
- a new SHA is always evaluated normally.

Control Center surfaces learning usage, flaky suspects, retryable failures,
verification-budget pressure, playbook classification and release readiness.

## Safety invariants

1. Learning cannot reduce required certification coverage.
2. Flaky classification is never a PASS override.
3. Truncated impact evidence broadens verification.
4. Cross-project signals do not override project-specific evidence.
5. Application failures are not hidden behind automatic retries.
6. Infrastructure retries are bounded.
7. Physical-device requirements remain explicit and cannot be inferred from
   emulator evidence.
