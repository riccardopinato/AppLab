#!/usr/bin/env python3
"""Produce a review-only donor research record from local REA CLI receipts.

No automatic CAP creation, source-code extraction, runtime trust or promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{64}$")
SOURCE_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_RECEIPT = 256 * 1024
MAX_EVIDENCE = 8 * 1024 * 1024
ALLOWED = {"ADOPT", "REFERENCE", "DEFER", "REJECT"}


def load(path: Path, limit: int) -> dict:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("Input must be an existing absolute regular non-symlink file")
    if path.stat().st_size > limit:
        raise ValueError("Input exceeds research budget")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def create(receipt_path: Path, evidence_dir: Path, source_review: Path | None = None) -> dict:
    receipt = load(receipt_path, MAX_RECEIPT)
    if receipt.get("mode") != "CLI_ONLY_NO_MCP" or receipt.get("status") not in (
            "REA_CLI_STATIC_OBSERVED", "REA_CLI_PARTIAL_OR_FAILED"):
        raise ValueError("Unrecognized REA CLI receipt")
    source_sha = receipt.get("source_sha")
    identity = receipt.get("input", receipt.get("artifact", {}))
    if not SOURCE_SHA.fullmatch(str(source_sha)) or not SHA.fullmatch(
            str(identity.get("sha256"))):
        raise ValueError("Missing immutable source and input identity")
    operations = receipt.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("No operation evidence")
    if not evidence_dir.is_absolute() or not evidence_dir.is_dir() or evidence_dir.is_symlink():
        raise ValueError("Evidence directory must be absolute and non-symlink")
    observed = []
    for operation in operations:
        file = operation.get("json_file") or operation.get("evidence_file")
        digest = operation.get("sha256") or operation.get("evidence_sha256")
        if (not isinstance(file, str) or file != Path(file).name or
                file.startswith(".") or not SHA.fullmatch(str(digest))):
            raise ValueError("Invalid evidence basename or declared SHA")
        evidence = evidence_dir / file
        raw = load_bytes(evidence)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Evidence hash changed or mismatched receipt")
        observed.append({"operation": operation.get("operation"),
                         "success": bool(operation.get("cli_success",
                                      operation.get("rea_success", False))),
                         "evidence_file": file, "evidence_sha256": digest})
    reviewed = []
    if source_review:
        doc = load(source_review, MAX_RECEIPT)
        if doc.get("source_sha") != source_sha or doc.get("artifact_sha256") != identity["sha256"]:
            raise ValueError("Source comparison is not about this artifact/source")
        findings = doc.get("findings", [])
        if not isinstance(findings, list) or len(findings) > 100:
            raise ValueError("Invalid bounded source-delta findings")
        for f in findings:
            if not isinstance(f, dict) or f.get("decision") not in ALLOWED:
                raise ValueError("Invalid manually reviewed finding")
            if not f.get("fact") or not f.get("source_comparison") or not f.get("license_basis"):
                raise ValueError("Findings require concrete source comparison and rights basis")
            reviewed.append({k: str(f[k]) for k in ("fact", "source_comparison",
                                                     "license_basis", "decision")})
    return {"schema_version": 1, "kind": "REA_DONOR_RESEARCH_REVIEW_ONLY",
            "source_repository": receipt.get("repository"), "source_sha": source_sha,
            "artifact_sha256": identity["sha256"], "family": receipt.get("family", "pe"),
            "engine": "rea-agents@6.9.0 CLI", "operations": observed,
            "execution": "ALL_SUCCESS" if all(x["success"] for x in observed)
                         else "PARTIAL_OR_FAILED",
            "source_comparison": "MANUALLY_REVIEWED" if source_review else "PENDING",
            "findings": reviewed,
            "canonical_capability_id": None,
            "admission": "E1_RESEARCH_ONLY",
            "certified_donor": False, "certified_golden": False,
            "app_code_changed": False}


def load_bytes(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_EVIDENCE:
        raise ValueError("Missing, symlinked or oversized REA evidence file")
    return path.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-review", type=Path)
    args = parser.parse_args()
    try:
        report = create(args.receipt, args.evidence_dir, args.source_review)
        if not args.output.is_absolute() or args.output.is_symlink():
            raise ValueError("Output must be an absolute non-symlink path")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"REA donor report BLOCKED: {exc}", file=sys.stderr)
        return 2
    print("REA donor E1 research report created: not a certified donor or capability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
