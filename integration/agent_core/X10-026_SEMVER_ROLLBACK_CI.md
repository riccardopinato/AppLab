# X10-026 — Real 0.1.1 → 0.1.0 source-package version rollback CI

**Factory baseline:** `App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619` (Master v27, Index v29). **Scope:** two real Flutter consumer source trees and a real SemVer dependency switch, not a device downgrade or Golden promotion.

## Immutable versions and consumers

| Role | Immutable Git SHA | Package version |
| --- | --- | --- |
| Profile kit 0.1.1 | `Idee-app-Archivi-riferimenti@710e83261bcadc1cfd5eda3e28d77bed8b8bc576` | 0.1.1, real patch (corruption guard) |
| Profile kit 0.1.0 | `Idee-app-Archivi-riferimenti@1d1a8628e25f58b788b013cf6955763d00363cdc` | 0.1.0, real historical package |
| Consumer A | `Agenda-per-Anna@984a34462ba527b2ea98dbc3a337bdd8614b88d4` | existing pin 0.1.0 |
| Consumer B | `TasteAI@61a83aa638654f4e885d503e024408d2dcddebc2` | existing pin 0.1.0 |

The new independent [X10 SemVer CI workflow](../../.github/workflows/x10-profile-semver-rollback.yml) checks out the exact package commits, runs real Dart tests on both versions, then tests both original consumers at the preexisting 0.1.0 Git dependency. In **disposable** worktrees only, it changes their Git ref to the real 0.1.1 donor commit, uses Flutter pub to re-resolve the lockfiles, verifies exact `resolved-ref` and package version, runs consumer regression tests, and **downgrades dependency back to 0.1.0**, re-resolves and retests. The final step asserts both working-tree `pubspec.yaml` and `pubspec.lock` match the original versions.

The workflow uses pinned Flutter 3.47.5 and provides real run-scoped JSON manifest and donor/two-consumer/rollback receipts. The **unchanged** `golden_compat_harness_x10.py` checks the X10-018 structural contract. It never claims its own receipts are independently trusted: `STRUCTURAL_PASS_REVIEW_REQUIRED` must be inspected against the CI job logs and exact repository SHAs before the X10-026 queue can move.

## Non-goals / remaining gates

- This is a **real Dart package SemVer dependency rollback test**, but **not** a deployed or installed Android APK downgrade. No persisted real phone data, Play Console, OEM notifications or release certification.
- The consumers' `main` remain pinned to 0.1.0; temporary CI worktrees are not deployed consumer adoption of 0.1.1. An approved scoped consumer update PR and exact-head tests may be required before final full X10-026 adoption.
- The reference X10-017 `PROFILE_STANDARD_CANDIDATE.json` is a **different historical DESIGN_ONLY package** (`app_factory_profile_standard 0.0.0`). Do not rewrite its identity or call it version 0.1.1: the new workflow creates a separate runtime manifest for **real `factory_profile_kit`**.
- The receipt generator is a same-workflow reporter, not an independent test authority. X10-018's own output never promotes the Golden; an independent reviewer must inspect the real CI runner proof.
- X10-023, X10-024, X10-032, X10-035 and X10-015 are separate tracks with their own device/owner/Windows gates.

Until the exact PR-head workflow is green and reviewed, **no execution success is claimed**. After green, record exact run, source, artifacts and residual scope in the canonical 10x queue using normal repository PR checks.
