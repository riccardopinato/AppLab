#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import controlled_closed_loop_expansion_v61d as expansion  # noqa: E402


def clean_row(success: int = 3) -> dict[str, int]:
    return {
        "successful_closed_loop_operations": success,
        "failed_closed_loop_operations": 0,
        "authority_breaches": 0,
        "false_repairs": 0,
        "recovery_failures": 0,
        "exact_identity_violations": 0,
    }


def main() -> int:
    contract = expansion.load_contract()
    policy = expansion.load_policy(contract=contract)
    proof = expansion.self_test()

    assert contract["promotion_order"] == ["SELF_CANARY", "PILOT_3", "PILOT_5"]
    assert "ALL_COMPATIBLE" not in contract["promotion_order"]
    assert set(policy["stages"]) == {"SELF_CANARY", "PILOT_3", "PILOT_5"}
    assert policy["active_stage"] == "SELF_CANARY"
    assert policy["promotion"]["automatic"] is False
    assert policy["promotion"]["v55_evidence_can_grant_mutation_authority"] is False

    assert proof["status"] == "PASS"
    assert proof["all_compatible_pre_authorized"] is False
    assert proof["promotion_requires_v61_closed_loop_evidence"] is True
    assert proof["promotion_is_explicit_not_automatic"] is True
    assert proof["pilot3_materialization_proven"] is True
    assert proof["downstream_bounded_mutation_admission_proven"] is True
    assert proof["high_risk_investigation_only"] is True
    assert proof["remote_dispatch_created"] is False
    assert proof["release_authority"] == "DENIED"

    self_evidence = {"riccardopinato/AppLab": clean_row()}
    self_decision = expansion.promotion_decision(
        policy=policy,
        evidence=self_evidence,
    )
    assert self_decision["decision"] == "ELIGIBLE_FOR_EXPLICIT_PROMOTION"
    assert self_decision["next_stage"] == "PILOT_3"
    assert self_decision["policy_changed"] is False

    pilot3 = json.loads(json.dumps(policy))
    pilot3["active_stage"] = "PILOT_3"
    pilot3_evidence = {
        repository: clean_row()
        for repository in pilot3["stages"]["PILOT_3"]
    }
    pilot3_decision = expansion.promotion_decision(
        policy=pilot3,
        evidence=pilot3_evidence,
    )
    assert pilot3_decision["decision"] == "ELIGIBLE_FOR_EXPLICIT_PROMOTION"
    assert pilot3_decision["next_stage"] == "PILOT_5"
    assert pilot3_decision["automatic"] is False

    broken = json.loads(json.dumps(pilot3_evidence))
    broken["riccardopinato/CamperBoss"]["false_repairs"] = 1
    held = expansion.promotion_decision(policy=pilot3, evidence=broken)
    assert held["decision"] == "HOLD"
    assert "riccardopinato/CamperBoss:FALSE_REPAIR" in held["blockers"]

    pilot5 = json.loads(json.dumps(policy))
    pilot5["active_stage"] = "PILOT_5"
    final = expansion.promotion_decision(
        policy=pilot5,
        evidence={
            repository: clean_row()
            for repository in pilot5["stages"]["PILOT_5"]
        },
    )
    assert final["decision"] == "HOLD"
    assert final["reason"] == "MAX_V61D_STAGE"
    assert final["next_stage"] == "PILOT_5"

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        global_killed = json.loads(json.dumps(policy))
        global_killed["global_kill_switch"] = True
        killed_path = root / "global-killed.json"
        killed_path.write_text(
            json.dumps(global_killed, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        denied = expansion.admit_closed_loop(
            db_path=root / "global-killed.sqlite3",
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha="a" * 40,
            applab_sha="a" * 40,
            delivery_id="v61d-global-killed",
            policy_path=killed_path,
            now_ts=200.0,
        )
        assert denied["admitted"] is False
        assert denied["reason"] == "GLOBAL_KILL_SWITCH"

        mismatch = expansion.admit_closed_loop(
            db_path=root / "self-mismatch.sqlite3",
            repository="riccardopinato/AppLab",
            source_ref="refs/heads/main",
            resolved_sha="a" * 40,
            applab_sha="b" * 40,
            delivery_id="v61d-self-mismatch",
            now_ts=201.0,
        )
        assert mismatch["admitted"] is False
        assert mismatch["reason"] == "SELF_IDENTITY_MISMATCH"

        pilot3_path = root / "pilot3.json"
        pilot3_path.write_text(
            json.dumps(pilot3, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        killed_repo_policy = json.loads(json.dumps(pilot3))
        killed_repo_policy["repository_kill_switches"][
            "riccardopinato/CamperBoss"
        ] = True
        materialized = expansion.materialize_event_config(killed_repo_policy)
        assert [
            item["repository"] for item in materialized["pilot_targets"]
        ] == ["riccardopinato/AppLab", "riccardopinato/TrailPath"]

        applab_sha = "1" * 40
        target_sha = "2" * 40
        revoked_db = root / "revoked.sqlite3"
        first = expansion.admit_closed_loop(
            db_path=revoked_db,
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha=target_sha,
            applab_sha=applab_sha,
            delivery_id="v61d-policy-revoke",
            policy_path=pilot3_path,
            now_ts=202.0,
        )
        assert first["mutation_authorized"] is True
        assert first["budget_state"] in {"ACTIVE", "EXHAUSTED"}

        revoked_policy = json.loads(json.dumps(pilot3))
        revoked_policy["closed_loop"]["mutation_enabled"] = False
        revoked_policy["closed_loop"]["draft_pr_enabled"] = False
        revoked_path = root / "revoked-policy.json"
        revoked_path.write_text(
            json.dumps(revoked_policy, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        revoked = expansion.admit_closed_loop(
            db_path=revoked_db,
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha=target_sha,
            applab_sha=applab_sha,
            delivery_id="v61d-policy-revoke",
            policy_path=revoked_path,
            now_ts=203.0,
        )
        assert revoked["reason"] == "POLICY_REVOKED_STOPPED"
        assert revoked["work_item_state"] == "STOPPED"
        assert revoked["budget_state"] == "TERMINAL_NO_NEW_BUDGET_ACTIVITY"

        terminal_replay = expansion.admit_closed_loop(
            db_path=revoked_db,
            repository="riccardopinato/CamperBoss",
            source_ref="refs/heads/main",
            resolved_sha=target_sha,
            applab_sha=applab_sha,
            delivery_id="v61d-policy-revoke",
            policy_path=revoked_path,
            now_ts=204.0,
        )
        assert terminal_replay["reason"] == "TERMINAL_REUSE_PRESERVED"
        assert terminal_replay["budget_state"] == "TERMINAL_NO_NEW_BUDGET_ACTIVITY"

        original_watchlist = expansion.legacy_expansion.WATCHLIST
        watchlist = json.loads(original_watchlist.read_text(encoding="utf-8"))
        for item in watchlist["repositories"]:
            if item.get("repository") == "riccardopinato/Notes-Ecosistema":
                item["enabled"] = False
        isolated_path = root / "watchlist-isolated.json"
        isolated_path.write_text(
            json.dumps(watchlist, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            expansion.legacy_expansion.WATCHLIST = isolated_path
            isolated = expansion.materialize_event_config(policy)
        finally:
            expansion.legacy_expansion.WATCHLIST = original_watchlist
        assert [item["repository"] for item in isolated["pilot_targets"]] == [
            "riccardopinato/AppLab"
        ]

    source = (
        ROOT / "scripts" / "controlled_closed_loop_expansion_v61d.py"
    ).read_text(encoding="utf-8")
    assert "live_requested=False" in source
    assert "ALL_COMPATIBLE" not in expansion.STAGES
    assert "time.sleep(" not in source
    assert "execute_remote(" not in source
    assert "SELF_MERGE" in contract["mandatory_denials"]

    print("AppLab v6.1D controlled expansion contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
