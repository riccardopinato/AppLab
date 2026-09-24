# AppLab v0.7.5 — Upgrade & Migration Lab

The trusted Android verifier can now test an in-place application upgrade from the latest known-good APK to the current candidate.

## How it works

1. AppLab restores the most recent PASS-only APK baseline for the project.
2. The normal verification suite runs against the original current APK.
3. The Upgrade Lab creates temporary copies of the previous and current APKs.
4. Both copies are signed with the same run-local AppLab test key so CI debug-key rotation cannot invalidate the migration test.
5. The previous PASS APK is installed and launched.
6. The current APK is installed with `adb install -r`, preserving the application's data directory.
7. AppLab launches the upgraded application, captures UI evidence, and checks process health, ANRs, and fatal exceptions.
8. Only after a successful trusted verification is the current original APK stored as the next PASS-only upgrade baseline.

The temporary re-signing is used only for the migration exercise. It does not alter the original APK bytes used by the normal trusted gates or by the verified release artifact.

## Optional project policy

Projects may add `.maestro/applab-upgrade.json`:

```json
{
  "schema_version": 1,
  "enabled": true,
  "required": true,
  "settle_seconds": 2,
  "expected_text_regex": ["Saved", "Home"],
  "forbidden_text_regex": ["Fatal error", "Welcome"]
}
```

`expected_text_regex` can assert state that should remain visible after an in-place upgrade. `forbidden_text_regex` can reject reset/error states.

If no previous PASS APK exists, the gate reports `NO_BASELINE` rather than failing the project. The first successful run seeds the baseline automatically.

## Evidence

- `upgrade-lab.json`
- `upgrade-lab.md`
- `upgrade-before.png`
- `upgrade-before.xml`
- `upgrade-after.png`
- `upgrade-after.xml`

The aggregated `upgrade_lab` verdict is propagated into `result.json`, Repo Watcher history, and the Control Center.
