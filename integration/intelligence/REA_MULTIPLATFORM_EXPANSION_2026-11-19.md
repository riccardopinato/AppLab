# REA CLI — Multi-platform intelligence lanes (2026-11-19)

**Implementation:** optional, direct local REA CLI; no MCP. AppLab is the research owner, not a trusted runtime verifier. Factory baseline `riccardopinato/App-Factory-Core@cac009697970490e45f9aaa9e7e7634016607273`, Golden `rea_cli_reverse_intelligence` COPY-READY.

## Scripts

`scripts/rea_research_cli.py` adds four **separate, allowlisted** static families to existing PE adapter `scripts/rea_cli_bridge.py`:

| Family | Exact command(s) | Input | Dependencies/limitations |
|---|---|---|---|
| `desktop` | `inspect-desktop-application` | extracted desktop directory | bounded total bytes/file count, no symlink, no execution |
| `managed` | `inspect-managed-artifact` | `.exe/.dll` PE | CLR metadata, *not* .NET runtime behavior |
| `flutter` | `identify-flutter-build`, `inspect-dart-aot` | compiled Flutter APK | parses build/AOT, not Flutter source/UI or full decompilation |
| `android` | `inspect-android-package` | APK | **requires separate verified** JADX JAR 0.7.1, SHA256 `6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75`, plus Java; no installation performed by adapter |

Use `--family`, optional `--operation` (else all allowlisted commands in family), `--artifact` absolute path, `--output-dir` distinct private path, `--repository OWNER/REPO`, `--source-sha FULL_SHA`, `--rea-bin` absolute path, optionally `--rea-entry` for Node.js on Windows, `--expected-sha256`, `--timeout` 5–180s and `--max-bytes` up to 512 MiB. Neither optional native tools nor REA itself are installed by these scripts. REA version 6.9.0 and supported Node runtime are enforced.

Example (authorized, locally available Flutter APK):

```bash
python scripts/rea_research_cli.py --rea-bin /opt/rea/node_modules/.bin/rea \
  --family flutter --artifact /abs/path/app-release.apk \
  --output-dir /abs/private-evidence --repository OWNER/APP \
  --source-sha FULL_40_HEX_SHA \
  --operation build --operation aot
```

`scripts/rea_donor_research.py` converts a valid CLI receipt into **E1 RESEARCH ONLY** after verifying each saved report hash. An optional explicit `--source-review` JSON provides concrete, manually checked source comparisons and license bases before expressing `ADOPT`, `REFERENCE`, `DEFER` or `REJECT`; no canonical CAP or Golden admission is minted.

Example:

```bash
python scripts/rea_donor_research.py --receipt /abs/private-receipt.json \
  --evidence-dir /abs/private-evidence --output /abs/private-donor-e1.json
```

## Evidence and gates

- `backend/tests/test_rea_research_cli.py`: synthetic positive/negative CLI tests for local Desktop, managed and Flutter files; forbidden symlinks, wrong version/operation, budgets and tampered evidence; intentionally **no fake JADX PASS**.
- `backend/tests/test_rea_donor_research.py`: receipt integrity, manual-review gates, immutable E1-only status.
- Existing `.github/workflows/rea-cli-static-smoke.yml` runs these regressions and the real REA synthetic PE smoke.
- Existing `.github/workflows/rea-deskland-preview-research.yml` additionally invokes **generalized** Desktop + managed CLI commands on the source-authenticated official public Deskland Preview v0.1.3, and produces an E1-only donor research report. No historic user installer is assumed accessible.
- **Independent consumer** (separate project and job): `Adaptive-Landscape-Android/.github/workflows/rea-independent-flutter-research.yml` builds its own release APK and invokes Flutter and Android REA commands with optional source-verified JADX JAR. Its end-to-end PASS must be observed on its own immutable PR head, not inferred from adding workflow text.

## Decision logic and performance

REA is opt-in only when it can reveal something not easily available from source/CI. For each pilot compare `new_verified_findings`, `manual_investigation_time_saved` (only if measured), `license_safe_reuse_candidates` and `evidence_quality`. If no new actionable information is found (as in public Deskland), mark `DEFER`, not a fabricated reusable donor.

No user binary or raw metadata is to be uploaded to public repositories. Runner artifacts include only public example metadata or private local receipts under explicit authorization. These lanes do not replace AppLab trusted evidence, Flutter analyze, exact-head build, physical tests or Play verification.

**Promotion gate:** two independent real successful consumers/contexts with reproducible exact-head positive/negative evidence, independently reviewed and licensed source deltas. The Golden remains `COPY-READY PROCESS` until the central Core admission is separately updated with that proof.
