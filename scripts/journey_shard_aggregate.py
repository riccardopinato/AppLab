#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ENGINE_VERSION = "5.9C"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def identity(contract: dict[str, Any]) -> tuple[str, str, str]:
    apk = contract.get("apk") if isinstance(contract.get("apk"), dict) else {}
    return (
        str(contract.get("repository", "")).lower(),
        str(contract.get("resolved_sha", "")).lower(),
        str(apk.get("sha256", "")).lower(),
    )


def aggregate(
    *,
    expected_contract: Path,
    plan_path: Path,
    evidence_root: Path,
    mode: str,
) -> dict[str, Any]:
    expected = read_json(expected_contract)
    plan = read_json(plan_path)
    expected_identity = identity(expected)
    selected = plan.get("selected_journeys")
    if not isinstance(selected, list) or not selected or not all(isinstance(v, str) for v in selected):
        raise ValueError("trusted plan has no selected journeys")
    selected_set = set(selected)
    if len(selected_set) != len(selected):
        raise ValueError("trusted plan selected journeys are duplicated")

    reports = sorted(evidence_root.rglob("journey-runtime.json"))
    if not reports:
        raise ValueError("no journey shard evidence found")

    union: set[str] = set()
    rows: list[dict[str, Any]] = []
    for report_path in reports:
        bundle = report_path.parent
        contract_path = bundle / "contract.json"
        if not contract_path.is_file():
            raise ValueError(f"shard contract missing beside {report_path}")
        if identity(read_json(contract_path)) != expected_identity:
            raise ValueError(f"shard exact-artifact identity mismatch: {report_path}")
        report = read_json(report_path)
        if str(report.get("repository", "")).lower() != expected_identity[0]:
            raise ValueError(f"shard repository mismatch: {report_path}")
        if report.get("result") != "PASS":
            shard_id = str(report.get("shard_id", bundle.name))
            reason = str(report.get("reason", "") or "")
            if not reason:
                journey_rows = report.get("journeys")
                if isinstance(journey_rows, list):
                    reason = next(
                        (
                            str(row.get("reason", "") or "")
                            for row in reversed(journey_rows)
                            if isinstance(row, dict) and row.get("reason")
                        ),
                        "",
                    )
            detail = reason or str(report_path)
            raise ValueError(f"shard {shard_id} did not PASS: {detail}")
        journeys = report.get("selected_journeys")
        if not isinstance(journeys, list) or not journeys or not all(isinstance(v, str) for v in journeys):
            raise ValueError(f"invalid shard journey list: {report_path}")
        for journey_id in journeys:
            if journey_id not in selected_set:
                raise ValueError(f"unexpected journey {journey_id}")
            if journey_id in union:
                raise ValueError(f"journey executed by multiple shards: {journey_id}")
            union.add(journey_id)
        rows.append({
            "shard_id": str(report.get("shard_id", bundle.name)),
            "journeys": journeys,
            "runtime_seconds": report.get("seconds"),
        })

    if union != selected_set:
        missing = sorted(selected_set - union)
        raise ValueError("shard coverage union incomplete: " + ",".join(missing))

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "result": "PASS",
        "mode": mode,
        "authoritative": mode == "authoritative",
        "repository": expected_identity[0],
        "resolved_sha": expected_identity[1],
        "apk_sha256": expected_identity[2],
        "selected_journeys": selected,
        "coverage_union_verified": True,
        "exact_artifact_verified": True,
        "shard_count": len(rows),
        "shards": rows,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        expected = root / "contract.json"
        plan = root / "plan.json"
        evidence = root / "evidence"
        expected_payload = {
            "repository": "owner/app",
            "resolved_sha": "a" * 40,
            "apk": {"sha256": "b" * 64},
        }
        expected.write_text(json.dumps(expected_payload), encoding="utf-8")
        plan.write_text(json.dumps({"selected_journeys": ["shell", "vault"]}), encoding="utf-8")
        for shard_id, journeys in (("coordinator", ["shell"]), ("deep", ["vault"])):
            bundle = evidence / shard_id
            bundle.mkdir(parents=True)
            (bundle / "contract.json").write_text(json.dumps(expected_payload), encoding="utf-8")
            (bundle / "journey-runtime.json").write_text(json.dumps({
                "result": "PASS",
                "repository": "owner/app",
                "shard_id": shard_id,
                "selected_journeys": journeys,
                "seconds": 1.0,
            }), encoding="utf-8")
        result = aggregate(
            expected_contract=expected,
            plan_path=plan,
            evidence_root=evidence,
            mode="authoritative",
        )
        assert result["coverage_union_verified"] is True
        assert result["exact_artifact_verified"] is True
        assert result["shard_count"] == 2
    print("AppLab v5.9C shard aggregate self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-contract", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--evidence-root", default="")
    parser.add_argument("--mode", choices=("shadow", "authoritative"), default="shadow")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.expected_contract, args.plan, args.evidence_root, args.output)):
        parser.error("aggregate arguments are required")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = aggregate(
            expected_contract=Path(args.expected_contract),
            plan_path=Path(args.plan),
            evidence_root=Path(args.evidence_root),
            mode=args.mode,
        )
    except Exception as exc:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "result": "FAIL",
            "mode": args.mode,
            "authoritative": args.mode == "authoritative",
            "coverage_union_verified": False,
            "exact_artifact_verified": False,
            "reason": str(exc),
        }
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1 if args.mode == "authoritative" else 0
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
