# REA Software Intelligence — 5 maxi-step implementation

**2026-11-19 · App Factory Golden Index v30 · COPY-READY PROCESS · AppLab research-only**

Canonical Golden: [REA CLI Reverse Intelligence](https://github.com/riccardopinato/App-Factory-Core/blob/main/golden/governance/GOLDEN_REA_CLI_REVERSE_INTELLIGENCE_v1.txt). Pinned source: `morluto/rea@4491c84c82140a43fa12390b727840a433875ba8`; npm `rea-agents@6.9.0`, MIT. Application source is never overwritten.

## Step 1 — Desktop / managed research

`scripts/rea_cli_research.py --mode desktop` accepts an **already extracted** Windows desktop application directory and invokes `inspect-desktop-application`. It hashes every regular file, rejects symlinks and caps total size/count. `--mode managed` accepts a PE/CLI candidate and invokes `inspect-managed-artifact` plus optionally `inspect-managed-members`. A separate `scripts/rea_desktop_manifest_verify.py` verifies files in a previously extracted directory against a publisher manifest SHA list. It **does not unpack or run any installer**; archives must be extracted independently in an isolated, authorized environment. The historic user's `Deskland-Setup.exe` was not accessible; proof remains the distinct official public Deskland Preview v0.1.3 ([report](REA_DESKLAND_PREVIEW_BINARY_REPORT_2026-11-19.md)).

## Step 2 — Android APK research

`--mode android` admits a local **single APK** with a parseable ZIP central directory, `AndroidManifest.xml`, regular input, no path traversal, explicit SHA-256 and bounded output; invokes `rea inspect-android-package` (JADX headless). The **REA npm distribution and Java prerequisites** are distinct from AppLab's Python adapter and must be available. Decoded declarations are **static observations**, not proof a service actually ran, a permission was granted, data was accessed, or cleanup succeeded.

## Step 3 — Flutter build research

`--mode flutter` invokes `identify-flutter-build` and `inspect-dart-aot` on an APK. Missing `lib/<ABI>/libapp.so` yields an explicit `NOT_APPLICABLE_NO_LIBAPP_SO` for AOT rather than a misleading FAIL. Each ABI's AOT layout has its own limitations; static snapshot strings are not source reconstruction, and SDK hash-to-release resolution requires external dataset verification. To run *only* the low-cost build identification, specify `--operation identify-flutter-build`.

## Step 4 — Donor pipeline with explicit decisions

`scripts/rea_donor_review.py` consumes a receipt from the runner, rehashes saved evidence files, validates source comparisons `NEW_BEYOND_SOURCE | ALREADY_IN_SOURCE | CONFLICT | NOT_VERIFIED` and decisions `ADOPT_CANDIDATE | REFERENCE_ONLY | DEFER | REJECT`. `ADOPT_CANDIDATE` requires genuinely new observation and research authorization. The output is a **manual-review candidate**, not a change to the canonical `Idee-app-Archivi-riferimenti` catalog: separate branch/PR/CI is required; no E3, E5, Golden or runtime truth is inferred.

## Step 5 — Independent second adoption

A dedicated, independently operated target-repository workflow is required to establish a second genuine usage; proposed first target **Android Omni Cleaner** with its own locally built, source-bound APK and `inspect-android-package`, plus Flutter negative control. Outcome must include a real run URL, source SHA, APK SHA-256, Java/REA versions, refusal/negative tests and limitations. A green smoke on an inert ZIP does not count as a second runtime adoption. Core Golden remains **COPY-READY** unless and until an independent verified consumer supports a separately reviewed promotion.

## Controlled local example

Install REA **outside any app repo** with supported Node 24 and separately provide Java as needed:

```sh
npm install --prefix /abs/rea-tools --no-save --omit=optional --no-audit --no-fund rea-agents@6.9.0
python scripts/rea_cli_research.py --mode android \
  --rea-bin /abs/rea-tools/node_modules/.bin/rea \
  --artifact /abs/app-debug.apk \
  --output-dir /abs/private-evidence \
  --repository OWNER/APP --source-sha FULL_40_HEX_SHA \
  --expected-sha256 FULL_64_HEX_APK_SHA256
```

For Windows, use absolute `node.exe` as `--rea-bin` and absolute `rea-agents/scripts/rea.mjs` as `--rea-entry`. The adapter launches subprocesses without shell and does not run target APK/EXE. Public CI must never receive private user binaries, credentials, decoded proprietary code or private metadata. Raw REA output is **UNVALIDATED_EXTERNAL_OUTPUT** until review; private directory storage is required.

## Evidence model and acceptance

Per artifact retain: repo/source SHA, artifact basename/size/SHA, operation/engine version, immutable evidence file SHA, failure/truncation status, exact-run URL and documented source-only baseline. Re-run source and CI tests after any modification. The restricted original PE adapter `rea_cli_bridge.py` remains available; these new modes are separate and **do not claim the old PE-only adapter supports APK or directories**.

Known limits: no app UI/camera/permissions/cleanup hardware acceptance; no signed Play release; no automatic NSIS extraction; no automatic Flutter AOT reconstruction; no guaranteed successful JADX analysis without Java/runtime; no automatic third-party code/license clearance.
