# AppLab v0.9 — FAST Analysis Engine

FAST is now implemented by the Adaptive Impact Analysis & Incremental
Verification Engine. The authoritative specification is
[`ADAPTIVE_IMPACT_ENGINE.md`](ADAPTIVE_IMPACT_ENGINE.md).

## Compatibility contract

AppLab still accepts the public analysis modes:

- `fast`
- `full`
- `certification`

Internally, FAST resolves to one of:

- `NO_RUNTIME_CHANGE`
- `STATIC_ONLY`
- `FAST_RUNTIME`
- `FULL_RUNTIME` (automatic safe escalation)

FULL resolves to `FULL_RUNTIME`; certification resolves to `CERTIFICATION`.

## Baseline safety

FAST compares the last trusted PASS for the exact repository/history-key/ref
against the current SHA. The baseline must exist and be an ancestor of HEAD.
Shallow runners progressively deepen history to prove ancestry. Missing or
unprovable ranges become FULL_RUNTIME.

## Runtime safety

FAST_RUNTIME always preserves the core runtime sentinels. Only specialist labs
are selectively skipped. Every skip remains `SKIPPED`, never PASS.

FAST cannot publish a production release artifact. CERTIFICATION remains the
only release-authoritative mode.

## Calibration

Periodic deterministic shadow FULL runs retain the FAST prediction while
executing all labs. Divergence and false-negative evidence is stored alongside
normal pipeline metrics and is the basis for future threshold tuning.
