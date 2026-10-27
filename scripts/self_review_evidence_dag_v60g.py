#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENGINE_VERSION = "6.0G"

NODES: dict[str, dict[str, Any]] = {
    "autonomous-review": {
        "producer": "scripts/autonomous_app_review.py",
        "deps": [],
        "outputs": ["autonomous-review.json", "autonomous-review.md"],
    },
    "longitudinal": {
        "producer": "scripts/longitudinal_product_intelligence.py",
        "deps": ["autonomous-review"],
        "outputs": ["longitudinal-intelligence.json", "longitudinal-intelligence.md"],
    },
    "experiment-plan": {
        "producer": "scripts/autonomous_experiment_planner.py",
        "deps": ["autonomous-review", "longitudinal"],
        "outputs": ["experiment-plan.json", "experiment-plan.md"],
    },
    "analyst": {
        "producer": "scripts/applab_analyst.py",
        "deps": ["autonomous-review", "longitudinal"],
        "outputs": ["analyst-report.json", "analyst-report.md"],
    },
    "evidence-graph": {
        "producer": "scripts/evidence_graph.py",
        "deps": ["autonomous-review", "longitudinal", "experiment-plan", "analyst"],
        "outputs": ["evidence-graph.json", "evidence-graph.md"],
    },
    "planner-feedback": {
        "producer": "scripts/planner_feedback.py",
        "deps": ["evidence-graph"],
        "outputs": ["planner-feedback.json", "planner-feedback.md"],
    },
    "simulated-human": {
        "producer": "scripts/simulated_human_qa.py",
        "deps": ["evidence-graph"],
        "outputs": ["simulated-human-qa.json", "simulated-human-qa.md"],
    },
    "design-advisor": {
        "producer": "scripts/design_system_advisor.py",
        "deps": ["autonomous-review", "evidence-graph"],
        "outputs": ["design-system-advisor.json", "design-system-advisor.md"],
    },
    "competitive": {
        "producer": "scripts/competitive_product_intelligence.py",
        "deps": ["autonomous-review", "evidence-graph"],
        "outputs": ["competitive-product-intelligence.json", "competitive-product-intelligence.md"],
    },
    "release-assurance": {
        "producer": "scripts/release_assurance.py",
        "deps": ["evidence-graph", "planner-feedback"],
        "outputs": ["release-assurance.json", "release-assurance.md"],
    },
    "review-council": {
        "producer": "scripts/virtual_product_review_council.py",
        "deps": [
            "evidence-graph",
            "simulated-human",
            "design-advisor",
            "competitive",
            "release-assurance",
        ],
        "outputs": ["virtual-product-review-council.json", "virtual-product-review-council.md"],
    },
}


