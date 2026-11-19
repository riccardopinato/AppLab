# Native Unslop QA — AppLab source advisory v1 (19/11/2026)

**Status:** CANDIDATE / NOT CERTIFIED. Canonical process: App-Factory-Core `contracts/UNSLOP_UI_ANTI_AI_64_BRIDGE_v1.md`; Design-App DSK-011 archive. Upstream `felipebasurto/unslop-ui@cd891160453f26aaacc569bad96a8d10d595076d`, MIT. AppLab adapter is a separately written, native-focused regex triage; it does NOT execute or reimplement the whole upstream skill.

## Usage

```sh
python3 scripts/anti_slop_native_audit.py /path/to/flutter/repo
python3 scripts/anti_slop_native_audit.py /path/to/compose/repo --surface --format text
python3 scripts/anti_slop_native_audit.py /path/to/repo --source-sha EXACT_COMMIT > unslop-qa.json
```

Accepts `.dart`, `.kt`, `.kts`, `.arb` under the specified directory, excluding generated/build/test folders and files over 1 MB. Prints deterministic JSON with U-candidate code, AT crosswalk, source line and evidence boundaries. Supports conservative automatic checks U1/U2/U3/U6/U8/U9/U11/U12 and opt-in U17/U19/U20. U4/U5/U7/U10/U13/U14/U15/U16/U18 **require manual code + screenshot review**, as do the semantic judgments for all detected candidates. No Kotlin or Dart code is changed. Static scanner can generate false positives and cannot prove state binding, accessibility, app behavior or visual quality.

**No required CI gate on total candidates:** `--max N` is optional for curated test fixtures; never impose a universal score threshold on product apps. Exact SHA must be supplied by the caller, not inferred. No local files containing personal data are uploaded. The script does not fetch or send content to a network service.

## Adoption and evidence

1. Link actual source SHA and product-owned Design-App references; store read-only report.
2. Mark each candidate `KEEP_PURPOSEFUL`, `ADAPT`, `REMOVE_CANDIDATE`, `NEEDS_RUNTIME_EVIDENCE`; keep a record of false positives.
3. Any scoped UI fix needs source tests, exact-head CI, native rendered before/after screenshots under matching fixtures, independent review and applicable physical verification.
4. Do **not** mistake this report, upstream test PASS or a Flutter Web snapshot for Android/iOS visual or physical acceptance. Pilot candidates: Anna's Diary (Flutter) and Android Omni Cleaner (Compose, RC1 release frozen).
5. A Golden promotion requires independent two-consumer evidence and central registry approval. No automatic modifications to protected Factory rules or destructive flows.

Unit tests: `PYTHONPATH=backend pytest backend/tests/test_anti_slop_native_audit.py -q` (the existing AppLab CI pytest suite includes this test).
