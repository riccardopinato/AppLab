#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import release_reality
import trusted_evidence_manifest

ENGINE_VERSION = "5.9C"


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _rewrite_summary(path: Path, result: str, reason: str) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else "# AppLab report\n"
    lines = text.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("- Result:"):
            lines[index] = f"- Result: {result}"
            replaced = True
            break
    if not replaced:
        lines.insert(1, f"- Result: {result}")
    lines.append(f"- Journey shard aggregate: {result}")
    if reason:
        lines.append(f"- Journey shard reason: {reason}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def finalize(
    *,
    coordinator_dir: Path,
    aggregate_path: Path,
    artifact_path: Path,
    output_dir: Path,
    repository: str,
    resolved_sha: str,
    run_id: str,
    analysis_mode: str,
    contract_fingerprint: str,
    config_fingerprint: str,
    trusted_applab_sha: str,
) -> dict[str, Any]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(coordinator_dir, output_dir)

    result_path = output_dir / "result.json"
    contract_path = output_dir / "build-contract.json"
    if not result_path.is_file() or not contract_path.is_file():
        raise ValueError("coordinator evidence is missing result/build contract")

    result = read_json(result_path)
    if str(result.get("repository", "")) != repository:
        raise ValueError("coordinator repository binding mismatch")
    if str(result.get("resolved_sha", "")).lower() != resolved_sha.lower():
        raise ValueError("coordinator SHA binding mismatch")
    if str(result.get("workflow_run_id", "")) != str(run_id):
        raise ValueError("coordinator run binding mismatch")

    aggregate: dict[str, Any]
    try:
        aggregate = read_json(aggregate_path)
    except ValueError as exc:
        aggregate = {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "result": "FAIL",
            "authoritative": True,
            "coverage_union_verified": False,
            "exact_artifact_verified": False,
            "reason": str(exc),
        }
    (output_dir / "journey-shard-aggregate.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    aggregate_pass = str(aggregate.get("result", "")).upper() == "PASS"
    coordinator_pass = str(result.get("result", "")).upper() == "PASS"
    final_pass = aggregate_pass and coordinator_pass
    final_result = "PASS" if final_pass else "FAIL"
    reason = "" if final_pass else str(aggregate.get("reason", "") or "authoritative journey shard aggregate failed")

    result["result"] = final_result
    result["pipeline_status"] = "success" if final_pass else "failure"
    result["runtime_result"] = final_result
    result["reason"] = None if final_pass else reason
    result["journey_sharding"] = {
        "engine_version": ENGINE_VERSION,
        "authoritative": True,
        "aggregate_result": str(aggregate.get("result", "FAIL")),
        "coverage_union_verified": aggregate.get("coverage_union_verified") is True,
        "exact_artifact_verified": aggregate.get("exact_artifact_verified") is True,
        "shard_count": int(aggregate.get("shard_count", 0) or 0),
    }
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rewrite_summary(output_dir / "summary.md", final_result, reason)

    # The coordinator manifest covered pre-aggregate bytes. Replace it only after
    # the authoritative result and Release Reality have been regenerated.
    (output_dir / trusted_evidence_manifest.MANIFEST_NAME).unlink(missing_ok=True)
    reality = release_reality.build_release_reality(
        output_dir,
        artifact_path,
        workflow_run_id=str(run_id),
        trusted_applab_sha=trusted_applab_sha,
        runtime_outcome="success" if final_pass else "failure",
    )
    release_reality.write_outputs(output_dir, reality)
    manifest = trusted_evidence_manifest.create_manifest(
        output_dir,
        repository=repository,
        resolved_sha=resolved_sha,
        run_id=str(run_id),
        analysis_mode=analysis_mode,
        contract_fingerprint=contract_fingerprint,
        config_fingerprint=config_fingerprint,
        trusted_applab_sha=trusted_applab_sha,
    )
    return {
        "result": final_result,
        "reason": reason,
        "manifest_result": manifest.get("result", {}).get("result"),
        "release_runtime_state": next(
            (row.get("state") for row in reality.get("levels", [])
             if row.get("key") == "TRUSTED_RUNTIME_VERIFIED"),
            "UNKNOWN",
        ),
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        coordinator = root / "coordinator"
        output = root / "final"
        coordinator.mkdir()
        artifact = root / "app.apk"
        artifact.write_bytes(b"apk")
        sha = release_reality.sha256_file(artifact)
        result = {
            "schema_version": 1,
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "workflow_run_id": "123",
            "package_id": "com.example.app",
            "result": "PASS",
            "pipeline_status": "success",
            "runtime_result": "PASS",
        }
        contract = {
            "schema_version": 1,
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "engine": "flutter",
            "analysis_mode": "fast",
            "package_id": "com.example.app",
            "quality_evidence": {"analyze":"PASS","lint":"N/A","unit_tests":"PASS","build":"PASS"},
            "certification_policy": {"schema_version":1,"requires_real_device":False,"expected_signing_certificate_sha256":"","max_apk_bytes":1000},
            "apk": {"path":"app.apk","size_bytes":3,"sha256":sha,"package_id":"com.example.app","version_name":"1","version_code":"1","build_variant":"release","signing_cert_sha256":"","signing_subject":""},
        }
        (coordinator / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (coordinator / "build-contract.json").write_text(json.dumps(contract), encoding="utf-8")
        (coordinator / "summary.md").write_text("# AppLab report\n\n- Result: PASS\n", encoding="utf-8")
        aggregate = root / "aggregate.json"
        aggregate.write_text(json.dumps({"result":"FAIL","authoritative":True,"coverage_union_verified":False,"exact_artifact_verified":True,"reason":"deep shard failed"}), encoding="utf-8")
        final = finalize(
            coordinator_dir=coordinator, aggregate_path=aggregate, artifact_path=artifact,
            output_dir=output, repository="owner/app", resolved_sha="a"*40,
            run_id="123", analysis_mode="fast", contract_fingerprint="c",
            config_fingerprint="p", trusted_applab_sha="b"*40,
        )
        assert final["result"] == "FAIL", final
        persisted = read_json(output / "result.json")
        assert persisted["result"] == "FAIL", persisted
        assert read_json(output / "trusted-evidence-manifest.json")["result"]["result"] == "FAIL"
        reality = read_json(output / "release-reality.json")
        states = {row["key"]: row["state"] for row in reality["levels"]}
        assert states["TRUSTED_RUNTIME_VERIFIED"] == "FAIL", reality
        assert "Journey shard aggregate: FAIL" in (output / "summary.md").read_text(encoding="utf-8")
    print("AppLab v5.9C authoritative result finalizer self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator-dir", default="")
    parser.add_argument("--aggregate", default="")
    parser.add_argument("--artifact", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--analysis-mode", default="fast")
    parser.add_argument("--contract-fingerprint", default="manual")
    parser.add_argument("--config-fingerprint", default="manual")
    parser.add_argument("--trusted-applab-sha", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (args.coordinator_dir, args.aggregate, args.artifact, args.output_dir,
                args.repository, args.resolved_sha, args.run_id, args.trusted_applab_sha)
    if not all(required):
        parser.error("all authoritative finalization arguments are required")
    payload = finalize(
        coordinator_dir=Path(args.coordinator_dir),
        aggregate_path=Path(args.aggregate),
        artifact_path=Path(args.artifact),
        output_dir=Path(args.output_dir),
        repository=args.repository,
        resolved_sha=args.resolved_sha,
        run_id=args.run_id,
        analysis_mode=args.analysis_mode,
        contract_fingerprint=args.contract_fingerprint,
        config_fingerprint=args.config_fingerprint,
        trusted_applab_sha=args.trusted_applab_sha,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
