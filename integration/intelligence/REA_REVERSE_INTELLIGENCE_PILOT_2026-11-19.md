# Reverse Engineering & Software Intelligence — AppLab research pilot

## Public Preview binary experiment — 19 November 2026

A *real* official binary was statically inspected using REA 6.9.0 CLI. Outcome: **PASS** for the public Deskland Preview v0.1.3 PE32/x86 installer, 7 imported DLLs / 163 imports, no embedded PE certificate table, 43-file published manifest. The original `Deskland-Setup.exe` previously uploaded in another chat remains **UNAVAILABLE AND NOT ANALYZED**. The new report documents the exact hashes, selected raw-Evidence fields, no-functional-donor decision and source-vs-binary boundaries: [REA_DESKLAND_PREVIEW_BINARY_REPORT_2026-11-19.md](REA_DESKLAND_PREVIEW_BINARY_REPORT_2026-11-19.md). Proof run [#44614264474](https://github.com/riccardopinato/AppLab/actions/runs/44614264474).

## CLI execution adapter — 19 November 2026 (supersedes the source-only status below)

**New code:** `scripts/rea_cli_bridge.py` invokes pinned `rea-agents@6.9.0`
directly through the local CLI; no MCP, no daemon, no automatic npm install
and no execution of the inspected Windows artifact. The earlier section
below is the archived *static-intake-only* baseline, not the new capability state.

Supported allowlisted static operations: `inspect-pe-imports`,
`inspect-pe-certificates`. It verifies the Node runtime and REA
`--version --json`, source SHA, input SHA-256 before/after, PE admission,
input size (64 MiB default / 512 MiB maximum), timeouts and JSON output size.
Evidence is written to an explicitly supplied **private local directory**
without overwriting divergent existing files; the stdout receipt contains
hashes, exit codes and `RESEARCH_ONLY`, not trusted AppLab E3 evidence.

**Install outside the application repo (explicit local action):**

```bash
npm install --prefix /absolute/rea-tools --no-save --omit=optional --no-audit --no-fund rea-agents@6.9.0
```

**Linux example:**

```bash
python scripts/rea_cli_bridge.py \
  --rea-bin /absolute/rea-tools/node_modules/.bin/rea \
  --artifact /absolute/Deskland-Setup.exe \
  --output-dir /absolute/private-research \
  --repository BLEZZ0102/Deskland \
  --source-sha 9818b577402ff476e1b59da07970c56472713126
```

**Windows:** provide `--rea-bin "C:\\Program Files\\nodejs\\node.exe"`
(or the actual full path to node.exe) **and**
`--rea-entry "C:\\rea-tools\\node_modules\\rea-agents\\scripts\\rea.mjs"`.
Never pass the `.cmd` shim. For files above 64 MiB add
`--max-bytes 300000000` (bounded to 512 MiB), matching actual size.
A Windows installer may be NSIS-wrapped; PE import/certificate findings
describe the **outer executable**, not the full extracted application.

**Actual test lane:** `.github/workflows/rea-cli-static-smoke.yml` installs
the pinned npm package in an ephemeral GitHub runner and invokes **real REA**
on an inert synthetic PE fixture. It NEVER pulls or runs the historical
Deskland installer. Unit tests use a separate CLI stub and are not by
themselves proof of the REA engine. A green smoke is CLI functionality
proof for that fixture only, not arbitrary installer success.

**Outstanding:** original user-supplied Deskland installer is unavailable
here; no real Deskland binary analysis/asset inventory or actual Windows
execution is claimed. A private local user run is the next evidence gate.
REA license MIT; Deskland upstream GPL-3.0; do not transfer protected code or
art assets into the independent commercial Android app.

---


**2026-11-19 · SOURCE IMPLEMENTED / REAL DESKLAND INSTALLER NOT VERIFIED**

This is an **opt-in, read-only research adapter**. It is NOT a replacement
for the AppLab trusted verifier, runtime tests, agent scheduler, QA score,
donor certification engine or App-Factory-Core Golden Registry.

## Ownership and trust boundary

1. Authority: App-Factory-Core CURRENT + Product Bible + app AGENTS.md +
   relevant OSS reconnaissance and Single-Donor admission Golden.
2. External candidate: morluto/rea at
   4491c84c82140a43fa12390b727840a433875ba8 (package.json v6.9.0,
   REA MIT). It is **not installed, vendored or executed** in AppLab.
   Optional third-party decompilers and inspected targets keep their own
   rights, licenses, risks and permissions.
3. Static intake: scripts/rea_artifact_intake.py reads a caller-provided
   **regular local file** up to a bounded size and returns SHA-256, length,
   PE container/machine facts when present. It never executes the target.
4. Optional REA output is only fingerprinted as UNVALIDATED_EXTERNAL_OUTPUT,
   without accepting instructions, claims, certification or source code.
5. A human-reviewed donor research dossier can cross-link this intake,
   exact source SHA, target rights, independent feature design and consumer
   tests. No automatic CAP/Golden promotion or app source modifications.

## Command (local, explicitly supplied file)

Requires Python 3.12+. No pip, REA binary, paid engine, daemon or cloud API.

    python scripts/rea_artifact_intake.py \
      --artifact /ABSOLUTE/PATH/Deskland-Setup.exe \
      --repository BLEZZ0102/Deskland \
      --source-sha 9818b577402ff476e1b59da07970c56472713126 \
      --rea-commit 4491c84c82140a43fa12390b727840a433875ba8 \
      > deskland-artifact-identity.json

For separately authorized REA execution, supply --rea-report PATH afterwards.
Do not run npx @latest or attach a debugger/browser/device implicitly.
Never commit private binaries or local reports to a public branch or CI.

## Deskland pilot facts

- Source upstream: BLEZZ0102/Deskland at
  9818b577402ff476e1b59da07970c56472713126; GPL-3.0.
- Consumer: riccardopinato/Adaptive-Landscape-Android, original Flutter
  editor + Android WallpaperService. No upstream code or assets copied.
- Inspectable now: upstream host/DesktopHost.cs, host/build.ps1,
  prototype/themes.json and current Android repo docs.
- **Unavailable:** original historic chat upload Deskland-Setup.exe bytes.
  Old text described an NSIS installer ~260 MiB, but no direct hash or
  extraction proof exists. Upstream public v0.1.3 preview installer is
  only ~28 MiB and cannot be silently substituted for that artifact.
- Therefore: installer manifest/imports/extracted binaries/resources,
  reverse-engineering trace, runtime/window observations, physical
  visual fidelity and Android parity all remain NOT_VERIFIED.
- Source-only investigation dossier lives in
  Adaptive-Landscape-Android/docs/REA_DESKLAND_PILOT_2026-11-19.md.

## Measurable next gate

Before expanding REA into AppLab execution, require an actual authorized
installer with SHA-256, reproducible REA engine/version pins, output
coverage/limitations, at least two materially useful findings absent from
source-only inspection, a rights review, and tested Android alternatives.
Physical/OEM/Play evidence is independent. No automatic decompilation
or copying of proprietary/GPL-derived source into the Android app.

Current admission: **RESEARCH CANDIDATE (E1 source provenance only)**.
