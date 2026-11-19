# REA CLI multi-platform — real proof & independent consumer

**Date:** 2026-11-19  
**Scope:** static research, exact artifact identities, `rea-agents@6.9.0` (MIT) via Node 24.  
**Latest admission:** Core [Index v31 CERTIFIED PROCESS (SCOPED)](https://github.com/riccardopinato/App-Factory-Core/pull/122), independent research consumers verified; **not CERTIFIED GOLDEN of any app/code or runtime**.

## Proven separate technology families

| Family | Provenance | Real execution result | Exact boundary |
|---|---|---|---|
| Windows NSIS + .NET | Official Deskland Preview v0.1.3, installer SHA-256 `e253cad56f1ea0ee2fb9d13ebe8a44f7dbe7232a506ba752cbe54c939c17bf44` | [AppLab real binary PASS #44615407360](https://github.com/riccardopinato/AppLab/actions/runs/44615407360): 43/43 published payload SHA match; extracted managed host observed | Historical user `Deskland-Setup.exe` not inspected, no Windows runtime |
| Flutter / Dart AOT | Official [Flutter Gallery v2.9.2](https://github.com/flutter-team-archive/gallery/releases/tag/v2.9.2) source `56dc27b62f1b93be9aa6ff93a730fc8952a35085`; APK SHA-256 `659b5fc6a4319dfe4f117d00ad4e7ec004915ebcadcb96628797fb3544040e29`, 117,817,550 bytes | [AppLab real Flutter PASS #44626932001](https://github.com/riccardopinato/AppLab/actions/runs/44626932001): `identify-flutter-build` and `inspect-dart-aot` both exit 0, three `libapp.so` ABIs; bounded AOT report 65,416 bytes | Public fixture, not the user's apps; Dart strings are not source reconstruction or complete SDK identification |
| Android/JADX independent consumer | Own `riccardopinato/Android-Omni-Cleaner` source `b594adc670bce482d0768638648196d92a3b8eaf` on PR #44; locally built debug APK SHA-256 `b2cb75cd332f1261ba5bfee69c47c994fd8acc0d64df88886be81c32fa14e977`, 19,324,653 bytes | [Independent real REA/JADX PASS #44626294217](https://github.com/riccardopinato/Android-Omni-Cleaner/actions/runs/44626294217): static `inspect-android-package` exit 0; compact receipt 28,517 bytes, private full evidence 60,054 bytes; hashes verified; Flutter identification negative (no `libapp.so`); deliberate wrong SHA refused | Does not run APK/clean files; no permission grant or physical/Play certification; full JADX output remains private |

## Third independent Flutter consumer

[Adaptive Landscape Android PR #42 merged](https://github.com/riccardopinato/Adaptive-Landscape-Android/pull/42); [actual own-repo REA CLI PASS run #44630662704](https://github.com/riccardopinato/Adaptive-Landscape-Android/actions/runs/44630662704). Source head `03fa33b7e6e563fd6021e0522bd40e82825945a1`, APK ARM64 17,805,211 bytes, SHA-256 `70cdf981ae8cae0832066b5d29657105baa0f275256c35fef3594724f95be33d`. All three static commands `identify-flutter-build`, `inspect-dart-aot`, `inspect-android-package` PASS; raw evidence hashes recorded separately in Core admission audit; no app source/permissions changed or physical wallpaper test implied.

## Evidence SHA and technical limitations

- REA source SHA: `morluto/rea@4491c84c82140a43fa12390b727840a433875ba8`, package `rea-agents@6.9.0`. Do not conflate source commit and npm artifact integrity: for production install freeze transitive lockfiles and review supply-chain digest.
- AppLab REA Desktop/Android/Flutter runner: `scripts/rea_cli_research.py`; managed PE and desktop tree use separate operation families. The original `scripts/rea_cli_bridge.py` remains PE-only.
- Flutter `identify-flutter-build` evidence SHA-256 `0278419f64a0e50e5c9fdaab5ee690eaeb141d3127494cfe4d01608acd2025a1`; direct AOT JSON SHA-256 `1f418dba9c5684e449f62469ef68c17cbd892c1acea3753e3533c518b552de77`.
- Omni `inspect-android-package` compact report SHA-256 `6423982f6146121acec9accc87cd521b786c8d4c65238019e8c94c3e0b282fa7`; private full bundle SHA-256 `1bdd889aa718c48b5c3a923c6cdb2076ab63c84fe564e8b30d42a8c5a58b7677`; native-Android Flutter-negative evidence SHA-256 `aca1b378b2e6d43f13bfcfea7055da0eb4d0939cac212b3b430e52fde7ddaf43`.
- Headless JADX requires Java 21 and the separate `jadx-headless-mcp-0.7.1-all.jar` with official SHA-256 `6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75`. The *first* Omni workflow run failed because the JAR prerequisite was absent; it was supplied and verified in the successful second run. Do not erase this failure from history.
- Flutter Gallery real AOT invocation initially failed using compact `--detail summary` for the AOT command; the successful rerun used its directly supported bounded JSON output. The Android/JADX command continues to retain a private full evidence file and return compact metadata.
- All raw third-party analysis reports remain `UNVALIDATED_EXTERNAL_OUTPUT` outside specifically reviewed hashes, operation codes, identity and selected metadata. A PASS is **an analyzer execution result**, not a statement that the software is safe, correct, lawful to clone or behaviorally identical on Android.

## Interpretation and next admission gate

**Second independent harness executed successfully:** yes — an app-owned, source-bound APK was built and inspected inside the Omni repo, not merely referenced by an AppLab source audit. **Cross-product Golden process certification:** now completed by separate [Core PR #122](https://github.com/riccardopinato/App-Factory-Core/pull/122) after source/CI and rights review, with scope limited to bounded static CLI research; broader E5/product admission remains separate. Do not automatically mark `CERTIFIED PROCESS`.

**Portable product functionality newly established from the binary:** none verified for Deskland; no additional Omni Cleaner feature or automatic cleanup behavior has been inferred from the APK. The value is **traceable artifact inspection and contrast**, not automatic donor extraction.
