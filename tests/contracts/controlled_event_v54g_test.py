#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import controlled_event_v54g as pilot  # noqa: E402


def main() -> int:
    contract = pilot.load_contract()
    config = pilot.load_config()

    assert contract["mode"] == "CONTROLLED_LIVE_PILOT"
    assert contract["authority"] == "ORCHESTRATION_ONLY"
    assert contract["certification_authority_changed"] is False
    assert contract["watchdog"] == "HOURLY_REPO_WATCHER"

    assert config["enabled"] is True
    assert config["kill_switch"] is False
    assert config["rollout"] == "SELF_REPO_MAIN_CANARY"
    assert config["max_live_operations_per_event"] == 1
    assert len(config["pilot_targets"]) == 1

    target = config["pilot_targets"][0]
    assert target["repository"] == "riccardopinato/AppLab"
    assert target["source_ref"] == "refs/heads/main"
    assert target["analysis_mode"] == "fast"
    assert target["engine"] == "native_android"
    assert target["working_directory"] == "selftest"
    assert target["run_maestro"] is False

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # PR-equivalent dry-run: admitted and persisted, never dispatched.
        dry = pilot.admit(
            db_path=root / "dry.sqlite3",
            config_path=pilot.DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="1" * 40,
            applab_sha="2" * 40,
            delivery_id="dry-run",
            live_requested=False,
        )
        assert dry["admitted"] is True
        assert dry["live"] is False
        assert dry["dispatch"] is False
        assert dry["queue_state"] == "QUEUED"
        assert dry["certification_authority_changed"] is False

        # Real canary admission claims exactly one GitHub Actions executor intent.
        db = root / "live.sqlite3"
        live = pilot.admit(
            db_path=db,
            config_path=pilot.DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="3" * 40,
            applab_sha="4" * 40,
            delivery_id="live-run-1",
            live_requested=True,
        )
        assert live["admitted"] is True
        assert live["live"] is True
        assert live["dispatch"] is True
        assert live["executor"] == "GITHUB_ACTIONS"
        assert live["watchdog"] == "HOURLY_REPO_WATCHER"
        assert live["integrity"]["ok"] is True

        final = pilot.finalize(
            db_path=db,
            operation_id=live["operation_id"],
            worker_id=live["worker_id"],
            job_result="success",
        )
        assert final["operation_terminal_state"] == "SUCCEEDED"
        assert final["queue_state"] == "DONE"
        assert final["watchdog_required"] is False

        # Same logical target and same AppLab identity dedupes after completion.
        duplicate = pilot.admit(
            db_path=db,
            config_path=pilot.DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="3" * 40,
            applab_sha="4" * 40,
            delivery_id="live-run-2",
            live_requested=True,
        )
        assert duplicate["event_persistence"] == "DEDUPED"
        assert duplicate["operation_id"] == live["operation_id"]
        assert duplicate["dispatch"] is False

        # Same target under a new AppLab revision is a distinct orchestration identity.
        upgraded = pilot.admit(
            db_path=db,
            config_path=pilot.DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="3" * 40,
            applab_sha="5" * 40,
            delivery_id="live-run-3",
            live_requested=True,
        )
        assert upgraded["operation_id"] != live["operation_id"]

        # Failure is fail-closed and explicitly delegates future recovery to watchdog.
        fail_db = root / "failure.sqlite3"
        failing = pilot.admit(
            db_path=fail_db,
            config_path=pilot.DEFAULT_CONFIG,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="6" * 40,
            applab_sha="7" * 40,
            delivery_id="failure-run",
            live_requested=True,
        )
        failed = pilot.finalize(
            db_path=fail_db,
            operation_id=failing["operation_id"],
            worker_id=failing["worker_id"],
            job_result="failure",
        )
        assert failed["operation_terminal_state"] == "FAILED"
        assert failed["queue_state"] == "BLOCKED"
        assert failed["watchdog_required"] is True
        assert failed["certification_authority_changed"] is False

        # Kill switch overrides a live request without dropping Event/Operation evidence.
        disabled_config = json.loads(pilot.DEFAULT_CONFIG.read_text(encoding="utf-8"))
        disabled_config["kill_switch"] = True
        disabled_path = root / "disabled.json"
        disabled_path.write_text(
            json.dumps(disabled_config, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        killed = pilot.admit(
            db_path=root / "killed.sqlite3",
            config_path=disabled_path,
            repository=target["repository"],
            source_ref=target["source_ref"],
            resolved_sha="8" * 40,
            applab_sha="9" * 40,
            delivery_id="killed-run",
            live_requested=True,
        )
        assert killed["admitted"] is True
        assert killed["live"] is False
        assert killed["dispatch"] is False

        # Non-allowlisted repositories can never enter the live path.
        rejected = pilot.admit(
            db_path=root / "reject.sqlite3",
            config_path=pilot.DEFAULT_CONFIG,
            repository="owner/not-allowlisted",
            source_ref="refs/heads/main",
            resolved_sha="a" * 40,
            applab_sha="b" * 40,
            delivery_id="reject-run",
            live_requested=True,
        )
        assert rejected["admitted"] is False
        assert rejected["dispatch"] is False

    workflow = (
        ROOT / ".github" / "workflows" / "controlled-event-pilot.yml"
    ).read_text(encoding="utf-8")
    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "uses: ./.github/workflows/external-native-android-runner.yml" in workflow
    assert "analysis_mode: fast" in workflow
    assert "publish_release_artifact" not in workflow
    assert "certification" not in workflow.lower()
    assert "applab-v54g-ledger-" in workflow
    assert "HOURLY_REPO_WATCHER" in workflow

    watcher = (
        ROOT / ".github" / "workflows" / "repo-watcher.yml"
    ).read_text(encoding="utf-8")
    assert "17 * * * *" in watcher
    assert "schedule:" in watcher

    source = (ROOT / "scripts" / "controlled_event_v54g.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib.request",
        "socket.",
        "subprocess.",
        "CERTIFIED",
    ):
        assert forbidden not in source, forbidden

    pilot.self_test()
    print("AppLab v5.4G Controlled Event-Driven Pilot contract test PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
