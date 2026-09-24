# AppLab v0.6.2 — Multi-Screen Visual Journey

AppLab can now validate multiple application screens in one Android runtime
session.

Every run captures at least two checkpoints automatically:

1. `launch` — the first settled application screen;
2. `final` — the screen after the standard Maestro smoke flow, or the current
   screen when Maestro is disabled.

Each checkpoint receives:

- Android screenshot;
- uiautomator hierarchy;
- Smart Visual QA;
- comparison with the same checkpoint from the last passing baseline.

## Optional custom journey

A repository can add:

`.maestro/applab-journey.json`

Example:

```json
{
  "checkpoints": [
    {
      "name": "settings",
      "flow": ".maestro/journey/settings.yaml"
    },
    {
      "name": "confirm-dialog",
      "flow": ".maestro/journey/confirm-dialog.yaml"
    }
  ]
}
```

Checkpoint flows are normal standalone Maestro YAML files. They are executed
sequentially in the same emulator session. AppLab captures the screen only
after each flow succeeds, so the screenshot and UI hierarchy always represent
the actual named checkpoint.

Names `launch` and `final` are reserved.

## Baselines

v0.6.2 uses visual-baseline cache generation `v2`.

The baseline layout contains one directory per checkpoint:

```text
.applab-visual-baseline/
  metadata.json
  screenshot.png
  window.xml
  journey/
    launch/
      screenshot.png
      window.xml
      metadata.json
    final/
      screenshot.png
      window.xml
      metadata.json
    settings/
      screenshot.png
      window.xml
      metadata.json
```

Only a successful AppLab run may replace the baseline.

## Verdict

The journey report aggregates all checkpoints:

- any high-confidence visual/runtime failure -> `FAIL`;
- warning on one or more checkpoints -> `WARN`;
- all checked screens stable -> `PASS`;
- first run with no previous journey baseline can still pass and create it.

Evidence:

- `visual-journey.json`
- `visual-journey.md`
- `visual-journey/current/<checkpoint>/screenshot.png`
- `visual-journey/current/<checkpoint>/window.xml`

The main `result.json` contains `visual_journey` and the watcher history
shows the Journey verdict.
