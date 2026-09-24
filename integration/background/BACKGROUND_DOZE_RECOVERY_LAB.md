# AppLab v0.7.8 — Background Execution, Doze & Recovery Lab

The trusted Android verifier now exercises background execution constraints before the Upgrade & Migration Lab.

## Default behaviour

1. confirm the target application can run;
2. send it to Home and observe background runtime health;
3. optionally place the package into App Standby;
4. optionally force Android into Doze;
5. inspect package services, JobScheduler/WorkManager evidence, notifications and device-idle state;
6. leave Doze and App Standby;
7. relaunch/recover the application;
8. capture screenshot and UI hierarchy;
9. scan package-specific ANRs and fatal exceptions.

Projects can define `.maestro/applab-background.json`:

```json
{
  "schema_version": 1,
  "enabled": true,
  "required": true,
  "background_cycles": 2,
  "settle_seconds": 1.5,
  "force_doze": true,
  "app_standby": true,
  "require_notification": true,
  "expected_service_regex": ["ForegroundService"],
  "expected_job_regex": ["WorkManager"],
  "expected_text_regex": ["Home", "Saved"],
  "forbidden_text_regex": ["Fatal error"]
}
```

The policy is validated inside the trusted build contract. It cannot inject shell commands.

Hosted-emulator inability to apply or observe Doze/App Standby is advisory by default. When `required` is true, those limitations become failures. Target ANRs, fatal exceptions, and failed foreground recovery are always hard failures.

## Evidence

- `background-lab.json`
- `background-lab.md`
- `background-recovery-N.png`
- `background-recovery-N.xml`

The aggregated `background_lab` verdict is propagated into `result.json`, Repo Watcher history, and the Control Center.
