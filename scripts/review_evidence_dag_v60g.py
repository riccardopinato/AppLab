#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

NODE_OUTPUTS = {
    "planner_feedback": ("planner-feedback.json", "planner-feedback.md"),
    "simulated_human": ("simulated-human-qa.json", "simulated-human-qa.md"),
    "design_advisor": ("design-system-advisor.json", "design-system-advisor.md"),
    "competitive": (
        "competitive-product-intelligence.json",
        "competitive-product-intelligence.md",
    ),
}

PRODUCER_SCRIPTS = {
    "planner_feedback": "planner_feedback.py",
    "simulated_human": "simulated_human_qa.py",
    "design_advisor": "design_system_advisor.py",
    "competitive": "competitive_product_intelligence.py",
}


class FanoutError(ValueError):
    pass


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def plan(
    *,
    applab_root: Path,
    evidence_dir: Path,
    trusted_runtime_dir: Path,
    target_root: Path,
    repository: str,
    resolved_sha: str,
    applab_sha: str,
    max_files: int,
    market_evidence_path: str,
) -> dict[str, Any]:
    graph = evidence_dir / "evidence-graph.json"
    analysis_plan = trusted_runtime_dir / "analysis-plan.json"
    if not graph.is_file() or not analysis_plan.is_file():
        raise FanoutError("review fan-out requires Evidence Graph and analysis plan")
    market_rel = Path(market_evidence_path)
    if market_rel.is_absolute() or ".." in market_rel.parts:
        raise FanoutError("unsafe market evidence path")
    market = target_root / market_rel

    producer_hashes: dict[str, str] = {}
    for node, script in PRODUCER_SCRIPTS.items():
        path = applab_root / "scripts" / script
        if not path.is_file():
            raise FanoutError(f"missing producer script: {script}")
        producer_hashes[node] = _hash_file(path)

    inputs = {
        "schema_version": 1,
        "repository": repository,
        "resolved_sha": resolved_sha,
        "applab_sha": applab_sha,
        "max_files": max_files,
        "evidence_graph_sha256": _hash_file(graph),
        "analysis_plan_sha256": _hash_file(analysis_plan),
        "market_evidence_sha256": _hash_file(market) if market.is_file() else "",
        "producer_hashes": producer_hashes,
    }
    digest = _hash_bytes(_canonical(inputs))
    return {
        "schema_version": 1,
        "record_type": "REVIEW_EVIDENCE_DAG_PLAN_V60G",
        "authority": "ADVISORY_EXECUTION_ONLY",
        "fingerprint_sha256": digest,
        "cache_key": f"applab-review-fanout-v60g-{digest}",
        "repository": repository,
        "resolved_sha": resolved_sha,
        "nodes": {
            name: {
                "producer": PRODUCER_SCRIPTS[name],
                "outputs": list(NODE_OUTPUTS[name]),
                "fingerprint_sha256": _hash_bytes(
                    _canonical({"node": name, "inputs": inputs})
                ),
            }
            for name in sorted(NODE_OUTPUTS)
        },
        "layers": [
            ["evidence_graph"],
            ["competitive", "planner_feedback", "simulated_human"],
            ["design_advisor"],
            ["release_assurance", "virtual_review_council"],
        ],
        "pass_certified_authority": "UNCHANGED",
    }


