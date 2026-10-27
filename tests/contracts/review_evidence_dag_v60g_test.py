#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import review_evidence_dag_v60g as dag  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        applab = root / "applab"
        evidence = root / "evidence"
        trusted = root / "trusted"
        target = root / "target"
        cache = root / "cache"
        for path in (applab / "scripts", evidence, trusted, target):
            path.mkdir(parents=True, exist_ok=True)

        for script in dag.PRODUCER_SCRIPTS.values():
            (applab / "scripts" / script).write_text(
                f"# {script}\n",
                encoding="utf-8",
            )
        (evidence / "evidence-graph.json").write_text(
            json.dumps({"graph": "fixture"}),
            encoding="utf-8",
        )
        (trusted / "analysis-plan.json").write_text(
            json.dumps({"lane": "FAST_RUNTIME"}),
            encoding="utf-8",
        )
        (target / "market-evidence.json").write_text(
            json.dumps({"observed_at": "2026-10-27"}),
            encoding="utf-8",
        )

        first = dag.plan(
            applab_root=applab,
            evidence_dir=evidence,
            trusted_runtime_dir=trusted,
            target_root=target,
            repository="owner/app",
            resolved_sha="a" * 40,
            applab_sha="b" * 40,
            max_files=3500,
            market_evidence_path="market-evidence.json",
        )
        second = dag.plan(
            applab_root=applab,
            evidence_dir=evidence,
            trusted_runtime_dir=trusted,
            target_root=target,
            repository="owner/app",
            resolved_sha="a" * 40,
            applab_sha="b" * 40,
            max_files=3500,
            market_evidence_path="market-evidence.json",
        )
        assert first == second
        assert first["cache_key"].startswith("applab-review-fanout-v60g-")
        assert len(first["nodes"]) == 4
        assert first["layers"][1] == [
            "competitive",
            "planner_feedback",
            "simulated_human",
        ]
        assert first["layers"][2] == ["design_advisor"]

        changed_sha = dag.plan(
            applab_root=applab,
            evidence_dir=evidence,
            trusted_runtime_dir=trusted,
            target_root=target,
            repository="owner/app",
            resolved_sha="a" * 40,
            applab_sha="c" * 40,
            max_files=3500,
            market_evidence_path="market-evidence.json",
        )
        assert changed_sha["fingerprint_sha256"] != first["fingerprint_sha256"]

        (evidence / "evidence-graph.json").write_text(
            json.dumps({"graph": "changed"}),
            encoding="utf-8",
        )
        changed_graph = dag.plan(
            applab_root=applab,
            evidence_dir=evidence,
            trusted_runtime_dir=trusted,
            target_root=target,
            repository="owner/app",
            resolved_sha="a" * 40,
            applab_sha="b" * 40,
            max_files=3500,
            market_evidence_path="market-evidence.json",
        )
        assert changed_graph["fingerprint_sha256"] != first["fingerprint_sha256"]

        # Cache is complete only when every declared node output is present.
        for outputs in dag.NODE_OUTPUTS.values():
            for name in outputs:
                (evidence / name).write_text(name, encoding="utf-8")
        dag.cache_outputs(evidence, cache)
        restored = root / "restored"
        dag.restore_outputs(cache, restored)
        for outputs in dag.NODE_OUTPUTS.values():
            for name in outputs:
                assert (restored / name).read_text(encoding="utf-8") == name

        missing = cache / "planner-feedback.json"
        missing.unlink()
        try:
            dag.restore_outputs(cache, root / "incomplete")
        except dag.FanoutError as exc:
            assert "cache is incomplete" in str(exc)
        else:
            raise AssertionError("incomplete review cache unexpectedly restored")

    workflow = (
        ROOT / ".github" / "workflows" / "autonomous-app-review-v31.yml"
    ).read_text(encoding="utf-8")
    for required in (
        "Plan v6.0G content-addressed review fan-out",
        "Restore exact review fan-out cache",
        "Run v6.0G parallel review evidence fan-out",
        "Save exact review fan-out cache",
        "review_evidence_dag_v60g.py",
        "steps.review_dag.outputs.cache_key",
        "--applab-sha",
        "Persist graph-aware planner feedback",
    ):
        assert required in workflow, required

    dag.self_test()
    print("AppLab v6.0G review evidence DAG contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
