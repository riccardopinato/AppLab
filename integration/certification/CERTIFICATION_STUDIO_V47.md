# AppLab v4.7 — Certification Studio / Release Cockpit

AppLab v4.7 turns the existing trusted release evidence into a compact, read-only
Certification Studio view. It does **not** introduce another certification
authority.

## Purpose

For every project/release with `release-reality.json`, Studio can answer:

- how far the exact artifact has actually progressed;
- whether certification is PASS/BLOCKED/FAIL/NOT_VERIFIED;
- why a release is not CERTIFIED;
- which exact source SHA, package/version and APK SHA-256 the evidence refers to;
- what trusted runtime evidence exists;
- whether physical-device evidence is required/present;
- whether relevant evidence is stale or invalidated;
- whether regressions or recurring findings deserve attention.

## Authority model

The Cockpit is a deterministic projection only.

Authoritative inputs remain:

1. `release-reality.json` for release ladder, artifact/source identity,
   runtime state and the pre/post-certification lifecycle;
2. finalized `certification.json`, when present, for the authoritative final
   certification status and compatibility-matrix blockers;
3. `evidence-graph.json` for derived freshness/recurrence views;
4. `longitudinal-intelligence.json` for regression candidates.

When finalized certification exists, Studio accepts it only when repository,
source SHA, package/version and APK SHA-256 reconcile with Release Reality.
Mismatch or incomplete identity fails closed as BLOCKED.

Studio MUST NOT:

- mutate trusted evidence;
- promote a release level;
- generate a synthetic certification score;
- convert missing/BLOCKED evidence into PASS;
- treat emulator/runtime evidence as physical-device proof;
- treat certification as distribution/store/production proof.

## Projection contract

`scripts/certification_studio.py` emits a bounded `release_cockpit` object
containing:

- `current_level`, `highest_observed_pass`;
- `certification_status`, `certified`;
- source repository/ref/resolved SHA;
- package/version/build variant/APK SHA/signing identity;
- exact-byte verification;
- workflow run, trusted AppLab SHA and runtime state;
- explicit real-device requirement, required physical capabilities and physical evidence state;
- stale/historical and invalidated evidence counts;
- recurring findings and regression candidates;
- unresolved stages;
- `why_not_certified` with exact blockers/reasons.

The projection is explicitly marked `read_only: true`.

## "Why is this not CERTIFIED?"

The drill-down is evidence-driven. It uses, in order:

1. exact `certification_blockers` emitted by Release Reality;
2. the next unresolved release gate;
3. unresolved release stages.

Rows are deduplicated and are not silently truncated. Only certification
prerequisites through `PHYSICAL_DEVICE_VERIFIED` participate in this drill-down;
distribution, store-readiness and production-release stages remain separate
post-certification lifecycle evidence. If no authoritative reason exists,
Studio says the evidence is incomplete rather than inventing a cause.

## Web Preview boundary

The static Web Preview uses a deterministic fixture to exercise the UI. The
fixture deliberately remains NOT_VERIFIED/BLOCKED and states that trusted
release evidence is absent. A Web Preview is never certification evidence.

## Validation

v4.7 is covered by:

- `scripts/certification_studio.py` self-test;
- Studio snapshot self-test/integration;
- frontend TypeScript/Vite build;
- backend tests and health/version check;
- existing audit/workflow contracts and CI.

END
