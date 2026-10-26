#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def evaluate(
    contract: dict[str, Any],
    execution: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    cache = execution.get("build_cache")
    if not isinstance(cache, dict):
        cache = {}
    cache_hit = cache.get("hit") is True
    base = {
        "schema_version": 1,
        "record_type": "VERIFICATION_REUSE_PROMOTION_V57E",
        "authority": "PROMOTION_EVIDENCE_ONLY",
        "promotion_ready": False,
        "cache_hit": cache_hit,
        "coverage_reduction_enabled": False,
        "certification_authority_unchanged": True,
    }
    if not cache_hit:
        return {**base, "state": "HOLD", "reason": "BUILD_CACHE_NOT_HIT"}

    repository = str(contract.get("repository", "")).strip()
    resolved_sha = str(contract.get("resolved_sha", "")).strip().lower()
    apk = contract.get("apk") if isinstance(contract.get("apk"), dict) else {}
    apk_sha = str(apk.get("sha256", "")).strip().lower()
    apk_size = int(apk.get("size_bytes", 0) or 0)
    execution_key = str(execution.get("execution_key", "")).strip()
    artifact_id = str(cache.get("artifact_id", "")).strip()

    checks = {
        "repository_bound": bool(repository),
        "resolved_sha_bound": bool(re.fullmatch(r"[0-9a-f]{40}", resolved_sha)),
        "artifact_sha256_bound": bool(re.fullmatch(r"[0-9a-f]{64}", apk_sha)),
        "artifact_size_bound": apk_size > 0,
        "execution_key_bound": bool(re.fullmatch(r"[0-9a-f]{64}", execution_key)),
        "cache_contract_validated": str(cache.get("reason", "")).strip() == "validated",
        "cache_artifact_id_bound": bool(artifact_id),
        "execution_repository_matches": str(execution.get("repository", "")).strip() == repository,
        "execution_sha_matches": str(execution.get("resolved_sha", "")).strip().lower() == resolved_sha,
        "runtime_result_pass": str(result.get("result", "")).strip().upper() == "PASS",
    }
    result_repository = str(result.get("repository", "")).strip()
    result_sha = str(result.get("resolved_sha", "")).strip().lower()
    if result_repository:
        checks["result_repository_matches"] = result_repository == repository
    if result_sha:
        checks["result_sha_matches"] = result_sha == resolved_sha
    runtime_result = str(result.get("runtime_result", "")).strip().upper()
    if runtime_result:
        checks["trusted_runtime_pass"] = runtime_result == "PASS"

    ready = all(checks.values())
    return {
        **base,
        "state": "READY" if ready else "BLOCKED",
        "reason": "EXACT_ARTIFACT_REUSE_PROVEN" if ready else "PROMOTION_CHECK_FAILED",
        "promotion_ready": ready,
        "repository": repository,
        "resolved_sha": resolved_sha,
        "exact_artifact_identity": {
            "apk_sha256": apk_sha,
            "size_bytes": apk_size,
            "execution_key": execution_key,
            "cache_artifact_id": artifact_id,
        },
        "checks": checks,
    }


def write_outputs(path: str, report: dict[str, Any]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"promotion_ready={str(bool(report.get('promotion_ready'))).lower()}\n")
        handle.write(f"cache_hit={str(bool(report.get('cache_hit'))).lower()}\n")
        handle.write(f"state={report.get('state','HOLD')}\n")


def self_test() -> None:
    contract = {
        "repository": "owner/app",
        "resolved_sha": "a" * 40,
        "apk": {"sha256": "b" * 64, "size_bytes": 123},
    }
    execution = {
        "repository": "owner/app",
        "resolved_sha": "a" * 40,
        "execution_key": "c" * 64,
        "build_cache": {
            "applicable": True,
            "hit": True,
            "reason": "validated",
            "artifact_id": "12345",
        },
    }
    result = {
        "result": "PASS",
        "runtime_result": "PASS",
        "repository": "owner/app",
        "resolved_sha": "a" * 40,
    }
    ready = evaluate(contract, execution, result)
    assert ready["promotion_ready"] is True
    assert ready["state"] == "READY"

    raw_runtime = {"result": "PASS"}
    early = evaluate(contract, execution, raw_runtime)
    assert early["promotion_ready"] is True
    assert "result_repository_matches" not in early["checks"]
    assert "result_sha_matches" not in early["checks"]

    miss = json.loads(json.dumps(execution))
    miss["build_cache"]["hit"] = False
    hold = evaluate(contract, miss, result)
    assert hold["promotion_ready"] is False
    assert hold["state"] == "HOLD"

    bad = json.loads(json.dumps(execution))
    bad["build_cache"]["reason"] = "unvalidated"
    blocked = evaluate(contract, bad, result)
    assert blocked["promotion_ready"] is False
    assert blocked["state"] == "BLOCKED"
    print("AppLab v5.7E promotion gate self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", default="")
    parser.add_argument("--execution-plan", default="")
    parser.add_argument("--result", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.contract or not args.execution_plan or not args.result:
        raise SystemExit("--contract, --execution-plan and --result are required")

    report = evaluate(
        read_json(Path(args.contract)),
        read_json(Path(args.execution_plan)),
        read_json(Path(args.result)),
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_outputs(args.github_output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.require_ready and not report["promotion_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
