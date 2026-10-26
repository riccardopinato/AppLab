# v5.6A Runtime Stability & Failure Diagnostics

Status: IMPLEMENTED

- Unknown/unclassified failures are fail-closed and are not auto-retried.
- Repo Watcher retries only explicit INFRA_ERROR / FLAKY_SUSPECT evidence with retryable=true.
- The existing bounded WebRTC peer recovery remains unchanged: diagnostics are captured before recovery and strict frame/input assertions remain authoritative.
- Continuous Maintenance now derives recurrence signatures plus wall/runtime/quality p50/p95 from existing watcher history without launching an emulator.
- Failed attempts remain evidence; a retry never rewrites the original failure.
- Runtime/emulator evidence remains distinct from physical-device and distribution/store evidence.

Artifacts:
- scripts/runtime_stability_v56a.py
- tests/contracts/runtime_stability_v56a_test.py
- .github/workflows/continuous-maintenance.yml

No FAST/FULL or certification authority changed.
