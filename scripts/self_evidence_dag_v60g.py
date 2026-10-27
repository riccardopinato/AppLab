#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

NODE_OUTPUTS = {
    "experiment": ["experiment-plan.json", "experiment-plan.md"],
    "analyst": ["analyst-report.json", "analyst-report.md"],
    "evidence_graph": ["evidence-graph.json", "evidence-graph.md"],
    "planner_feedback": ["planner-feedback.json", "planner-feedback.md"],
    "simulated_human": ["simulated-human-qa.json", "simulated-human-qa.md"],
    "design_advisor": ["design-system-advisor.json", "design-system-advisor.md"],
    "competitive": ["competitive-product-intelligence.json", "competitive-product-intelligence.md"],
    "release_assurance": ["release-assurance.json", "release-assurance.md"],
    "review_council": ["virtual-product-review-council.json", "virtual-product-review-council.md"],
}
DEPENDENCIES = {
    "experiment": [],
    "analyst": ["experiment"],
    "simulated_human": [],
    "design_advisor": [],
    "competitive": [],
    "evidence_graph": ["experiment", "analyst", "simulated_human", "design_advisor", "competitive"],
    "planner_feedback": ["evidence_graph"],
    "release_assurance": ["evidence_graph"],
    "review_council": ["evidence_graph", "release_assurance"],
}


class DagError(ValueError):
    pass


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_inputs(root: Path, excluded: set[str]) -> list[dict[str, Any]]:
    rows = []
    if not root.is_dir():
        return rows
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel in excluded:
            continue
        rows.append({"path": rel, "sha256": _hash_file(path), "size": path.stat().st_size})
    return rows


def node_fingerprint(
    node: str,
    evidence_dir: Path,
    trusted_dir: Path,
    target_dir: Path,
    dependency_records: dict[str, Any],
) -> dict[str, Any]:
    if node not in NODE_OUTPUTS:
        raise DagError(f"unknown evidence DAG node: {node}")
    excluded = set(NODE_OUTPUTS[node])
    payload = {
        "schema_version": 1,
        "node": node,
        "evidence_inputs": _tree_inputs(evidence_dir, excluded),
        "trusted_inputs": _tree_inputs(trusted_dir, set()),
        "target_inputs": _tree_inputs(target_dir, set()),
        "dependencies": {
            dep: dependency_records.get(dep, {}).get("output_digest_sha256", "")
            for dep in DEPENDENCIES[node]
        },
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        **payload,
        "fingerprint_sha256": hashlib.sha256(rendered).hexdigest(),
    }


def output_digest(node: str, evidence_dir: Path) -> str:
    rows = []
    for name in NODE_OUTPUTS[node]:
        path = evidence_dir / name
        if not path.is_file():
            raise DagError(f"missing node output: {name}")
        rows.append({"path": name, "sha256": _hash_file(path), "size": path.stat().st_size})
    rendered = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def cache_dir(cache_root: Path, node: str, fingerprint: str) -> Path:
    return cache_root / node / fingerprint


def restore_node(node: str, fingerprint: str, cache_root: Path, evidence_dir: Path) -> bool:
    source = cache_dir(cache_root, node, fingerprint)
    manifest = source / "manifest.json"
    if not manifest.is_file():
        return False
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if payload.get("fingerprint_sha256") != fingerprint or payload.get("node") != node:
        return False
    for name in NODE_OUTPUTS[node]:
        cached = source / name
        if not cached.is_file():
            return False
        expected = str((payload.get("outputs") or {}).get(name, ""))
        if _hash_file(cached) != expected:
            return False
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for name in NODE_OUTPUTS[node]:
        (evidence_dir / name).write_bytes((source / name).read_bytes())
    return True


def save_node(node: str, fingerprint: str, cache_root: Path, evidence_dir: Path) -> dict[str, Any]:
    destination = cache_dir(cache_root, node, fingerprint)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for name in NODE_OUTPUTS[node]:
        source = evidence_dir / name
        if not source.is_file():
            raise DagError(f"cannot cache missing node output: {name}")
        data = source.read_bytes()
        (destination / name).write_bytes(data)
        outputs[name] = hashlib.sha256(data).hexdigest()
    manifest = {
        "schema_version": 1,
        "node": node,
        "fingerprint_sha256": fingerprint,
        "outputs": outputs,
        "output_digest_sha256": output_digest(node, evidence_dir),
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def plan_all(
    evidence_dir: Path,
    trusted_dir: Path,
    target_dir: Path,
    cache_root: Path,
) -> dict[str, Any]:
    records: dict[str, Any] = {}
    order = [
        "experiment", "analyst", "simulated_human", "design_advisor", "competitive",
        "evidence_graph", "planner_feedback", "release_assurance", "review_council",
    ]
    for node in order:
        fp = node_fingerprint(node, evidence_dir, trusted_dir, target_dir, records)
        cached = cache_dir(cache_root, node, fp["fingerprint_sha256"]) / "manifest.json"
        records[node] = {
            "fingerprint_sha256": fp["fingerprint_sha256"],
            "cache_hit": cached.is_file(),
            "dependencies": DEPENDENCIES[node],
            "outputs": NODE_OUTPUTS[node],
        }
    return {
        "schema_version": 1,
        "record_type": "SELF_EVIDENCE_DAG_PLAN_V60G",
        "authority": "ADVISORY_EVIDENCE_EXECUTION_ONLY",
        "nodes": records,
        "cross_input_reuse": False,
        "verification_authority": "UNCHANGED",
    }


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        evidence = root / "evidence"
        trusted = root / "trusted"
        target = root / "target"
        cache = root / "cache"
        for directory in (evidence, trusted, target):
            directory.mkdir()
        (evidence / "autonomous-review.json").write_text('{"ok":true}\n', encoding="utf-8")
        (trusted / "result.json").write_text('{"result":"PASS"}\n', encoding="utf-8")
        (target / "app.py").write_text("print('x')\n", encoding="utf-8")

        fp = node_fingerprint("experiment", evidence, trusted, target, {})
        assert restore_node("experiment", fp["fingerprint_sha256"], cache, evidence) is False
        (evidence / "experiment-plan.json").write_text('{"plan":1}\n', encoding="utf-8")
        (evidence / "experiment-plan.md").write_text("# plan\n", encoding="utf-8")
        manifest = save_node("experiment", fp["fingerprint_sha256"], cache, evidence)
        assert manifest["output_digest_sha256"]
        (evidence / "experiment-plan.json").unlink()
        (evidence / "experiment-plan.md").unlink()
        assert restore_node("experiment", fp["fingerprint_sha256"], cache, evidence) is True
        assert (evidence / "experiment-plan.json").is_file()

        before = fp["fingerprint_sha256"]
        (target / "app.py").write_text("print('y')\n", encoding="utf-8")
        after = node_fingerprint("experiment", evidence, trusted, target, {})["fingerprint_sha256"]
        assert before != after

        plan = plan_all(evidence, trusted, target, cache)
        assert plan["cross_input_reuse"] is False
        assert set(plan["nodes"]) == set(NODE_OUTPUTS)
    print("AppLab v6.0G Evidence DAG self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", default="")
    parser.add_argument("--trusted-dir", default="")
    parser.add_argument("--target-dir", default="")
    parser.add_argument("--cache-root", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.evidence_dir, args.trusted_dir, args.target_dir, args.cache_root)):
        raise SystemExit("--evidence-dir, --trusted-dir, --target-dir and --cache-root are required")
    report = plan_all(
        Path(args.evidence_dir), Path(args.trusted_dir), Path(args.target_dir), Path(args.cache_root)
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
