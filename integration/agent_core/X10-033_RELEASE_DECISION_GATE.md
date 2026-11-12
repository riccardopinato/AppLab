# X10-033 — CI → QA → release decision brief (source-level)

Pinned Factory: Core@c5adc147046beb7024629466d10eeb799c3c2619 / Master v27 / Golden Index 29.

This is a **thin, side-effect-free aggregator** of existing independent AppLab authorities, NOT a new certification or signing engine. `scripts/x10_release_decision_gate.py` consumes existing **release_assurance.py** (canonical release authority), **release_reality.py** via the assurance identity, **qa_test_router_x10.py** delegated certification report, **x10_visual_baseline_gate.py**, **x10_performance_a11y_gate.py**, **x10_signed_release_provenance.py**, and the seven required CI workflow checks. An **external host-owned trust resolver** must verify each of the six evidence sources to the exact repository/source SHA/APK bytes/workflow run. This module does not obtain or independently verify GitHub check status, artifact upload, physical device or Store release by itself.

Critical rules:
- Missing/non-certification QA, stale source/artifact SHA, incomplete CI check set, WARN/FAIL visual/performance/QA, missing original signed APK, incomplete canonical release-assurance stages or untrusted evidence => blocked.
- Valid-looking records do not mint PASS: even with everything reported PASS, the state is **INPUTS_REPORTED_READY_FOR_HUMAN_REVIEW**, never certified or Store-authorized.
- Real physical-device evidence is evaluated by canonical Release Reality / Release Assurance; emulators, synthetic fixtures, signed candidate reports and self-declared tool outputs do not stand in for real device or Play Console.
- This adapter **never publishes, signs, approves, merges or changes release configuration**. Product owner has independent release approval; scope X10-032 remains human.

Acceptance: Python unit tests only synthetic + normal AppLab exact-head workflows + Codex review. No user app runtime or Store claim; no automatic pipeline admission. The host must wire the trusted verifier in a separately gated integration before any real release decision can rely on this report.