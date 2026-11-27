"""Offline acceptance projection tests using the real AppLab WorkGraph schema.

Receipt callbacks below are TEST FAKES, not provider attestations.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_work_graph_v60a as graphmod  # noqa: E402
import durable_brain_v54a as brain  # noqa: E402
from spec_lite_evidence_adapter import (  # noqa: E402
    SpecEvidenceError, project_spec_evidence
)

REPO = "riccardopinato/GalleryDrift"
SHA = "a" * 40
APPLAB = "c" * 40
FACTORY = "8b3d9263ad1a72f3b8a43273550fe43646780d78"


def manifest():
    return {
        "schema_version": 1, "spec_id": "FSL-20261127-STEP4-EVIDENCE",
        "factory": {"repository": "riccardopinato/App-Factory-Core", "sha": FACTORY,
                    "resolver": "CURRENT.yaml"},
        "target": {"repository": REPO, "source_sha": SHA},
        "canonical_refs": {"factory_current": {"repository": "riccardopinato/App-Factory-Core",
                                              "sha": FACTORY, "path": "CURRENT.yaml"}},
        "approval": {"status": "PROPOSED", "decision_ref": None},
        "requirements": [
            {"id": "FR-001", "status": "PROPOSED", "conflicts_with": [],
             "acceptance": [
                 {"id": "AC-001", "evidence_type": "UNIT_TEST"},
                 {"id": "AC-002", "evidence_type": "INTEGRATION_TEST"},
             ]}],
        "validation": {"required_checks": ["UNIT_TEST", "INTEGRATION_TEST"]}
    }


def create_work_item():
    operation = brain._operation_fixture(
        "op_spec_lite_step4", REPO, "main", SHA, APPLAB
    )
    return graphmod.adapt_operation_to_work_item(
        operation, work_item_id="wrk_spec_lite_step4", allow_code_edit=False
    )


def binding(manifest_value, item):
    digest = hashlib.sha256(json.dumps(manifest_value, sort_keys=True,
                                       separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return {
        "schema_version": 1, "record_type": "FSL_WORK_ITEM_TRACE_PROJECTION",
        "binding_id": "fsl_" + "b" * 32, "spec_id": manifest_value["spec_id"],
        "spec_sha256": digest, "job_sha256": "d" * 64,
        "repository": REPO, "source_sha": SHA,
        "work_item_id": item["work_item_id"], "operation_id": item["operation_id"],
        "acceptance": [
            {"requirement_id": "FR-001", "acceptance_id": "AC-001", "required_check": "UNIT_TEST"},
            {"requirement_id": "FR-001", "acceptance_id": "AC-002", "required_check": "INTEGRATION_TEST"},
        ],
        "authority": "TRACE_ONLY", "runtime_verified": False, "side_effects_performed": False,
        "dispatch_performed": False, "certified": False,
    }


def receipt(item, ac="AC-001", kind="UNIT_TEST", evidence_id="ev_test_01"):
    return {"evidence_id": evidence_id, "acceptance_id": ac, "check_type": kind,
            "repository": REPO, "resolved_sha": SHA, "work_item_id": item["work_item_id"],
            "outcome": "PASS", "run_url": "https://github.com/riccardopinato/AppLab/actions/runs/0"}


class SpecLiteEvidenceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.spec = manifest()
        self.item = create_work_item()
        self.bind = binding(self.spec, self.item)

    def evaluate(self, receipts=None, trusted_evidence_verifier=None,
                 trusted_product_decision=None):
        return project_spec_evidence(
            self.spec, self.bind, self.item, receipts if receipts is not None else [],
            expected_factory_sha=FACTORY, expected_source_sha=SHA,
            expected_job_sha256="d" * 64,
            trusted_evidence_verifier=trusted_evidence_verifier,
            trusted_product_decision=trusted_product_decision,
        )

    def assertDeny(self, fragment, action):
        with self.assertRaises(SpecEvidenceError) as caught:
            action()
        self.assertIn(fragment, str(caught.exception))

    def test_existing_real_workgraph_contract_validates_fixture_item(self):
        self.assertEqual(graphmod.validate_work_item(self.item, graphmod.load_contract())["authority"],
                         "ORCHESTRATION_ONLY")

    def test_missing_tests_remain_not_verified(self):
        result = self.evaluate()
        self.assertEqual(result["state"], "MISSING_EVIDENCE")
        self.assertEqual(result["missing_acceptance_ids"], ["AC-001", "AC-002"])
        self.assertFalse(result["certified"])

    def test_one_missing_check_blocks_completeness(self):
        result = self.evaluate([receipt(self.item)], lambda record, item: True)
        self.assertEqual(result["state"], "MISSING_EVIDENCE")
        self.assertEqual(result["missing_acceptance_ids"], ["AC-002"])

    def test_all_fake_fixture_receipts_only_link_source_evidence(self):
        sample = [receipt(self.item), receipt(self.item, ac="AC-002",
                          kind="INTEGRATION_TEST", evidence_id="ev_test_02")]
        result = self.evaluate(sample, lambda record, item: True)
        self.assertEqual(result["state"], "SOURCE_EVIDENCE_LINKED_NOT_APPROVED")
        self.assertEqual(result["linked_evidence_count"], 2)
        self.assertEqual(result["missing_acceptance_ids"], [])
        self.assertFalse(result["runtime_verified"])
        self.assertFalse(result["physical_verified"])
        self.assertFalse(result["certified"])
        self.assertFalse(result["work_item_mutated"])

    def test_same_receipt_replay_deduplicates_without_new_store(self):
        single = receipt(self.item)
        result = self.evaluate([single, copy.deepcopy(single)], lambda rec, item: True)
        self.assertEqual(result["linked_evidence_count"], 1)
        self.assertEqual(result["state"], "MISSING_EVIDENCE")

    def test_receipt_replay_changed_identity_denied(self):
        first = receipt(self.item)
        changed = copy.deepcopy(first)
        changed["check_type"] = "INTEGRATION_TEST"
        self.assertDeny("REPLAY_RECEIPT_IDENTITY_CONFLICT",
                        lambda: self.evaluate([first, changed], lambda rec, item: True))

    def test_wrong_sha_or_workitem_ref_denied(self):
        bad = receipt(self.item)
        bad["resolved_sha"] = "f" * 40
        self.assertDeny("EVIDENCE_IMMUTABLE_IDENTITY_MISMATCH",
                        lambda: self.evaluate([bad], lambda rec, item: True))
        self.bind["source_sha"] = "f" * 40
        self.assertDeny("WORKITEM_SOURCE_OR_IDENTITY_MISMATCH", self.evaluate)

    def test_untrusted_or_missing_evidence_verifier_rejected(self):
        self.assertDeny("EXISTING_TRUSTED_VERIFIER_REQUIRED",
                        lambda: self.evaluate([receipt(self.item)]))
        self.assertDeny("UNTRUSTED_EVIDENCE",
                        lambda: self.evaluate([receipt(self.item)], lambda rec, item: False))

    def test_declared_test_missing_in_manifest_denied(self):
        self.spec["validation"]["required_checks"] = ["UNIT_TEST"]
        self.bind["spec_sha256"] = hashlib.sha256(json.dumps(self.spec, sort_keys=True,
                                separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        self.assertDeny("REQUIRED_TEST_NOT_DECLARED", self.evaluate)

    def test_binding_fingerprint_detects_spec_modification(self):
        self.spec["requirements"][0]["acceptance"][0]["id"] = "AC-999"
        self.assertDeny("UNTRUSTED_OR_CHANGED_SPEC_BINDING", self.evaluate)

    def test_applab_authority_envelope_is_not_overridable(self):
        self.item["authority"] = "CERTIFIER"
        self.assertDeny("EXISTING_APPLAB_WORKITEM_INVALID", self.evaluate)

    def test_write_approval_marker_does_not_grant_acceptance(self):
        self.spec["approval"] = {"status": "APPROVED", "decision_ref": "https://github.com/a/b/issues/1"}
        self.spec["requirements"][0]["status"] = "APPROVED"
        self.bind["spec_sha256"] = hashlib.sha256(json.dumps(self.spec, sort_keys=True,
                                separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        full = [receipt(self.item), receipt(self.item, ac="AC-002", kind="INTEGRATION_TEST",
                                              evidence_id="ev_test_02")]
        result = self.evaluate(full, lambda rec, item: True)
        self.assertEqual(result["state"], "SOURCE_EVIDENCE_LINKED_NOT_APPROVED")
        result = self.evaluate(full, lambda rec, item: True, lambda spec: True)
        self.assertEqual(result["state"], "SOURCE_EVIDENCE_LINKED_NOT_CERTIFIED")
        self.assertFalse(result["certified"])

    def test_unmapped_extra_required_check_denied_even_with_other_receipts(self):
        self.spec["validation"]["required_checks"].append("DEVICE_TEST")
        self.bind["spec_sha256"] = hashlib.sha256(json.dumps(
            self.spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()).hexdigest()
        full = [
            receipt(self.item),
            receipt(self.item, ac="AC-002", kind="INTEGRATION_TEST", evidence_id="ev_test_02"),
        ]
        self.assertDeny("REQUIRED_CHECK_UNMAPPED:DEVICE_TEST",
                        lambda: self.evaluate(full, lambda rec, item: True))

    def test_changed_job_digest_refused_even_when_same_valid_hex_format(self):
        self.bind["job_sha256"] = "e" * 64
        self.assertDeny("BINDING_JOB_DIGEST_MISMATCH", self.evaluate)

    def test_no_trusted_job_digest_fail_closed(self):
        self.assertDeny("TRUSTED_JOB_DIGEST_REQUIRED", lambda: project_spec_evidence(
            self.spec, self.bind, self.item, [],
            expected_factory_sha=FACTORY, expected_source_sha=SHA, expected_job_sha256="",
        ))

    def test_false_binding_runtime_claim_denied(self):
        self.bind["runtime_verified"] = True
        self.assertDeny("BINDING_AUTHORITY_ESCALATION", self.evaluate)


if __name__ == "__main__":
    unittest.main()
