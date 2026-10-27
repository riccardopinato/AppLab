#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import closed_loop_pilot_v61a as pilot  # noqa: E402


def main() -> int:
    contract = pilot.load_contract()
    config = pilot.load_config(contract=contract)
    proof = pilot.self_test()

    assert proof["status"] == "PASS"
    assert proof["stage"] == "SELF_CANARY"
    assert proof["repository_allowlist"] == ["riccardopinato/AppLab"]
    assert proof["source_ref_allowlist"] == ["refs/heads/main"]
    assert proof["immutable_self_identity_proven"] is True
    assert proof["global_kill_switch_proven"] is True
    assert proof["normal_risk_mutation_admitted"] is True
    assert proof["high_risk_investigation_only"] is True
    assert proof["duplicate_delivery_reuses_operation_and_work_item"] is True
    assert proof["policy_revocation_stops_existing_mutable_work_item"] is True
    assert proof["operation_reuse_uses_persisted_work_item_id"] is True
    assert proof["existing_durable_substrate_reused"] is True
    assert proof["parallel_dispatcher_created"] is False
    assert proof["fixed_interval_polling_primary"] is False
    assert proof["github_actions_fallback"] is True
    assert proof["release_authority"] == "DENIED"
    assert proof["certification_authority"] == "UNCHANGED"

    denials = set(contract["mandatory_denials"])
    for required in {
        "WRITE_MAIN",
        "WRITE_FACTORY_CORE",
        "RELEASE",
        "SELF_APPROVE",
        "SELF_MERGE",
    }:
        assert required in denials

    assert len(config["pilot_targets"]) == 1
    assert config["pilot_targets"][0]["repository"] == "riccardopinato/AppLab"
    assert config["closed_loop"]["post_gate_merge_authority"] == "EXTERNAL_REPOSITORY_AUTOMATION"

    source = (ROOT / "scripts" / "closed_loop_pilot_v61a.py").read_text(encoding="utf-8")
    assert "execute_remote(" not in source
    assert "live_requested=False" in source
    assert "time.sleep(" not in source
    assert "POST_GATE_EXTERNAL_ONLY" in source

    print("AppLab v6.1A closed-loop pilot admission contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
