# AppLab v6.0H — Sensor Mesh

Status: **IMPLEMENTED CANDIDATE / REAL PRODUCER AVAILABILITY IS ENVIRONMENT-BOUND**

v6.0H extends the existing v5.6E producer registry rather than creating a competing security/physical evidence model. Hetty is added as `SECOND_WAVE_NETWORK / NETWORK_REPLAY`.

The mesh selects sensors from risk, changed paths, failed specialist labs, artifact availability and explicit physical/network-replay intent.

First-wave/available producers: scrcpy capture, LeakCanary evidence, Semgrep and Trivy. Second-wave producers: MobSF and Hetty.

Hosted CLI execution is supported for Semgrep/Trivy when the binaries are actually available. Missing binaries return `BLOCKED / SENSOR_BINARY_NOT_AVAILABLE`; they never become PASS. Physical scrcpy, LeakCanary, MobSF and Hetty evidence enter through their real environment-specific producers and are normalized by the same registry.

Every normalized record remains `EVIDENCE_ONLY`, with `can_mint_pass=false`, `can_mint_certified=false`, no trusted-runtime replacement and no store-distribution claim.

## Acceptance

- [x] reuse existing v5.6E producer registry;
- [x] register Hetty without duplicate authority;
- [x] risk-triggered producer planning;
- [x] Semgrep/Trivy real CLI adapters with BLOCKED semantics when absent;
- [x] physical/artifact identity preserved through existing normalizer;
- [x] network replay requires explicit opt-in;
- [x] evidence-only authority maintained;
- [x] CI/self-test wiring;
- [ ] real environment evidence accrual for each optional producer.
