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
        "journey-shard-${{ github.run_id }}-coordinator",
    ):
        require(needle in workflow, f"v5.9C trusted workflow missing: {needle}")

    require(
        '"riccardopinato/Agenda-per-Anna"' in admission
        and '"mode": "shadow"' in admission,
        "v5.9C Anna pilot must remain shadow until explicit promotion",
    )
