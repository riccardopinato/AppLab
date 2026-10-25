# AppLab v5.4 — Post-Implementation Architecture Evaluations

Status: **EVALUATION COMPLETE / NO ADDITIONAL PRODUCTION AUTHORITY ENABLED**

Baseline evaluated: AppLab@cccf82e8bbbd56686f6a0bc77b3b13311a593159.

The v5.4 A→G sequence is complete. These evaluations close the four remaining roadmap items without silently adding new trusted authorities or external runtime dependencies.

## 1. scrcpy — Physical Evidence Hub extension

Reference: Genymobile/scrcpy@a60891aea193d92e7e5c3942700eca63f9d19a5f

The evaluated revision provides Android device mirroring/control over USB or TCP/IP, recording, no-root operation and no persistent app requirement on the device.

**Decision: FUTURE_PILOT — YES**

Role: PHYSICAL_EVIDENCE_HUB_EXTENSION. Authority: EVIDENCE_CAPTURE_ONLY.

Best fit:
- physical-device screen recording;
- operator-assisted reproduction;
- evidence capture during real-device validation;
- optional explicit input/control sessions;
- low-friction observation without modifying the target APK.

It must not become verification or certification authority.

A future evidence record must bind repository, exact source SHA, exact APK SHA-256, package/version, physical device identity, Android/API level, pinned scrcpy identity, session timestamps, control mode, operator/automation identity and recording SHA-256.

Default collection should be recording-first. Interactive control is explicit because it can mutate app/device state. Recording alone does not prove the correctness of an un-attested action sequence.

Promotion requires exact artifact/device/session identity, retention policy, control provenance, deterministic hashes and fail-closed handling of missing identity.

## 2. LeakCanary — memory diagnostic lane

Reference: square/leakcanary@eb60b0be53732aa016c79b7774b497770ad1e4f3

LeakCanary is an Android memory-leak detection library.

**Decision: FUTURE_PILOT — YES, DIAGNOSTIC ARTIFACT ONLY**

Role: DEBUG_INSTRUMENTED_MEMORY_DIAGNOSTIC. Authority: DIAGNOSTIC_ONLY.

Correct model:
- exact immutable source SHA produces the normal release APK for existing trusted AppLab verification/certification;
- the same source SHA may separately produce an instrumented debug APK for LeakCanary diagnostics;
- the two artifacts retain independent SHA-256 identity.

LeakCanary evidence may report suspected leaks, retained-object diagnostics and memory-diagnostic outcomes. It may not produce release PASS, artifact equivalence, physical-device equivalence or CERTIFIED.

A pilot requires explicit debug-artifact identity, source-SHA binding, a diagnostic evidence schema, no release-artifact substitution and clear separation from the current performance-lab authority.

## 3. Dedicated security scanners

Evaluated references:
- semgrep/semgrep@087e93b3a1fdf44f97bc92b5b9c2ba221cb2488b
- aquasecurity/trivy@3a0164d6cd627645220730d48d51dc71e10e7156
- MobSF/Mobile-Security-Framework-MobSF@c47c1957e54a98477eed5e527d2671bef790fad6

### Semgrep

The evaluated revision is a static-analysis engine supporting 30+ languages including Dart, Java, Kotlin, Python, JavaScript/TypeScript and YAML, and can run locally or in CI. Its own documentation notes that Community Edition has weaker security coverage than cross-file/cross-function commercial capabilities.

**Decision: FIRST-WAVE PILOT**

Initial AppLab role:
- source-code security patterns;
- project-specific unsafe API rules;
- CI/workflow guardrails;
- language-aware correctness/security evidence.

Findings remain SECURITY_EVIDENCE, not AppLab PASS/CERTIFIED authority.

### Trivy

The evaluated revision scans repositories/filesystems/images and can produce vulnerability, dependency/SBOM, misconfiguration, secret and license findings.

**Decision: FIRST-WAVE PILOT**

Initial AppLab role:
- dependency vulnerability evidence;
- repository/filesystem scanning;
- secret detection;
- Docker/IaC/configuration scanning;
- SBOM generation/validation.

Trivy complements existing pip/npm audits rather than replacing them immediately.

### MobSF

The evaluated revision provides mobile-specific static and dynamic analysis for Android/iOS, including APK/source analysis and CI/CD integration.

**Decision: SECOND-WAVE MOBILE PILOT**

MobSF is a strong fit for deeper Android binary/mobile-security evidence but is operationally heavier than Semgrep/Trivy.

Preferred sequence:
1. Semgrep + Trivy.
2. Calibrate noise, runtime and normalized evidence.
3. MobSF isolated APK/static pilot.
4. Evaluate MobSF dynamic analysis separately.

MobSF dynamic analysis must remain isolated from normal trusted-runtime verification and cannot reinterpret release certification authority.

### Security authority boundary

All scanners are subordinate evidence producers. Their findings may feed a registered Security Evidence Lane, Release Assurance and human/policy consumers, but they do not directly mint FAST/FULL PASS, release PASS or CERTIFIED.

## 4. Autonomous diagnosis / fix / PR proposals

v5.4 A→G now provides the prerequisites previously missing: durable event identity, persistent operations, deterministic transitions, per-repository queueing, bounded retries, live event-driven canary, watcher recovery and trusted executor boundaries.

**Decision: ELIGIBLE FOR A SEPARATE PROPOSAL-ONLY PILOT**

This is not authorization for autonomous merge or release.

Allowed future scope:
- diagnose from trusted evidence;
- create bounded remediation proposals;
- create isolated branches;
- run tests/AppLab verification;
- open pull requests.

Forbidden without a separate governance decision:
- direct push to main;
- automatic PR merge;
- release creation;
- store publication;
- secret/credential mutation;
- certification-authority changes;
- Product Bible or product-scope changes;
- hidden coverage reduction.

A future proposal record should bind source repository, failing source SHA, AppLab SHA, supporting evidence IDs, failure classification, proposed file set, patch digest, test plan, resulting branch/commit SHA, verification results and residual uncertainty.

Initial automatic-fix candidates should be narrow deterministic build/config issues, mechanically justified lint/static defects, bounded dependency remediation and deterministic CI/test-fixture defects.

Authentication/authorization, payments, privacy/permissions, cryptography, data deletion/migration, signing/release, broad architecture changes and ambiguous product/UX changes remain human-gated.

Safe future flow:
AUTONOMOUS_DIAGNOSE → AUTONOMOUS_PROPOSE → AUTONOMOUS_BRANCH → AUTONOMOUS_PR → existing AppLab/CI gates → HUMAN OR SEPARATE GOVERNANCE MERGE DECISION.

## Final decisions

| Topic | Decision | Earliest role | Production activated now? |
|---|---|---|---:|
| scrcpy | FUTURE_PILOT | Physical Evidence capture | No |
| LeakCanary | FUTURE_PILOT | Debug memory diagnostics | No |
| Semgrep | FIRST_WAVE_PILOT | Source security evidence | No |
| Trivy | FIRST_WAVE_PILOT | Dependency/config/secret evidence | No |
| MobSF | SECOND_WAVE_PILOT | Mobile APK/security evidence | No |
| Autonomous diagnose/fix/PR | PROPOSAL_ONLY_PILOT_ELIGIBLE | Diagnosis + branch + PR proposal | No |

## v5.4 closure

The v5.4 roadmap is architecturally complete:
- A→G implementation sequence complete;
- post-implementation tool evaluations complete;
- no new certification authority introduced;
- no autonomous merge/release enabled;
- future work moves to separately authorized pilots/versions rather than being hidden inside v5.4.
