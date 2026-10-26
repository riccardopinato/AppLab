#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def run_check(namespace: dict[str, Any]) -> None:
    root = namespace["ROOT"]
    require = namespace["require"]
    planner = (root / "scripts/journey_sharding.py").read_text(encoding="utf-8")
    shard_runtime = (root / "scripts/journey_shard_runtime.py").read_text(encoding="utf-8")
    aggregate = (root / "scripts/journey_shard_aggregate.py").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/trusted-apk-verifier.yml").read_text(encoding="utf-8")
    admission = (root / "config/journey-sharding-pilots.json").read_text(encoding="utf-8")
    shard_shell = (root / "scripts/run_journey_shard.sh").read_text(encoding="utf-8")

    for needle in (
        'ENGINE_VERSION = "5.9C"',
        '"coverage_union_verified": True',
        '"exact_artifact_verified": True',
    ):
        require(
            needle in planner or needle in shard_runtime or needle in aggregate,
            f"v5.9C sharding invariant missing: {needle}",
        )

    for needle in (
        "journey_plan:",
        "journey_shards:",
        "journey_aggregate:",
        "fromJSON(needs.journey_plan.outputs.matrix)",
        "Finalize journey sharding admission",
        "journey_sharding_admission.py",
        "journey-shard-${{ github.run_id }}-coordinator",
        "Finalize authoritative canonical evidence",
        "Publish authoritative canonical evidence",
        "Enforce authoritative aggregate verdict",
    ):
        require(needle in workflow, f"v5.9C trusted workflow missing: {needle}")

    require(
        "path: .applab-visual-baseline" in workflow
        and "path: .applab-upgrade-baseline" in workflow,
        "v5.9C admission must restore canonical runtime baseline cache paths",
    )
    require(
        'cp "$BUILD_CONTRACT_JSON" "$REPORT_DIR/contract.json"' in shard_shell
        and shard_shell.index('cp "$BUILD_CONTRACT_JSON" "$REPORT_DIR/contract.json"')
        < shard_shell.index('journey_shard_runtime.py'),
        "v5.9C shard evidence must preserve exact contract before journey execution",
    )
    require(
        '"riccardopinato/Agenda-per-Anna"' in admission
        and '"mode": "shadow"' in admission,
        "v5.9C Anna pilot must remain shadow until explicit promotion",
    )
