# AppLab v0.7.9 — Storage & Data Integrity Lab

The trusted Android verifier now checks storage persistence and restart integrity without deleting or corrupting application data.

## Default behaviour

1. confirm the target application can launch;
2. record free space on the emulator `/data` partition;
3. when `run-as` is available, enumerate bounded private files from `files/`, `shared_prefs/`, `databases/`, and `no_backup/`;
4. record size and SHA-256 for readable files within configured limits;
5. force-stop and relaunch the application;
6. repeat the private-storage snapshot;
7. compare before/after file presence and hashes;
8. capture recovery screenshot and UI hierarchy;
9. scan package-specific ANRs and fatal exceptions.

The lab is non-destructive. It does not clear app data, mutate databases, corrupt files, or fill the device storage.

Projects can optionally define `.maestro/applab-storage.json`:

```json
{
  "schema_version": 1,
  "enabled": true,
  "required": true,
  "settle_seconds": 1.5,
  "max_files": 200,
  "max_file_bytes": 10485760,
  "minimum_free_mb": 128,
  "stable_path_regex": [
    "shared_prefs/.*",
    "databases/app\\.db"
  ],
  "required_path_regex": [
    "databases/.*"
  ],
  "expected_text_regex": [
    "Home",
    "Saved"
  ],
  "forbidden_text_regex": [
    "Welcome",
    "Reset"
  ]
}
```

`stable_path_regex` makes matching files strict: disappearance or a SHA-256 change across the restart fails the gate. `required_path_regex` verifies that expected persistent-storage artifacts exist.

If `run-as` is unavailable for a release APK, private-file inspection is advisory by default and becomes a failure only when `required` is true. Relaunch failures, ANRs, fatal exceptions, forbidden UI state, and strict stable-file violations are always failures.

## Evidence

- `storage-lab.json`
- `storage-lab.md`
- `storage-recovery.png`
- `storage-recovery.xml`

The aggregated `storage_lab` verdict is propagated into `result.json`, Repo Watcher history, and the Control Center.