def _run_node(
    name: str,
    command: list[str],
    *,
    log_dir: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / f"{name}.log"
    log.write_text(proc.stdout or "", encoding="utf-8")
    return {
        "node": name,
        "returncode": proc.returncode,
        "duration_seconds": duration,
        "log": str(log),
    }


def _commands(
    *,
    applab_root: Path,
    target_root: Path,
    evidence_dir: Path,
    trusted_runtime_dir: Path,
    max_files: int,
    market_evidence_path: str,
) -> dict[str, list[str]]:
    py = sys.executable
    scripts = applab_root / "scripts"
    commands = {
        "planner_feedback": [
            py,
            str(scripts / "planner_feedback.py"),
            "--graph",
            str(evidence_dir / "evidence-graph.json"),
            "--analysis-plan",
            str(trusted_runtime_dir / "analysis-plan.json"),
            "--output-dir",
            str(evidence_dir),
        ],
        "simulated_human": [
            py,
            str(scripts / "simulated_human_qa.py"),
            "--evidence-dir",
            str(evidence_dir),
            "--output-dir",
            str(evidence_dir),
        ],
        "design_advisor": [
            py,
            str(scripts / "design_system_advisor.py"),
            "--repo-root",
            str(target_root),
            "--evidence-dir",
            str(evidence_dir),
            "--output-dir",
            str(evidence_dir),
            "--max-files",
            str(max_files),
        ],
        "competitive": [
            py,
            str(scripts / "competitive_product_intelligence.py"),
            "--repo-root",
            str(target_root),
            "--evidence-dir",
            str(evidence_dir),
            "--output-dir",
            str(evidence_dir),
        ],
    }
    market_rel = Path(market_evidence_path)
    market = target_root / market_rel
    if market.is_file():
        commands["competitive"].extend(["--market-evidence", str(market)])
    return commands


def run_fanout(
    *,
    applab_root: Path,
    target_root: Path,
    evidence_dir: Path,
    trusted_runtime_dir: Path,
    log_dir: Path,
    max_files: int,
    market_evidence_path: str,
) -> dict[str, Any]:
    commands = _commands(
        applab_root=applab_root,
        target_root=target_root,
        evidence_dir=evidence_dir,
        trusted_runtime_dir=trusted_runtime_dir,
        max_files=max_files,
        market_evidence_path=market_evidence_path,
    )
    started = time.monotonic()
    results: list[dict[str, Any]] = []

    # Wave 1 contains only producers that read the immutable pre-fanout
    # evidence set. design_advisor must wait for simulated-human-qa.json,
    # otherwise parallel execution is race-dependent and cache-unsafe.
    first_wave = ("planner_feedback", "simulated_human", "competitive")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(first_wave)) as pool:
        futures = {
            pool.submit(_run_node, name, commands[name], log_dir=log_dir): name
            for name in first_wave
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    failures = [row for row in results if row["returncode"] != 0]
    if not failures:
        results.append(
            _run_node(
                "design_advisor",
                commands["design_advisor"],
                log_dir=log_dir,
            )
        )

    results.sort(key=lambda row: row["node"])
    failures = [row for row in results if row["returncode"] != 0]
    report = {
        "schema_version": 1,
        "record_type": "REVIEW_EVIDENCE_FANOUT_V60G",
        "authority": "ADVISORY_EXECUTION_ONLY",
        "status": "PASS" if not failures else "FAIL",
        "wall_seconds": round(time.monotonic() - started, 3),
        "sum_node_seconds": round(
            sum(float(row["duration_seconds"]) for row in results), 3
        ),
        "nodes": results,
    }
    if failures:
        names = ", ".join(row["node"] for row in failures)
        raise FanoutError(f"review evidence fan-out failed: {names}")
    for node, outputs in NODE_OUTPUTS.items():
        for filename in outputs:
            if not (evidence_dir / filename).is_file():
                raise FanoutError(f"{node} did not produce {filename}")
    return report


def cache_outputs(evidence_dir: Path, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for outputs in NODE_OUTPUTS.values():
        for filename in outputs:
            src = evidence_dir / filename
            if not src.is_file():
                raise FanoutError(f"cannot cache missing output: {filename}")
            shutil.copy2(src, cache_dir / filename)


def restore_outputs(cache_dir: Path, evidence_dir: Path) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for outputs in NODE_OUTPUTS.values():
        for filename in outputs:
            src = cache_dir / filename
            if not src.is_file():
                raise FanoutError(f"cache is incomplete: {filename}")
            shutil.copy2(src, evidence_dir / filename)


def self_test() -> None:
    assert sorted(NODE_OUTPUTS) == [
        "competitive",
        "design_advisor",
        "planner_feedback",
        "simulated_human",
    ]
    payload = {"x": 1, "y": [2, 3]}
    assert _hash_bytes(_canonical(payload)) == _hash_bytes(_canonical(payload))
    print("AppLab v6.0G review evidence DAG self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--applab-root", default=".")
    parser.add_argument("--target-root", default="target")
    parser.add_argument("--evidence-dir", default="applab-autonomous-review")
    parser.add_argument("--trusted-runtime-dir", default="trusted-runtime")
    parser.add_argument("--log-dir", default="review-fanout-logs")
    parser.add_argument("--cache-dir", default=".applab-review-fanout-cache")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--applab-sha", default="")
    parser.add_argument("--max-files", type=int, default=3500)
    parser.add_argument("--market-evidence-path", default="market-evidence.json")
    parser.add_argument("--plan-output", default="")
    parser.add_argument("--report-output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--restore-cache", action="store_true")
    parser.add_argument("--save-cache", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    applab_root = Path(args.applab_root).resolve()
    target_root = Path(args.target_root).resolve()
    evidence_dir = Path(args.evidence_dir).resolve()
    trusted_runtime = Path(args.trusted_runtime_dir).resolve()
    cache_dir = Path(args.cache_dir).resolve()

    if args.restore_cache:
        restore_outputs(cache_dir, evidence_dir)
        print("AppLab v6.0G review fan-out cache restore PASS")
        return 0

    dag = plan(
        applab_root=applab_root,
        evidence_dir=evidence_dir,
        trusted_runtime_dir=trusted_runtime,
        target_root=target_root,
        repository=args.repository,
        resolved_sha=args.resolved_sha,
        applab_sha=args.applab_sha,
        max_files=args.max_files,
        market_evidence_path=args.market_evidence_path,
    )
    if args.plan_output:
        Path(args.plan_output).write_text(
            json.dumps(dag, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"cache_key={dag['cache_key']}\n")
            handle.write(f"fingerprint={dag['fingerprint_sha256']}\n")
    if args.plan_only:
        print(json.dumps(dag, indent=2, sort_keys=True))
        return 0

    report = run_fanout(
        applab_root=applab_root,
        target_root=target_root,
        evidence_dir=evidence_dir,
        trusted_runtime_dir=trusted_runtime,
        log_dir=Path(args.log_dir).resolve(),
        max_files=args.max_files,
        market_evidence_path=args.market_evidence_path,
    )
    if args.save_cache:
        cache_outputs(evidence_dir, cache_dir)
    if args.report_output:
        Path(args.report_output).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
