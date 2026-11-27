# AppLab Spec Lite evidence adapter — Step 4 / bounded source proof

**Factory:** `App-Factory-Core@8b3d9263ad1a72f3b8a43273550fe43646780d78` (Master v27, Index v31). **AppLab source baseline:** `817a65dfdeb53750ce2ec4fb224a691dc29b8953`. **Agent Core source:** `e7903b33f9bd03a969f039d8c20292532a92951c` before the Step 4 adapter PR. No new scheduler, WorkGraph, evidence engine, database, trust authority, provider or local worker.

`scripts/spec_lite_evidence_adapter.py` is a **pure projection layer**:

- Consumes the source-pinned Spec Lite manifest and the side-effect-free `FSL_WORK_ITEM_TRACE_PROJECTION` from Agent Core's companion adapter.
- Validates the **existing** `APPLAB_WORK_ITEM` with `agent_work_graph_v60a.validate_work_item` and AppLab's own contract; rejects changed immutable WorkItem ID, repository or source SHA.
- Requires stable `FR-`/`AC-` requirements and an explicit `required_checks` entry for every acceptance criterion; reconciles the acceptance map to the Agent Core projection's immutable manifest digest.
- Links only receipts that pass an independently injected, **trusted AppLab evidence verifier**; receipt self-assertions, fake status text and arbitrary user URLs are not proof.
- For identical receipt replay, deduplicates by ID; conflicting ID reuse fails closed; no second evidence store.
- Missing tests → `MISSING_EVIDENCE`; complete source receipts without verified product approval → `SOURCE_EVIDENCE_LINKED_NOT_APPROVED`; independent product approval plus linked receipts → `SOURCE_EVIDENCE_LINKED_NOT_CERTIFIED`. Even a complete link **never** mints AppLab PASS, physical/device proof, Windows E2E, production or Play certification.
- The adapter does not mutate WorkItems or schedules. AppLab's existing verification/certification authorities remain authoritative. The caller must pass the **real** externally validated run/receipt verifier, never a self-claimed Boolean.

**Test evidence:** `python tests/contracts/spec_lite_evidence_adapter_test.py` runs offline against a real WorkGraph fixture and its canonical validator, with mocked trust callbacks. There are 16 tests including missing evidence/type, SHA drift, binding drift, receipt tampering, replay, untrusted verifier, missing approval and WorkGraph authority tampering. Existing `.github/workflows/ci.yml` runs this test alongside v60a and the full AppLab suite. No live trusted provider/runtime assertions are made by test mocks.

**Promotion boundary:** The source adapter may be considered source-CI verified after an exact-head PR CI and post-merge main CI. A genuine AppLab E2E integration would require independently authenticated receipts and real persisted operation/lease evidence; that is outside this pilot's scope.

**Additional fail-closed invariants (review):** `expected_job_sha256` is a mandatory trusted caller input, independent from the untrusted binding; altered 64-character job digests are denied. Every `validation.required_checks` entry MUST be mapped by at least one AC or fail with `REQUIRED_CHECK_UNMAPPED` (including an unmapped `DEVICE_TEST`). Unit fixtures exercise these cases without claiming physical verification.
