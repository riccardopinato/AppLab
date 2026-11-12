# X10-018 — Golden package compatibility harness (offline)

**Scope:** harness machine-readable per l'[X10-017 package contract](https://github.com/riccardopinato/Idee-app-Archivi-riferimenti/blob/62912f973341b835585cec52b7ff9749524816ba/19-APP-FACTORY-10X/contracts/README.md), Factory baseline `c5adc147046beb7024629466d10eeb799c3c2619`.

Implemented [`scripts/golden_compat_harness_x10.py`](../../scripts/golden_compat_harness_x10.py) and [regression tests](../../backend/tests/test_x10_golden_compat.py). Consume X10-017 manifest and an array of test receipts. Fail closed on:
- DESIGN_ONLY package, missing extracted source files or unreviewed license;
- non-pinned SHA/versions; donor different from manifest, consumer not approved, or incompatible Dart/Flutter pair;
- missing/failed donor or consumer tests, duplicate receipts or one consumer masquerading as two;
- absence of rollback test or rollback to an invalid/mismatched package version;
- any publication authorization (this harness has **no** release rights).

Example command, after supplying genuine external evidence files:

`python3 scripts/golden_compat_harness_x10.py --manifest /path/to/manifest.json --receipts /path/to/ci_receipts.json`

**Trust boundary:** input receipts are untrusted self-reported metadata. The result is **STRUCTURAL_PASS_REVIEW_REQUIRED**, never CERTIFIED; CI/check URLs, exact source commit, runner trust and the fact Flutter tests truly executed must be independently reviewed. The harness neither invokes Flutter nor fetches network data. Test suite uses synthetic fixtures strictly for logic. No package version or Golden registry state is promoted. Runtime donor+consumer execution belongs to the subsequent X10-026 adoption campaign; physical/Play evidence separate.