class EvidenceDagError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _file_sha(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise EvidenceDagError(f"missing DAG producer: {relative}")
    return _sha256_bytes(path.read_bytes())


def _directory_digest(root: Path | None) -> str:
    if root is None or not root.is_dir():
        return "none"
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_cache_index(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvidenceDagError("cache index must be a JSON object")
    return payload


def _valid_cache_entry(
    entry: Any,
    *,
    fingerprint: str,
    outputs: list[str],
) -> bool:
    if not isinstance(entry, dict):
        return False
    if str(entry.get("fingerprint") or "") != fingerprint:
        return False
    hashes = entry.get("outputs")
    if not isinstance(hashes, dict):
        return False
    for output in outputs:
        value = str(hashes.get(output) or "")
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            return False
    return True


def build_plan(
    *,
    applab_root: Path,
    repository: str,
    resolved_sha: str,
    trusted_evidence_fingerprint: str,
    history_root: Path | None = None,
    cross_app_fingerprint: str = "none",
    market_fingerprint: str = "none",
    max_files: int = 3500,
    cache_index_path: Path | None = None,
) -> dict[str, Any]:
    if "/" not in repository:
        raise EvidenceDagError("repository must be owner/name")
    source_sha = resolved_sha.strip().lower()
    if len(source_sha) != 40 or any(ch not in "0123456789abcdef" for ch in source_sha):
        raise EvidenceDagError("resolved_sha must be an exact lowercase SHA")
    if max_files < 1:
        raise EvidenceDagError("max_files must be positive")

    history_digest = _directory_digest(history_root)
    cache = _load_cache_index(cache_index_path)
    node_rows: list[dict[str, Any]] = []
    fingerprints: dict[str, str] = {}
    waves: dict[str, int] = {}

    for name, spec in NODES.items():
        deps = list(spec["deps"])
        wave = 0 if not deps else max(waves[dep] for dep in deps) + 1
        waves[name] = wave
        producer_sha = _file_sha(applab_root, str(spec["producer"]))
        inputs = {
            "repository": repository,
            "resolved_sha": source_sha,
            "producer": spec["producer"],
            "producer_sha256": producer_sha,
            "trusted_evidence_fingerprint": trusted_evidence_fingerprint,
            "history_digest": history_digest if name in {"longitudinal", "experiment-plan", "analyst", "evidence-graph"} else "not-applicable",
            "cross_app_fingerprint": cross_app_fingerprint if name in {"evidence-graph", "release-assurance", "review-council"} else "not-applicable",
            "market_fingerprint": market_fingerprint if name in {"competitive", "review-council"} else "not-applicable",
            "max_files": max_files if name in {"autonomous-review", "design-advisor"} else 0,
            "upstream_fingerprints": {
                dep: fingerprints[dep]
                for dep in deps
            },
        }
        fingerprint = _sha256_bytes(_canonical(inputs))
        fingerprints[name] = fingerprint
        outputs = list(spec["outputs"])
        reusable = _valid_cache_entry(
            cache.get(name),
            fingerprint=fingerprint,
            outputs=outputs,
        )
        node_rows.append(
            {
                "name": name,
                "producer": spec["producer"],
                "wave": wave,
                "dependencies": deps,
                "fingerprint": fingerprint,
                "outputs": outputs,
                "decision": "REUSE" if reusable else "RUN",
                "reusable": reusable,
            }
        )

    wave_rows: list[dict[str, Any]] = []
    for wave in sorted(set(waves.values())):
        names = [row["name"] for row in node_rows if row["wave"] == wave]
        wave_rows.append({"wave": wave, "nodes": names})

    root_fingerprint = _sha256_bytes(
        _canonical(
            {
                "engine_version": ENGINE_VERSION,
                "repository": repository,
                "resolved_sha": source_sha,
                "nodes": {row["name"]: row["fingerprint"] for row in node_rows},
            }
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "APPLAB_SELF_REVIEW_EVIDENCE_DAG_V60G",
        "engine_version": ENGINE_VERSION,
        "authority": "EXECUTION_PLANNING_ONLY",
        "repository": repository,
        "resolved_sha": source_sha,
        "root_fingerprint": root_fingerprint,
        "history_digest": history_digest,
        "nodes": node_rows,
        "waves": wave_rows,
        "run_count": sum(row["decision"] == "RUN" for row in node_rows),
        "reuse_count": sum(row["decision"] == "REUSE" for row in node_rows),
        "guardrails": {
            "reuse_requires_exact_node_fingerprint": True,
            "reuse_requires_all_declared_output_hashes": True,
            "upstream_fingerprint_is_transitive": True,
            "pass_authority_unchanged": True,
            "certification_authority_unchanged": True,
        },
    }


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        scripts = root / "scripts"
        scripts.mkdir()
        for spec in NODES.values():
            path = root / str(spec["producer"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {path.name}\n", encoding="utf-8")
        history = root / "history"
        history.mkdir()
        (history / "one.json").write_text('{"v":1}\n', encoding="utf-8")

        plan1 = build_plan(
            applab_root=root,
            repository="owner/app",
            resolved_sha="a" * 40,
            trusted_evidence_fingerprint="trusted-1",
            history_root=history,
        )
        assert plan1["run_count"] == len(NODES)
        assert plan1["reuse_count"] == 0
        graph = next(row for row in plan1["nodes"] if row["name"] == "evidence-graph")
        assert graph["wave"] > 0
        assert any(len(row["nodes"]) > 1 for row in plan1["waves"])

        cache = {}
        for row in plan1["nodes"]:
            cache[row["name"]] = {
                "fingerprint": row["fingerprint"],
                "outputs": {name: "b" * 64 for name in row["outputs"]},
            }
        cache_path = root / "cache.json"
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        plan2 = build_plan(
            applab_root=root,
            repository="owner/app",
            resolved_sha="a" * 40,
            trusted_evidence_fingerprint="trusted-1",
            history_root=history,
            cache_index_path=cache_path,
        )
        assert plan2["reuse_count"] == len(NODES)

        (root / "scripts/autonomous_app_review.py").write_text(
            "# changed\n", encoding="utf-8"
        )
        plan3 = build_plan(
            applab_root=root,
            repository="owner/app",
            resolved_sha="a" * 40,
            trusted_evidence_fingerprint="trusted-1",
            history_root=history,
            cache_index_path=cache_path,
        )
        changed = {
            row["name"]: row["decision"]
            for row in plan3["nodes"]
        }
        assert changed["autonomous-review"] == "RUN"
        assert changed["longitudinal"] == "RUN"
        assert changed["review-council"] == "RUN"
        print("AppLab v6.0G self-review Evidence DAG self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--applab-root", default=".")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--trusted-evidence-fingerprint", default="")
    parser.add_argument("--history-root", default="")
    parser.add_argument("--cross-app-fingerprint", default="none")
    parser.add_argument("--market-fingerprint", default="none")
    parser.add_argument("--max-files", type=int, default=3500)
    parser.add_argument("--cache-index", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repository or not args.resolved_sha or not args.trusted_evidence_fingerprint:
        raise SystemExit(
            "--repository, --resolved-sha and --trusted-evidence-fingerprint are required"
        )
    report = build_plan(
        applab_root=Path(args.applab_root),
        repository=args.repository,
        resolved_sha=args.resolved_sha,
        trusted_evidence_fingerprint=args.trusted_evidence_fingerprint,
        history_root=Path(args.history_root) if args.history_root else None,
        cross_app_fingerprint=args.cross_app_fingerprint,
        market_fingerprint=args.market_fingerprint,
        max_files=args.max_files,
        cache_index_path=Path(args.cache_index) if args.cache_index else None,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"root_fingerprint={report['root_fingerprint']}\n")
            handle.write(f"run_count={report['run_count']}\n")
            handle.write(f"reuse_count={report['reuse_count']}\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
