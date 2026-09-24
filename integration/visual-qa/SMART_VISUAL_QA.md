# AppLab v0.6 — Smart Visual QA

Smart Visual QA runs inside the standard AppLab Android gate after launch and
after Maestro when a flow is enabled.

It analyzes both the final Android screenshot and the corresponding
uiautomator hierarchy.

## High-confidence FAIL conditions

- nearly uniform black/white/blank rendered screen;
- extremely sparse UI combined with a low-detail screenshot;
- target application not present in the foreground UI hierarchy;
- crash/ANR dialog visible over the app;
- enabled interactive controls with zero-size or fully off-screen bounds.

These conditions fail the AppLab gate.

## Warning-only conditions

- partially off-screen enabled controls;
- touch targets smaller than 32 px on at least one axis;
- likely permission/system dialog blocking the application.

Warnings are reported but do not fail the project.

## Evidence

Every verification report now includes:

- `visual-qa.json`
- `visual-qa.md`
- screenshot statistics
- UI node statistics
- structured findings
- `visual_qa` in the main `result.json`

The central Repo Watcher history also exposes the Smart Visual QA result.

## Design principle

v0.6 is conservative by default. It only blocks a commit when the visual
problem is strong enough to be detected deterministically. Ambiguous layout
issues remain warnings so that AppLab does not turn normal design differences
into false CI failures.
