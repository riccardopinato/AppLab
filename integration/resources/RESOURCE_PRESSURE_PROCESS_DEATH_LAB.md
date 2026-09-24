# AppLab v0.7.7 — Resource Pressure & Process Death Lab

The trusted Android verifier now exercises memory-pressure callbacks and operating-system-style background process death before the Upgrade & Migration Lab.

## Default behaviour

1. record the target's initial process and memory snapshot;
2. send conservative Android trim-memory signals (`RUNNING_LOW`, then `BACKGROUND`);
3. verify the target does not crash or disappear unexpectedly during trim handling;
4. send the app to Home;
5. invoke `am kill <package>` while the app is backgrounded;
6. observe whether the process exits;
7. relaunch the app through its launcher intent;
8. capture recovery screenshot/UI hierarchy and a new memory snapshot;
9. scan package-specific ANR and fatal-exception evidence.

Projects can optionally define `.maestro/applab-resource.json`:

```json
{
  "schema_version": 1,
  "enabled": true,
  "required": true,
  "trim_levels": ["RUNNING_LOW", "BACKGROUND"],
  "process_death_cycles": 2,
  "settle_seconds": 1.5,
  "expected_text_regex": ["Home", "Saved"],
  "forbidden_text_regex": ["Fatal error", "Welcome"]
}
```

Supported trim levels are limited to Android's documented activity-manager levels. Target-controlled shell commands are not accepted.

If the hosted Android runtime cannot apply or observe a trim/process-kill operation, AppLab reports WARN by default. When `required` is true, those infrastructure limitations become failures. Target crashes, ANRs, unexpected process loss during trim handling, or failed recovery after process death always fail the gate.

## Evidence

- `resource-pressure-lab.json`
- `resource-pressure-lab.md`
- `resource-recovery-N.png`
- `resource-recovery-N.xml`

The aggregated `resource_pressure_lab` verdict is propagated into `result.json`, Repo Watcher history, and the Control Center.
