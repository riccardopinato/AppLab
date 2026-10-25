#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import conductor_shadow_v54d as shadow  # noqa: E402


def main() -> int:
    workflow = shadow.load_workflow()
    assert workflow["schemaVersion"] == 2
    assert workflow["restartable"] is True
    assert [task["taskReferenceName"] for task in workflow["tasks"]] == list(shadow.PHASES)
    assert all(task.get("retryCount") == 0 for task in workflow["tasks"])

    event, plan, actual, inventory = shadow._fixture()

    raw_plan = {
        "schema_version": 2,
        "planner_version": "1.1.0",
        "repository": event["repository"],
        "head_sha": event["resolved_sha"],
        "mode": "full",
        "lane": "FULL_RUNTIME",
        "selected_labs": {
            "system": True,
            "performance": False,
            "network": False,
            "persistence": True,
            "configuration": False,
            "resource_pressure": False,
            "background": False,
            "storage": False,
            "upgrade": False,
        },
        "changed_files": ["lib/main.dart"],
    }
    normalized = shadow.normalize_authoritative_plan(raw_plan, event)
    assert normalized["resolved_sha"] == event["resolved_sha"]
    assert normalized["analysis_mode"] == "full"
    assert normalized["required_labs"] == ["persistence", "system"]
    assert normalized["plan_digest_sha256"].startswith("sha256:")

    raw_actual = dict(actual, executed_labs=["system", "persistence"])
    raw_result = shadow.execute_shadow(event, raw_plan, raw_actual, inventory)
    assert raw_result["comparison"]["required_labs_all_executed"] is True

    baseline = shadow.execute_shadow(event, plan, actual, inventory)
    assert baseline["authority"] == "NONE_SHADOW_ONLY"
    assert baseline["mode"] == "SHADOW_NO_DISPATCH"
    assert baseline["dispatch"] is False
    assert baseline["verdict_authority"] is False
    assert baseline["conductor_reference_sha"] == shadow.REFERENCE_SHA

    # Restart/recovery from every non-terminal shadow phase must be deterministic.
    for stop in range(1, len(shadow.PHASES)):
        cp = shadow.execute_shadow(event, plan, actual, inventory, stop_after_phase=stop)
        assert cp["authority"] == "NONE_SHADOW_ONLY"
        assert cp["next_phase_index"] == stop
        resumed = shadow.execute_shadow(event, plan, actual, inventory, resume_from=cp)
        assert resumed == baseline

    tampered = shadow.execute_shadow(
        event,
        plan,
        dict(actual, analysis_mode="fast"),
        inventory,
    )
    assert tampered["comparison"]["analysis_mode_match"] is False
    assert tampered["promotion_ready_for_dispatch"] is False

    missing_lab = shadow.execute_shadow(
        event,
        plan,
        dict(actual, executed_labs=["system", "visual"]),
        inventory,
    )
    assert missing_lab["comparison"]["required_labs_all_executed"] is False
    assert missing_lab["promotion_ready_for_dispatch"] is False

    warm_inventory = [{
        "worker_id": "warm-1",
        "worker_class": "WARM_TRUSTED_ANDROID",
        "state": "AVAILABLE",
        "applab_sha": actual["applab_sha"],
        "runtime_profiles": ["android-default"],
    }]
    modeled = shadow.execute_shadow(
        event,
        plan,
        dict(actual, worker_class="WARM_TRUSTED_ANDROID"),
        warm_inventory,
    )
    assert modeled["worker_model"]["worker_model"] == "WARM_TRUSTED_ANDROID"
    assert modeled["comparison"]["worker_model_match"] is True

    wrong_checkpoint = shadow.execute_shadow(event, plan, actual, inventory, stop_after_phase=2)

    tampered_checkpoint = {
        **wrong_checkpoint,
        "partial": {
            **wrong_checkpoint["partial"],
            "plan": {
                **wrong_checkpoint["partial"]["plan"],
                "required_labs": ["system"],
            },
        },
    }
    try:
        shadow.execute_shadow(
            event, plan, actual, inventory, resume_from=tampered_checkpoint
        )
    except shadow.ShadowError as exc:
        assert "partial state mismatch" in str(exc)
    else:
        raise AssertionError("tampered checkpoint partial state was accepted")

    changed_plan = dict(plan, plan_digest_sha256="sha256:" + ("9" * 64))
    try:
        shadow.execute_shadow(event, changed_plan, actual, inventory, resume_from=wrong_checkpoint)
    except shadow.ShadowError as exc:
        assert "digest mismatch" in str(exc)
    else:
        raise AssertionError("checkpoint accepted changed inputs")

    source = (ROOT / "scripts" / "conductor_shadow_v54d.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "subprocess.",
        "workflow_dispatch",
        "repository_dispatch",
        "GITHUB_TOKEN",
        "CONDUCTOR_AUTH",
    ):
        assert forbidden not in source, forbidden

    shadow.self_test()
    print("AppLab v5.4D Conductor Shadow contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
