# AppLab v0.7.3 — Network & Offline Lab

The trusted Android verifier now exercises connectivity loss and recovery after
the existing visual, interaction and Android-system gates.

Default behaviour is deliberately conservative:

1. record the emulator's initial connectivity state;
2. switch Android into airplane/offline mode;
3. verify that the target process remains healthy;
4. optionally force-stop and relaunch the app while offline;
5. restore the original airplane-mode state;
6. verify network recovery and app relaunch;
7. scan package-specific ANR/fatal-exception evidence.

Infrastructure limitations are advisory by default. If the hosted AVD cannot
toggle or confirm connectivity, the network gate reports WARN rather than
failing an otherwise healthy app. A target-process crash, ANR or failed
offline/recovery relaunch is always a FAIL.

Projects can opt into strict infrastructure assertions with
`.maestro/applab-network.json`:

```json
{
  "schema_version": 1,
  "enabled": true,
  "required": true,
  "offline_seconds": 2,
  "recovery_timeout_seconds": 20,
  "relaunch_while_offline": true
}
```

All values are validated inside the trusted build contract before the emulator
job runs. Arbitrary URLs, shell commands and target-controlled network probes
are intentionally unsupported.

Evidence:

- `network-lab.json`
- `network-lab.md`
- `network-offline.png`
- `network-recovered.png`

The main `result.json`, Repo Watcher history and Control Center surface the
aggregated `network_lab` verdict.
