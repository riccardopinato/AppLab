"""Hash-verified REA research to donor E1, never automatic E3/Golden."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/rea_donor_research.py"


def sample(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    blob = b'{"meta":{"command":"inspect-managed-artifact"}}\n'
    (evidence / "managed.json").write_bytes(blob)
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({
        "mode":"CLI_ONLY_NO_MCP","status":"REA_CLI_STATIC_OBSERVED",
        "repository":"riccardopinato/AppLab","source_sha":"a"*40,
        "input":{"sha256":"b"*64},"family":"managed",
        "operations":[{"operation":"metadata","cli_success":True,
        "json_file":"managed.json","sha256":hashlib.sha256(blob).hexdigest()}]
    }))
    return receipt,evidence,tmp_path / "candidate.json"


def invoke(receipt,evidence,target,*args):
    return subprocess.run([sys.executable,str(SCRIPT),"--receipt",str(receipt),
                           "--evidence-dir",str(evidence),"--output",str(target),*args],
                           check=False,text=True,capture_output=True)


def test_valid_record_keeps_e1_and_no_certification(tmp_path):
    receipt,evidence,out=sample(tmp_path)
    result=invoke(receipt,evidence,out)
    assert result.returncode == 0, result.stderr
    data=json.loads(out.read_text())
    assert data["admission"]=="E1_RESEARCH_ONLY"
    assert data["source_comparison"]=="PENDING"
    assert data["certified_donor"] is False
    assert data["canonical_capability_id"] is None
    assert invoke(receipt,evidence,out).returncode==2  # no overwrite


def test_tampered_evidence_fails_closed(tmp_path):
    receipt,evidence,out=sample(tmp_path)
    (evidence / "managed.json").write_text("{}")
    result=invoke(receipt,evidence,out)
    assert result.returncode==2
    assert "hash changed" in result.stderr
    assert not out.exists()


def test_bad_licensing_and_source_review_rejected(tmp_path):
    receipt,evidence,out=sample(tmp_path)
    src=tmp_path/"source-review.json"
    src.write_text(json.dumps({"source_sha":"c"*40,"artifact_sha256":"b"*64,
                               "findings":[{"decision":"ADOPT","fact":"a","source_comparison":"b","license_basis":"c"}]}))
    assert invoke(receipt,evidence,out,"--source-review",str(src)).returncode==2
    src.write_text(json.dumps({"source_sha":"a"*40,"artifact_sha256":"b"*64,
                               "findings":[{"decision":"CERTIFIED","fact":"a","source_comparison":"b","license_basis":"c"}]}))
    assert invoke(receipt,evidence,out,"--source-review",str(src)).returncode==2


def test_manual_source_comparison_is_not_promotion(tmp_path):
    receipt,evidence,out=sample(tmp_path)
    src=tmp_path/"source-review.json"
    src.write_text(json.dumps({"source_sha":"a"*40,"artifact_sha256":"b"*64,
                               "findings":[{"decision":"REFERENCE",
                                            "fact":"x64 host",
                                            "source_comparison":"not documented in source",
                                            "license_basis":"pattern only, no code copied"}]}))
    result=invoke(receipt,evidence,out,"--source-review",str(src))
    assert result.returncode == 0,result.stderr
    data=json.loads(out.read_text())
    assert data["source_comparison"]=="MANUALLY_REVIEWED"
    assert data["findings"][0]["decision"]=="REFERENCE"
    assert data["certified_donor"] is False
