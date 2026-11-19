# REA CLI — Deskland Preview v0.1.3: binary and extracted-host pilot

**2026-11-19 · VERIFIED STATIC OBSERVATIONS / RESEARCH-ONLY / NOT GOLDEN**

This dossier documents **one exact official public preview**. The historic user-uploaded `Deskland-Setup.exe` from another conversation is **not available**; it has not been hashed, extracted, inspected or executed. Never equate that missing installer to this public v0.1.3 release.

## Evidence provenance and reproducibility

- Deskland source: [BLEZZ0102/Deskland@9818b577402ff476e1b59da07970c56472713126](https://github.com/BLEZZ0102/Deskland/tree/9818b577402ff476e1b59da07970c56472713126), GPL-3.0.
- Official binary: [Deskland Preview v0.1.3, 7 Nov 2026](https://github.com/BLEZZ0102/Deskland/releases/tag/v0.1.3), `Deskland-Preview-0.1.3-win-x64-Setup.exe`.
- External engine: `morluto/rea@4491c84c82140a43fa12390b727840a433875ba8`, `rea-agents@6.9.0` (MIT), direct CLI only, ephemeral GitHub runner with Node 24.
- Workflow/code: `.github/workflows/rea-deskland-preview-research.yml` and existing `scripts/rea_cli_bridge.py`.
- **Final binary + host pilot:** [GitHub run #44615407360](https://github.com/riccardopinato/AppLab/actions/runs/44615407360), workflow head `668e0ce9db8b36fe06f522beaee935889b5cc5f5`; downloadable research artifact ID **14573359629** (temporary 14-day retention), intentionally excludes installer, extracted executables and artwork.
- Prior runs: outer installer REA proof [#44614264474](https://github.com/riccardopinato/AppLab/actions/runs/44614264474), NSIS extraction proof [#44615097169](https://github.com/riccardopinato/AppLab/actions/runs/44615097169).
- No package install, launch, Windows registry operations, network observation, user-interaction or mobile runtime verification. `RESEARCH_ONLY`; observations are bounded to static inputs.

## 1. Public installer: integrity and PE facts

| Field | Verified from binary or published checksum |
|---|---|
| Exact file size | **28,001,125 bytes** |
| SHA-256 | `e253cad56f1ea0ee2fb9d13ebe8a44f7dbe7232a506ba752cbe54c939c17bf44`, matches official `.sha256` |
| Installer wrapper | **PE32, 32-bit x86**, despite release's x64 target |
| Import directory | **7 Windows DLLs / 163 standard imported functions**, REA coverage complete, 0 delay-load entries |
| DLL names | ADVAPI32, SHELL32, ole32, COMCTL32, USER32, GDI32, KERNEL32 |
| pefile-compatible import hash | `46ce5c12b293febbeb513b196aa7f843` |
| PE certificate security table | Absent, 0 WIN_CERTIFICATE entries, coverage complete for this table |

The imports belong to **the NSIS setup wrapper**. Their existence neither establishes actual runtime calls nor characterizes the installed `Deskland.exe`. Missing PE embedded certificates do not exclude Windows catalog signatures or imply a complete trust/safety assessment.

## 2. Static extraction: payload verified byte-for-byte against official manifest

The Linux runner listed and extracted the official NSIS package using 7-Zip, **without running it**.

- **48 physical files** extracted, **30,244,401 bytes** total.
- **43/43** published payload paths were located and matched their published per-file SHA-256 checksums.
- Five additional NSIS/plugin-stage files (not included in the published 43-file payload manifest): `$PLUGINSDIR/modern-wizard.bmp`, `$PLUGINSDIR/System.dll`, `$PLUGINSDIR/MicrosoftEdgeWebview2Setup.exe`, `$PLUGINSDIR/nsDialogs.dll`, `$PLUGINSDIR/LangDLL.dll`.
- Published payload includes `host/bin/Deskland.exe`, WebView2 runtime bridge binaries, `Deskland-source.zip`, legal notices, the Beach/Meadow HTML/JS themes, preview thumbnails and artwork. **These files were inspected for identity only; no assets/code were imported into our Android app.**
- NSIS package-level paths and checksums agree with the source packaging script `tools/build-installer.ps1`; they do **not** prove install-time user experience, registry changes or third-party runtime behavior.

## 3. Real extracted Windows host: managed assembly facts

- Path: `host/bin/Deskland.exe`, **94,208 bytes**.
- SHA-256: `5337c513e8c14dc492900d315cd57e287e9dfb4ba750ccf96c2fb668fa4ea530`, matches the official public payload manifest.
- REA `inspect-pe-imports`: **PE32+ x86_64**, zero conventional PE import-directory functions, coverage complete. Absence of PE imports **does not mean absence of Win32 calls**: the managed metadata has **40 ImplMap (P/Invoke) rows**.
- REA `inspect-managed-artifact`: valid **managed CIL, IL-only**, assembly name `Deskland`, version **0.1.3.0**, CLR metadata version `v4.0.30319`; 28 defined types and **200 methods** in metadata, with **7 assembly references**.
- Assembly references: `mscorlib` 4.0, `System` 4.0, `System.Drawing` 4.0, `System.Windows.Forms` 4.0, `System.Web.Extensions` 4.0, `Microsoft.Web.WebView2.Core` **1.0.4191.47**, `Microsoft.Web.WebView2.WinForms` **1.0.4191.47**. These are metadata references, not runtime dependency resolution.
- REA `inspect-pe-certificates` on the *host*: PE certificate table absent. Managed strong-name public key absent; not equivalent to a complete Authenticode/catalog-signature check.
- REA managed classification reports runtime family `unknown`; do **not** claim the precise installed .NET runtime was measured. Source uses .NET Framework, and the references/metadata are consistent with that source design.

## 4. Interpretation for Adaptive Landscape Android

| Desktop finding | Android disposition |
|---|---|
| NSIS wrapper 32-bit + 64-bit CIL host | Windows installer implementation detail: **NO_PORT** |
| Windows shell interaction, native P/Invoke and icon coordinate reading | **REWRITE/ADAPT** with Android `WallpaperService`; automatic reading of icons is not available to an ordinary live wallpaper |
| WebView2, HTML/JS desktop host and local themes | **PATTERN_RESEARCH_ONLY**; independently authored Flutter/Kotlin native rendering and local state remain preferred |
| Installed bundled assets and GPL source ZIP | **DO_NOT_COPY** into commercial-target Android product under existing app policy |
| Visibility/pause/restore behavior suggested by Windows source | **CANDIDATE FOR QA COMPARISON**, not directly interoperable Android code; current native lifecycle requires physical device tests |
| New Android product functionality discovered only in public binary | **NONE VERIFIED** |

**Measured value:** REA CLI successfully inspected an independently hashed public executable, extracted its source-verified payload and characterized the real .NET host. This is a real **software-intelligence tooling proof**. It did **not** expose at least two *new transferable Android capabilities* absent from the source-only audit, so broad default invocation / Golden promotion is **DEFERRED**. Prefer REA for authorized software whose source is absent or incomplete.

## 5. Trust/release boundaries

The full external JSON reports remain `UNVALIDATED_EXTERNAL_OUTPUT` beyond the specific selected fields cross-checked here against official checksums and machine-readable structures. No consumer build change, APK, user acceptance, device testing, REA MCP server, automatic agent, E3 donor admission, E5 Golden or store readiness is implied. The historical user installer remains the next *separate* evidence gate.
