# AppLab v0.7.4 — Persistence & Restart Lab

The trusted Android verifier now exercises application lifecycle persistence after the existing system, performance, and network gates.

Default behaviour:

1. confirm the target process is running;
2. force-stop the application;
3. relaunch it through the launcher intent;
4. wait for the UI to settle;
5. capture screenshot and UI hierarchy;
6. repeat the restart cycle;
7. scan for package-specific ANRs and fatal exceptions.

Projects can opt into explicit state assertions with `.maestro/applab-persistence.json`:

```json
{
  "schema_version": 1,
  "enabled": true,
  "required": true,
  "restart_cycles": 2,
  "settle_seconds": 1.5,
  "expected_text_regex": ["Saved", "My note"],
  "forbidden_text_regex": ["Welcome back", "Fatal error"]
}
```

`expected_text_regex` is evaluated after every restart and is useful for state that must remain visible after process recreation. `forbidden_text_regex` fails when reset/error UI becomes visible.

Without a project policy AppLab still validates restartability, process health, screenshot/UI capture, and crash/ANR behaviour. Missing generic UI evidence is advisory by default; failed relaunches and target crashes are always failures.

Evidence:

- `persistence-lab.json`
- `persistence-lab.md`
- `persistence-cycle-N.png`
- `persistence-cycle-N.xml`

The main `result.json`, Repo Watcher history, and Control Center surface the aggregated `persistence_lab` verdict.
