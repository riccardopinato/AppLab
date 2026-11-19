#!/usr/bin/env python3
"""Convert verified REA CLI receipts and explicitly reviewed findings to donor research.

Never edits catalog, apps, Golden, CI provenance or trusted verifier evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePath

SHA = re.compile(r"^[a-f0-9]{64}$")
ID = re.compile(r"^[A-Za-z0-9_.:-]{2,72}$")
DECISIONS = {"ADOPT_CANDIDATE", "REFERENCE_ONLY", "DEFER", "REJECT"}
SOURCE_COMPARISON = {"NEW_BEYOND_SOURCE", "ALREADY_IN_SOURCE", "CONFLICT", "NOT_VERIFIED"}
RIGHTS = {"AUTHORIZED_FOR_RESEARCH", "INCOMPATIBLE_FOR_COPY", "REVIEW_REQUIRED"}


def _json(path: Path, limit: int) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError("Source report must be a bounded regular file")
    d = json.loads(path.read_text(encoding="utf8"))
    if not isinstance(d, dict):
        raise ValueError("Expected JSON object")
    return d


def review(receipt_path: Path, evidence_dir: Path, findings_path: Path) -> dict:
    receipt = _json(receipt_path, 4 * 1024 * 1024)
    plan = _json(findings_path, 2 * 1024 * 1024)
    if (receipt.get("type") != "REA_RESEARCH_CLI_RECEIPT"
            or receipt.get("status") != "REA_RESEARCH_OBSERVED"
            or receipt.get("donor_admission") != "RESEARCH_ONLY"
            or receipt.get("trusted_runtime") is not False):
        raise ValueError("Receipt does not meet research-only verified-shape gate")
    artifact = receipt.get("artifact", {})
    if not SHA.fullmatch(str(artifact.get("sha256", ""))):
        raise ValueError("Receipt has invalid artifact SHA")
    operations = receipt.get("operations", [])
    verified_operations = set()
    for entry in operations:
        if entry.get("status") == "NOT_APPLICABLE_NO_LIBAPP_SO":
            continue
        if entry.get("status") != "OBSERVED":
            raise ValueError("Non-successful REA operation in receipt")
        ev = entry.get("evidence", {})
        name = ev.get("file", "")
        if not isinstance(name, str) or name != Path(name).name or "/" in name or "\\" in name:
            raise ValueError("Evidence filename not a safe basename")
        path = evidence_dir / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing or symlinked evidence")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != ev.get("sha256") or path.stat().st_size != ev.get("bytes"):
            raise ValueError("External REA evidence SHA/size mismatch")
        verified_operations.add(entry["operation"])
    rows = plan.get("findings")
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("findings must be a bounded array")
    ids = set()
    reviewed = []
    for row in rows:
        if not isinstance(row, dict) or not ID.fullmatch(str(row.get("id", ""))):
            raise ValueError("Invalid finding ID")
        if row["id"] in ids:
            raise ValueError("Duplicate finding ID")
        ids.add(row["id"])
        if (row.get("decision") not in DECISIONS
                or row.get("source_comparison") not in SOURCE_COMPARISON
                or row.get("rights") not in RIGHTS):
            raise ValueError("Invalid donor decision, comparison, or license disposition")
        if row.get("evidence_operation") not in verified_operations:
            raise ValueError("Finding points to missing or unverified REA operation")
        if not isinstance(row.get("reason"), str) or not 12 <= len(row["reason"]) <= 2500:
            raise ValueError("Concrete bounded source-comparison reasoning required")
        if (row["decision"] == "ADOPT_CANDIDATE"
                and (row["source_comparison"] != "NEW_BEYOND_SOURCE"
                     or row["rights"] != "AUTHORIZED_FOR_RESEARCH")):
            raise ValueError("ADOPT_CANDIDATE requires NEW evidence and research authorization")
        reviewed.append({k: row[k] for k in ("id", "decision", "source_comparison",
                      "rights", "evidence_operation", "reason")})
    return {
        "schema_version": 1, "report_type": "REA_DONOR_RESEARCH_DECISIONS",
        "source_repository": receipt["repository"], "source_sha": receipt["source_sha"],
        "target_sha256": artifact["sha256"],
        "rea_version": receipt["engine"]["version"],
        "findings": reviewed, "new_ideas": sum(x["source_comparison"] == "NEW_BEYOND_SOURCE" for x in reviewed),
        "adopt_candidate_count": sum(x["decision"] == "ADOPT_CANDIDATE" for x in reviewed),
        "catalog_mutated": False, "certified_donors": 0,
        "golden_promoted": False, "execution_of_target": "NONE",
        "classification": "E1_RESEARCH_REVIEW_PENDING_CATALOG_PR",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--evidence-dir", type=Path, required=True)
    p.add_argument("--findings", type=Path, required=True)
    args = p.parse_args()
    try:
        result = review(args.receipt, args.evidence_dir, args.findings)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"REA DONOR REVIEW BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
