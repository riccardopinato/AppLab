# REA CLI — Deskland public Preview v0.1.3 real binary inspection

**Date:** 2026-11-19
**Status:** PUBLIC_RELEASE_BINARY_OBSERVED / E1 RESEARCH ONLY
**Not the historical user upload:** `Deskland-Setup.exe` from another chat was unavailable. Its SHA, packaging, version, content and runtime remain **NOT_VERIFIED**.

## Reproducible evidence

- Source: `BLEZZ0102/Deskland@9818b577402ff476e1b59da07970c56472713126` (GPL-3.0).
- Public release: https://github.com/BLEZZ0102/Deskland/releases/tag/v0.1.3, published 2026-11-07.
- Selected file: `Deskland-Preview-0.1.3-win-x64-Setup.exe` (not `Deskland-Setup.exe`).
- Size: **28,001,125 bytes**, verified against official release metadata.
- SHA-256: `e253cad56f1ea0ee2fb9d13ebe8a44f7dbe7232a506ba752cbe54c939c17bf44`, verified against the published `.sha256` companion before REA analysis.
- Engine: `rea-agents@6.9.0`, CLI only, Node 24, installed temporarily in isolated GitHub runner; existing AppLab `scripts/rea_cli_bridge.py` invoked with allowlisted operations.
- Run: https://github.com/riccardopinato/AppLab/actions/runs/44614264474 (workflow head `2209b1a77743776c15e1786b8eb9f996e0005ec4`).
- Research artifact: `deskland-preview-v0-1-3-rea-research` (Actions artifact **14574396780**, 14-day retention). Contains public manifest, version, raw REA evidence JSON, bridge receipt and summary; deliberately **does not contain the executable**.
- Evidence file SHA-256 imports: `fdade6383df210a50b6e65c45d99e564bee676ea52d5ef769dcacc2c0d07ca12`.
- Evidence file SHA-256 PE certificates: `807e403523754bfd0696d569b318b09af794f686b6a80533a5d3466d13999909`.

## Observed outer Windows installer (not installed application)

| Observation | Actual verified evidence | Boundary |
|---|---|---|
| Outer format | PE32 `machine=332`, x86, 32-bit, REA `format=pe32` | Installer stub is 32-bit despite the release target/name being win-x64 |
| Imported libraries | 7 distinct DLLs: `ADVAPI32.dll`, `SHELL32.dll`, `ole32.dll`, `COMCTL32.dll`, `USER32.dll`, `GDI32.dll`, `KERNEL32.dll` | Import presence is not runtime call proof |
| Native imports | 163 standard imports; REA coverage `complete`, no issues | Installer bootstrapper, not `host/bin/Deskland.exe` |
| Delay-loaded imports | None declared | No inference about dynamic loading at runtime |
| Import hash | pefile-compatible `46ce5c12b293febbeb513b196aa7f843` | Useful only for comparing this installer family |
| PE certificate table | `IMAGE_DIRECTORY_ENTRY_SECURITY` absent, 0 `WIN_CERTIFICATE` rows; complete coverage for this table | Does not establish all signature/catalog possibilities nor security of binary |
| Release manifest | 43 declared payload paths and SHA-256 entries | **Manifest observed**, not independent extraction or byte validation of all embedded files |
| Runtime execution | None | No installer execution, permissions, network calls at runtime, GUI interaction or Windows registry mutation observed |

The 43-path public manifest declares `host/bin/Deskland.exe`, WebView2 DLLs, `Deskland-source.zip`, notices, HTML/JS themes and assets. It is consistent with the upstream installer scripts (NSIS) but the installed payload itself has **not been unpacked** in this pilot.

## Value compared with source-only Deskland reconnaissance

- **Binary-only packaging observations:** real installer PE32/x86 classification, complete import table/hash, and absent PE embedded certificate table. This distinguishes the *outer installer* from the **x64 Windows host** described by upstream C# build scripts.
- **Confirmation rather than new product capability:** the public release manifest and installer recipe already explain WebView2, per-user installation, source archive and Beach/Meadow. The 163 imports add packaging detail but **do not reveal a transferable new Android feature**.
- **Decision:** REA CLI integration has demonstrated meaningful real-artifact inspection; **no evidence yet for broad automatic REA execution across App Factory** and **no new Android implementation task or certified donor** from this binary. Apply the CLI selectively to authorized files without adequate sources.
- **Next gate:** inspect the *exact original historic installer* once its bytes are actually made available; compare independent SHA/signature/imports/resources, then revisit Android relevance. Never substitute this public v0.1.3 sample for that artifact.

## Trust and intellectual property

REA raw output has been reviewed for these *specific fields* by matching its JSON receipt and normalized results; its remaining claims are **external evidence subject to review**. Deskland remains GPL-3.0, and the independent Flutter/Kotlin Android app does not import its code or artwork. No E3 donor, Golden, device acceptance, store readiness or Windows runtime QA is implied.
