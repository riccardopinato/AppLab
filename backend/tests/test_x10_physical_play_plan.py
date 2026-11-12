"""X10-032 physical test planning; does not pretend device execution."""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts" / "x10_physical_play_plan.py"
spec = importlib.util.spec_from_file_location("x10_physical_play_plan", path)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)

SHA = "a" * 40
APK = "b" * 64
CERT = "c" * 64
CONTRACT = {
    "repository": "example/app", "source_sha": SHA, "apk_sha256": APK,
    "package_id": "com.example.app", "version_code": 12,
    "previous_version_code": 11, "signing_cert_sha256": CERT,
    "capabilities": ["notifications", "gps", "play_delivery"],
    "release_workflow_url": "https://github.com/example/app/actions/runs/42",
}

def test_scenarios_stay_unverified_even_with_identifiers():
    plan = gate.create_plan(CONTRACT)
    assert plan["authority"] == "PLAN_ONLY"
    assert plan["scenario_count"] >= 7
    assert plan["actual_device_connected"] is False
    assert plan["physical_qa_complete"] is False
    assert plan["play_internal_testing_complete"] is False
    assert plan["release_authorized"] is False
    assert all(s["status"] == "NOT_VERIFIED" and s["observed_result"] is None
               for s in plan["scenarios"])

def test_is_deterministic_and_no_double_play_or_picker():
    data = copy.deepcopy(CONTRACT)
    data["capabilities"] += ["storage", "file_picker"]
    a, b = gate.create_plan(data), gate.create_plan(data)
    assert a["plan_digest"] == b["plan_digest"]
    ids = [s["scenario_id"] for s in a["scenarios"]]
    assert len(ids) == len(set(ids))

def test_stale_upgrade_or_identity_mismatch_is_refused():
    for changed in (
        {"previous_version_code": 12},
        {"version_code": 10},
        {"apk_sha256": "tampered"},
        {"source_sha": "wrong"},
        {"signing_cert_sha256": ""},
    ):
        data = {**CONTRACT, **changed}
        with pytest.raises(gate.PhysicalPlanError):
            gate.create_plan(data)

def test_unrelated_workflow_url_is_rejected():
    data = {**CONTRACT, "release_workflow_url": "https://github.com/elsewhere/repo/actions/runs/42"}
    with pytest.raises(gate.PhysicalPlanError, match="SOURCE_WORKFLOW_RUN_URL_INVALID"):
        gate.create_plan(data)

def test_reject_unknown_device_capability_or_duplicate():
    for caps in (["unknown"], ["gps", "gps"]):
        with pytest.raises(gate.PhysicalPlanError, match="UNSUPPORTED_CAPABILITIES"):
            gate.create_plan({**CONTRACT, "capabilities": caps})

def test_no_private_receipts_or_raw_logs_in_result():
    plan = gate.create_plan(CONTRACT)
    assert "logs" not in str(plan).lower()
    assert "token" not in str(plan).lower()
