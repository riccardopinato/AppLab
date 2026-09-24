# AppLab v0.6.1 — Visual Regression Baseline

AppLab keeps the last passing runtime screen for each project and compares the
next verified screen against it.

## Baseline lifecycle

1. The runner restores the most recent passing baseline from GitHub Actions cache.
2. The APK is built, installed and launched normally.
3. Maestro runs when enabled.
4. Smart Visual QA checks the final current screen.
5. Visual Regression compares that screen and UI hierarchy with the restored baseline.
6. If the whole gate passes, the current screen becomes the new baseline.
7. If build/runtime/visual checks fail, the previous baseline is preserved.

No service commits are created.

## Comparison signals

The screenshot is normalized to a fixed grid so different emulator resolutions
remain comparable. Most status/navigation-bar pixels are ignored.

AppLab calculates:

- mean absolute RGB difference;
- RMS RGB difference;
- changed-cell ratios;
- visible text Jaccard similarity;
- target-package node-count delta;
- interactive-control count delta.

A large image change plus a large structural UI change is a high-confidence
regression and fails the gate. Moderate differences are warnings.

## First run

When a project has no previous baseline:

`visual_regression = NO_BASELINE`

The run can still pass. Its final screen is then saved as the first baseline.

## Evidence

Each comparison adds:

- `visual-regression.json`
- `visual-regression.md`
- baseline source SHA and workflow run
- image-difference metrics
- UI-structure difference metrics
- `visual_regression` in the main `result.json`

The central watcher summary also exposes the regression verdict.
