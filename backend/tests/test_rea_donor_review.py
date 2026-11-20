"""No evidence-to-donor escalation, tamper/failure controls."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from rea_donor_review import review


@pytest.fixture
def rig(tmp_path):
    evidence = tmp_path / "raw"
    evidence.mkdir()
    raw = evidence / "deadbeef-inspect-android-package.json"
    raw.write_text('{"normalized_result":{"package":"test"}}', encoding="utf8")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({
        "type": "REA_RESEARCH_CLI_RECEIPT",
        "status": "REA_RESEARCH_OBSERVED",
        "donor_admission": "RESEARCH_ONLY",
        "trusted_runtime": False,
        "repository": "riccardopinato/Android-Omni-Cleaner",
        "source_sha": "1" * 40,
        "artifact": {"sha256": "f" * 64},
        "engine": {"version": "6.9.0"},
        "operations": [{
            "operation": "inspect-android-package", "status": "OBSERVED",
            "evidence": {"file": raw.name,
                "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "bytes": raw.stat().st_size}
        }]
    }), encoding="utf8")
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps({"findings": [{
        "id": "omni_manifest",
        "decision": "REFERENCE_ONLY", "source_comparison": "ALREADY_IN_SOURCE",
        "rights": "AUTHORIZED_FOR_RESEARCH",
        "evidence_operation": "inspect-android-package",
        "reason": "The Android manifest was already explicitly inspected in the source tree."
    }]}), encoding="utf8")
    return receipt, evidence, findings, raw


def test_research_review_does_not_certify_or_modify_catalog(rig):
    receipt, evidence, findings, _ = rig
    result = review(receipt, evidence, findings)
    assert result["catalog_mutated"] is False
    assert result["golden_promoted"] is False
    assert result["certified_donors"] == 0
    assert result["adopt_candidate_count"] == 0
    assert result["new_ideas"] == 0
    assert result["classification"] == "E1_RESEARCH_REVIEW_PENDING_CATALOG_PR"


def test_cannot_relabel_unreviewed_as_donor(rig):
    receipt, evidence, findings, _ = rig
    d = json.loads(findings.read_text())
    d["findings"][0]["decision"] = "ADOPT_CANDIDATE"
    findings.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="requires NEW"):
        review(receipt, evidence, findings)


def test_evidence_tamper_and_failed_receipt_block(rig):
    receipt, evidence, findings, raw = rig
    raw.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="mismatch"):
        review(receipt, evidence, findings)
    raw.write_text('{"normalized_result":{"package":"test"}}')
    d = json.loads(receipt.read_text())
    d["status"] = "REA_RESEARCH_PARTIAL_OR_FAILED"
    receipt.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="research-only"):
        review(receipt, evidence, findings)


def test_unverified_operations_and_duplicate_ids_block(rig):
    receipt, evidence, findings, _ = rig
    d = json.loads(findings.read_text())
    d["findings"][0]["evidence_operation"] = "identify-flutter-build"
    findings.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="missing or unverified"):
        review(receipt, evidence, findings)
    d["findings"][0]["evidence_operation"] = "inspect-android-package"
    d["findings"].append(d["findings"][0])
    findings.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="Duplicate"):
        review(receipt, evidence, findings)
