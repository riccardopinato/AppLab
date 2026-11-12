# X10-026 — AppLab two Flutter consumer source and rollback rehearsal

Factory baseline: `App-Factory-Core@c5adc147046beb7024629466d10eeb799c3c2619`, Master v27, Index v29. The package is **factory_profile_kit 0.1.0**, a Dart read-only profile model. This workflow does not register or promote any Golden.

| Role | Repo | Immutable SHA |
|---|---|---|
| Profile donor | riccardopinato/Idee-app-Archivi-riferimenti | `1d1a8628e25f58b788b013cf6955763d00363cdc` |
| Consumer A | riccardopinato/Agenda-per-Anna | `984a34462ba527b2ea98dbc3a337bdd8614b88d4` |
| Consumer B | riccardopinato/TasteAI | `61a83aa638654f4e885d503e024408d2dcddebc2` |
| Anna before kit | riccardopinato/Agenda-per-Anna | `8fbfe14f7a21d41af274cf259c462df2eab9dc69` |
| Taste before kit | riccardopinato/TasteAI | `8e880be68d74686c6c6b7e6a992a5fdc6fa6c384` |

## Real independent verification

[`x10-two-flutter-consumers.yml`](../../.github/workflows/x10-two-flutter-consumers.yml) runs in AppLab CI with read-only GitHub permissions. It clones the immutable donor and real consumer commits, checks both `pubspec.yaml` and `pubspec.lock` for exactly the same donor SHA/version, and executes donor Dart analysis/tests and consumer Flutter tests with real `AgendaStore` and `AppSettingsController`. It then checks out the pre-adoption source of each consumer into separate worktrees and runs pre-existing preferences/restore tests. Flutter is pinned to 3.47.5 after the [TasteAI #7](https://github.com/riccardopinato/TasteAI/pull/7) toolchain fix.

This is a **source rollback rehearsal**, not a tested installed APK downgrade with actual retained user data. The [existing X10-018 Golden harness](X10-018_GOLDEN_COMPAT_HARNESS.md) additionally requires a real package-version rollback receipt to a lower semver, which this task does **not** fabricate; `factory_profile_kit 0.0.0` does not exist. SOURCE+CI success is distinct from `DEVICE_VERIFIED`, release, store approval or Golden admission.

Before changing X10-026 from PLANNED, review the exact-head CI run and decide explicitly whether the phase acceptance can rely on source rollback only or whether the stricter X10-018 semver rollback gate also applies. No producer or consumer repo writes, new OAuth/permissions, analytics, SDK monetization, user data migration or external expenditure are authorized by this workflow.
