# AppLab v0.6.7 — Permissions, Notifications & System UI Lab

AppLab v0.6.7 adds a trusted Android system-behaviour layer after runtime,
interaction, and visual verification.

## Default checks

Without project configuration AppLab records and validates:

- requested Android permissions and app-ops state;
- notification-manager evidence for the package;
- running service and foreground-service state;
- device-idle whitelist state;
- background -> foreground recovery;
- force-stop -> launcher restart;
- final process, ANR, and fatal-exception health.

The default checks are conservative. Missing notifications, foreground services,
or battery-whitelist membership are observations, not failures.

## Optional project policy

Projects can add:

`.maestro/applab-system.json`

Example:

```json
{
  "schema_version": 1,
  "permissions": {
    "grant": [
      "android.permission.POST_NOTIFICATIONS"
    ],
    "revoke": []
  },
  "deep_links": [
    {
      "uri": "myapp://settings",
      "required": true
    }
  ],
  "biometric": {
    "enabled": false,
    "finger_id": 1,
    "required": false
  },
  "require_notification": false
}
```

The configuration is copied into the isolated build artifact and validated by
the trusted verifier before Android starts.

Configured permission operations are restricted to
`android.permission.*`. Deep links are launched explicitly against the target
package. Required configured checks fail the gate; optional unsupported checks
produce warnings.

## Evidence

Each run adds:

- `system-lab.json`
- `system-lab.md`
- `system_lab` in the main `result.json`
- system verdict in central watcher history

## Security boundary

System UI Lab runs only inside the trusted verification job introduced in
v0.6.4. The target repository is not checked out in that job; only the validated
APK and declarative `.maestro` evidence are available.
