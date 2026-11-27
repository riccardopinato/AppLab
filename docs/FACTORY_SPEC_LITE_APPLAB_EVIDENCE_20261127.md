# AppLab — Factory Spec Lite evidence projection (Step 4)

Status: **SOURCE-ONLY ADAPTER / CI VALIDATION**, not trusted runtime or user/device certification.

Factory baseline: `riccardopinato/App-Factory-Core@8b3d9263ad1a72f3b8a43273550fe43646780d78` (Master 27; Golden Index 31); Agent Core bridge [#37](https://github.com/riccardopinato/App-Factory-Agent-Core/pull/37) retains existing Agent Core permission gateway and AppLab WorkGraph.

`scripts/spec_lite_evidence_adapter.py` projects a bounded Spec Lite requirement and AC set into a read-only `APPLAB_SPEC_LITE_COVERAGE_PROJECTION` using the **existing** `agent_work_graph_v60a.validate_work_item` and independently verified receipts. It adds **no** scheduler, queue, SQL table, worker, lease, execution framework, verifier authority, evidence database or self-approval path.

## Authority boundary

- Factory and target SHA are passed independently as trusted inputs, not inferred from the untrusted manifest or WorkItem.
- The Agent Core trace binding is fingerprinted and must match `spec_id`, immutable job SHA, work item ID, operation ID and repo/source SHA exactly; replay of the same receipt is idempotent.
- Each required acceptance has a fixed `FR-`/`AC-` identifier and a declared test kind. Missing tests yield `MISSING_EVIDENCE`; source or receipt mismatches deny; changed payload for one receipt ID denies.
- A `PASS` string is untrusted until an AppLab-authorized, immutable-evidence verifier supplied from the trusted process approves it. The adapter does **not** implement or replace this verifier.
- An `APPROVED` string in a Spec Lite JSON manifest is not a trusted approval decision. A separate verified decision is required to upgrade only the *label* to `SOURCE_EVIDENCE_LINKED_NOT_CERTIFIED`. Even then `runtime_verified=false`, `physical_verified=false`, `certified=false` remain fixed.
- The adapter only returns a projection. It performs no mutation, workflow dispatch or release.

## Offline validation

Run `python tests/contracts/spec_lite_evidence_adapter_test.py` and the existing full AppLab CI. Test callbacks are intentionally synthetic and are **NOT trusted provider or physical receipts**. Negative test vectors include duplicate/replayed receipts, wrong SHA/work item, missing required tests, absent trusted verifier, manifest drift, unauthorized Product Bible approval and escalated WorkItem authority.

**Scope:** documentation and offline source contract. A real AppLab signed evidence chain and live Agent Core Windows runner E2E remain **NOT VERIFIED**; requiring those as product deployment gates is unchanged. No promotion of Spec Kit as a new Golden.

**Review-gate hardening:** The AppLab caller must independently resolve `expected_job_sha256` from the persisted Agent Core/AppLab operation and supply it separately; the adapter rejects altered job digests even when syntactically valid. Every `validation.required_checks` kind must correspond to at least one feature acceptance criterion. Otherwise it returns `REQUIRED_CHECK_UNMAPPED` rather than silently declaring source coverage complete; e.g., an unmapped `DEVICE_TEST` blocks the projection. These checks are enforced by three dedicated offline negative tests; test fakes are not trusted evidence.

**Signed admission identity (review hardening):** The caller must pass `expected_spec_sha256` independently from the persisted job admission record, in addition to the already separately resolved `expected_job_sha256`. The adapter rejects coordinated changes to both the untrusted manifest and its binding (including removal of an `AC` or a required `INTEGRATION_TEST`) even if both self-recomputed hashes match one another. A new adversarial fixture proves the immutability boundary; it is not a real persisted-operation E2E test.
