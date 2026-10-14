# Crawler Runtime Evidence Windows

AppLab baseline: v5.3.5 operational hardening.

## Problem

Runtime crawlers historically inspected the current Android logcat buffer for
target ANR/fatal evidence. The buffer is process-global to the emulator and can
contain target events produced by a previous lab, launch, or action.

That makes temporal attribution ambiguous even when package attribution is
correct.

## Contract

Safe Interaction Crawler and Safe Journey Crawler now use explicit evidence
windows:

1. reset logcat immediately before each controlled relaunch;
2. wait boundedly for the target process;
3. check launch health;
4. capture the pre-action UI state;
5. reset logcat immediately before the safe tap;
6. execute the tap;
7. evaluate ANR/fatal/process evidence from that action window.

## Failure semantics

- stale event before the window: not attributed to the current launch/action;
- target ANR/fatal inside the window: FAIL;
- target process death inside the window: FAIL;
- observation/capture instrumentation failure without target runtime failure:
  WARN/SKIPPED according to the existing crawler contract.

There is no automatic target-failure retry-to-PASS path.

## Regression evidence

`tests/contracts/crawler_runtime_window_test.py` covers:

- a stale target ANR present before the crawler starts;
- successful isolation after the runtime window reset;
- a fresh target ANR injected by the tested action;
- fail-closed detection of that fresh ANR.

This hardening changes attribution, not certification authority.
