#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import controlled_event_v54g as pilot  # noqa: E402

CONFIG = ROOT / "integration" / "orchestration" / "v55-pilot.json"

def main() -> int:
    config = pilot.load_config(CONFIG)
    assert config["rollout"] == "MULTI_PROJECT_PILOT_SET"
    assert config["max_live_operations_per_event"] == 1
    targets = {t["repository"]: t for t in config["pilot_targets"]}
    assert set(targets) == {
        "riccardopinato/AppLab",
        "riccardopinato/CamperBoss",
        "riccardopinato/TrailPath",
    }
    assert targets["riccardopinato/CamperBoss"]["analysis_mode"] == "fast"
    assert targets["riccardopinato/TrailPath"]["analysis_mode"] == "fast"

    watchlist = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    watched = {(x.get("repository"), x.get("ref")) for x in watchlist["repositories"] if x.get("enabled")}
    for repository in targets:
        assert (repository, "main") in watched

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for index, target in enumerate(config["pilot_targets"], start=1):
            report = pilot.admit(
                db_path=root / f"{index}.sqlite3",
                config_path=CONFIG,
                repository=target["repository"],
                source_ref=target["source_ref"],
                resolved_sha=str(index) * 40,
                applab_sha="a" * 40,
                delivery_id=f"pilot-{index}",
                live_requested=True,
                now_ts=1000.0 + index,
            )
            assert report["admitted"] is True
            assert report["dispatch"] is True
            assert report["executor"] == "GITHUB_ACTIONS"
            assert report["certification_authority_changed"] is False

        rejected = pilot.admit(
            db_path=root / "rejected.sqlite3",
            config_path=CONFIG,
            repository="riccardopinato/not-allowlisted",
            source_ref="refs/heads/main",
            resolved_sha="f" * 40,
            applab_sha="a" * 40,
            delivery_id="rejected",
            live_requested=True,
        )
        assert rejected["admitted"] is False
        assert rejected["dispatch"] is False

    workflow = (ROOT / ".github" / "workflows" / "multi-project-event-pilot.yml").read_text(encoding="utf-8")
    assert "repository_dispatch:" in workflow
    assert "uses: ./.github/workflows/universal-project-runner.yml" in workflow
    assert "publish_release_artifact: false" in workflow
    assert "analysis_mode: fast" in workflow
    assert "cancel-in-progress: false" in workflow
    repository_selector = "github.event.client_payload.repository || inputs.target_repository || github.repository"
    assert workflow.count(repository_selector) >= 4
    assert "restore-keys:" in workflow
    assert "certification" not in workflow.lower()
    print("AppLab v5.5A Multi-Project Pilot contract test PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
