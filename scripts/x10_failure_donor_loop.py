#!/usr/bin/env python3
"""X10-045: correlate exact-source failed QA receipts with *existing* Pattern-3.

Thin admission facade: no duplicate failure classifier/pattern engine/donor
registry, no autonomous fixes and no claim that replay actually ran.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
TOKEN = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
TEST_KEY = re.compile(r"[A-Za-z0-9_./:-]{1,128}\Z")
CATEGORIES = frozenset(("BUILD", "TEST", "VISUAL_PRODUCT", "RUNTIME",
                       "PERFORMANCE", "INFRASTRUCTURE", "PERSISTENCE", "NETWORK"))
MAX_RECEIPTS = 100


class FailureDonorLoopError(ValueError):
    pass


def demand(ok: bool, code: str) -> None:
    if not ok:
        raise FailureDonorLoopError(code)


def analyze(
    failures: list[dict[str, Any]],
    *,
    trusted_failure_verifier: Callable[[dict[str, Any]], dict[str, Any]],
    existing_pattern_observations: Callable[[dict[str, Any]], list[dict[str, Any]]],
    existing_pattern3_builder: Callable[[dict[str, Any]], dict[str, Any]],
    existing_feedback_packager: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    read_only_reuse_catalog: dict[str, Any],
) -> dict[str, Any]:
    """Fail-closed source-bound input to existing AppLab Pattern-3 + feedback.

    External verifier must independently confirm each run failure and digest.
    Fixtures can prove this contract, not the existence of a live failure.
    """
    demand(isinstance(failures, list) and 3 <= len(failures) <= MAX_RECEIPTS,
           "INSUFFICIENT_REPEATED_FAILURE_EVIDENCE")
    demand(all(callable(x) for x in (
        trusted_failure_verifier, existing_pattern_observations,
        existing_pattern3_builder, existing_feedback_packager)),
        "TRUSTED_EXISTING_ADAPTERS_REQUIRED")
    demand(isinstance(read_only_reuse_catalog, dict)
           and isinstance(read_only_reuse_catalog.get("repositories"), list),
           "READ_ONLY_CATALOG_MISSING")
    keys = set()
    evidence_keys = set()
    observations = []
    source_refs = []
    for row in failures:
        demand(isinstance(row, dict) and set(row) == {
            "repository", "source_sha", "workflow_run_id", "test_key",
            "failure_code", "category", "evidence_sha256", "run_url", "result",
        }, "FAILURE_RECEIPT_SCHEMA_INVALID")
        repo, sha, run_id = row["repository"], row["source_sha"], row["workflow_run_id"]
        category, code, test_key = row["category"], row["failure_code"], row["test_key"]
        demand(isinstance(repo, str) and REPO.fullmatch(repo) is not None
               and isinstance(sha, str) and SHA40.fullmatch(sha) is not None
               and type(run_id) is int and run_id > 0
               and isinstance(test_key, str) and TEST_KEY.fullmatch(test_key) is not None
               and category in CATEGORIES and isinstance(code, str)
               and TOKEN.fullmatch(code) is not None
               and isinstance(row["evidence_sha256"], str)
               and SHA256.fullmatch(row["evidence_sha256"]) is not None
               and row["result"] in ("FAIL", "ERROR")
               and isinstance(row["run_url"], str) and row["run_url"] in (
                   f"https://github.com/{repo}/actions/runs/{run_id}",
                   f"https://github.com/riccardopinato/AppLab/actions/runs/{run_id}"),
               "FAILURE_SOURCE_OR_TAXONOMY_INVALID")
        # Three *independent runs* are needed, not three test names from one
        # workflow run, and a repeated evidence blob cannot inflate the count.
        canonical_repo = repo.casefold()
        key = (canonical_repo, run_id)
        evidence_key = (canonical_repo, sha, row["evidence_sha256"])
        demand(key not in keys and evidence_key not in evidence_keys,
               "REPLAY_OR_DUPLICATE_FAILURE")
        keys.add(key)
        evidence_keys.add(evidence_key)
        verified = trusted_failure_verifier(row)
        demand(isinstance(verified, dict) and verified.get("verified") is True
               and isinstance(verified.get("repository"), str)
               and verified["repository"].casefold() == canonical_repo
               and verified.get("source_sha") == sha
               and verified.get("workflow_run_id") == run_id
               and verified.get("test_key") == test_key
               and verified.get("category") == category
               and verified.get("failure_code") == code
               and verified.get("evidence_sha256") == row["evidence_sha256"]
               and verified.get("result") == row["result"],
               "FAILURE_PROVENANCE_NOT_INDEPENDENTLY_VERIFIED")
        # Pattern-3 uses case-sensitive repo keys: always canonicalize.
        observations.append({"repository": canonical_repo, "category": category,
                             "code": code, "message": test_key, "occurrences": 1})
        source_refs.append({"repository": canonical_repo, "source_sha": sha,
                            "workflow_run_id": run_id, "test_key": test_key,
                            "evidence_sha256": row["evidence_sha256"],
                            "run_url": row["run_url"]})

    queue = {"items": observations}
    origin_observations = existing_pattern_observations(queue)
    demand(isinstance(origin_observations, list)
           and len(origin_observations) == len(failures)
           and all(isinstance(obs, dict) and obs.get("repository") == row["repository"].casefold()
                   and obs.get("count") == 1
                   and isinstance(obs.get("signature"), str)
                   for obs, row in zip(origin_observations, failures)),
           "CANONICAL_PATTERN_OBSERVATIONS_DRIFT")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for original, ref in zip(origin_observations, source_refs):
        grouped.setdefault(original["signature"], []).append(ref)

    pattern3 = existing_pattern3_builder(queue)
    demand(isinstance(pattern3, dict)
           and pattern3.get("schema_version") == 1
           and pattern3.get("record_type") == "PATTERN3_DISCOVERY_V57C"
           and pattern3.get("authority") == "PROPOSAL_ONLY"
           and pattern3.get("threshold") == 3
           and isinstance(pattern3.get("candidates"), list),
           "PATTERN3_CANONICAL_CONTRACT_INVALID")
    package = existing_feedback_packager(pattern3, read_only_reuse_catalog)
    demand(isinstance(package, dict)
           and package.get("record_type") == "FACTORY_FEEDBACK_PACKAGE_V58D"
           and package.get("authority") == "PROPOSAL_ONLY"
           and isinstance(package.get("packages"), list)
           and package.get("guardrails", {}).get("can_promote_golden") is False,
           "FEEDBACK_PACKAGER_CONTRACT_INVALID")
    candidates = []
    package_by_sig = {}
    for item in package["packages"]:
        demand(isinstance(item, dict) and isinstance(item.get("signature"), str)
               and item["signature"] not in package_by_sig
               and item.get("promotion_evidence", {}).get("auto_promote") is False,
               "FEEDBACK_PACKAGE_DUPLICATE_OR_UNSAFE")
        package_by_sig[item["signature"]] = item
    for item in pattern3["candidates"]:
        signature = item.get("signature") if isinstance(item, dict) else None
        evidence = grouped.get(signature, [])
        demand(isinstance(signature, str) and signature in package_by_sig
               and len(evidence) >= 3
               and item.get("occurrences") == len(evidence)
               and item.get("auto_promote") is False
               and item.get("review_required") is True,
               "PATTERN3_THRESHOLD_OR_PROVENANCE_DRIFT")
        package_item = package_by_sig[signature]
        candidates.append({
            "signature": signature, "occurrences": len(evidence),
            "suggested_classification": item["suggested_classification"],
            "source_references": evidence, "packaged_donor_provenance": package_item["donor_provenance"],
            "replay_plan": {"state": "NOT_EXECUTED", "requires_same_source_or_reviewed_new_sha": True,
                            "requires_independent_verified_test_run": True,
                            "tests": sorted({r["test_key"] for r in evidence})},
            "proposed_only": True, "golden_admission": "NOT_GRANTED",
        })
    demand(len(package_by_sig) == len(candidates), "FEEDBACK_PACKAGE_MISMATCH")
    digest = hashlib.sha256(json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "record_type": "X10_FAILURE_DONOR_REPLAY_INTAKE",
        "authority": "PROPOSAL_ONLY",
        "state": "CANDIDATES_REVIEW_REQUIRED" if candidates else "PATTERN_BELOW_THRESHOLD",
        "candidate_count": len(candidates), "candidates": candidates,
        "evidence_digest": digest, "source_receipt_count": len(failures),
        "existing_pattern3_reused": True, "existing_feedback_packager_reused": True,
        "replay_verified": False, "donor_promoted": False,
        "golden_promoted": False, "user_app_modified": False,
        "runtime_failure_reproduced": False,
    }
