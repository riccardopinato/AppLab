# AppLab v0.7.6 — Configuration & Lifecycle Stress Lab

The trusted Android verifier now stress-tests configuration changes and repeated foreground/background transitions before the Upgrade & Migration Lab.

## Default behaviour

1. preserve the emulator's original rotation settings;
2. disable automatic rotation temporarily;
3. cycle landscape and portrait orientation twice;
4. capture screenshot and UI hierarchy after every orientation change;
5. send the app to Home and return it to the foreground twice;
6. verify the target process remains healthy after every stage;
7. scan for package-specific ANRs and fatal exceptions;
8. restore the emulator's original rotation settings even when a test fails.

Projects can optionally define `.maestro/applab-configuration.json`:

```json
{
  "schema_version": 1,
  "enabled": true,
  "required": true,
  "rotation_cycles": 2,
  "background_cycles": 3,
  "settle_seconds": 1,
  "expected_text_regex": ["Home", "Saved"],
  "forbidden_text_regex": ["Fatal error", "Welcome"]
}
```

When `required` is false, a device/app that does not expose landscape geometry is reported as WARN rather than FAIL. Target process death, ANR, fatal exception, or inability to return the application to the foreground always fails the gate.

## Evidence

- `configuration-lab.json`
- `configuration-lab.md`
- `config-landscape-N.png/xml`
- `config-portrait-N.png/xml`
- `config-foreground-N.png/xml`

The aggregated `configuration_lab` verdict is propagated into `result.json`, Repo Watcher history, and the Control Center.
