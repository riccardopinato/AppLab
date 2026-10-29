#!/usr/bin/env python3
"""Real event metadata is observation, not autonomous repair certification."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from v62_background_proof import summarize, markdown, ProofObserverError


def test_observation_does_not_mint_proof() -> None:
    sha = "a" * 40
    live = {"id": 123, "name": "Controlled Event-Driven Pilot", "event": "push",
            "head_branch": "main", "head_sha": sha,
            "status": "completed", "conclusion": "success"}
    bad = {**live, "id": 124, "conclusion": "failure"}
    ignore = {**live, "id": 125, "event": "pull_request"}
    artifact = {"name": "applab-v62a-local-repair-123", "workflow_run": {"id": 123},
                "expired": False}
    report = summarize({"workflow_runs": [live, bad, ignore]},
                       {"artifacts": [artifact]})
    assert report["observed_self_canary_runs"] == 2
    assert report["verify_only_or_other_success_runs"] == 1
    assert report["failed_or_cancelled_runs"] == 1
    assert report["repair_artifact_metadata_observed"] == 1
    assert report["complete_causal_repairs_certified_here"] == 0
    assert report["real_repair_gate"] == "BACKGROUND_PROOF_PENDING"
    assert report["promotion_authorized"] is False
    assert "0/3" in markdown(report)
    with_wrong_lineage = summarize(
        {"workflow_runs": [live]},
        {"artifacts": [{**artifact, "workflow_run": {"id": 200}}]})
    assert with_wrong_lineage["repair_artifact_metadata_observed"] == 0
    for payload in ({"workflow_runs": None}, {"workflow_runs": [42]}):
        try:
            summarize(payload, {"artifacts": []})
        except ProofObserverError:
            pass
        else:
            raise AssertionError("invalid input became a false clean report")
    try:
        summarize({"workflow_runs": [live]}, {"artifacts": []},
                  active_stage="ALL_COMPATIBLE")
    except ProofObserverError:
        pass
    else:
        raise AssertionError("unapproved stage accepted")


if __name__ == "__main__":
    test_observation_does_not_mint_proof()
    print("v6.2 background proof observer fixture PASS; no false promotion")
