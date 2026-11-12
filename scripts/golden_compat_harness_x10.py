#!/usr/bin/env python3
"""X10-018: offline Golden package/consumer/rollback compatibility gate.

Evaluates structured evidence against X10-017's pinned candidate manifest.
Reports are untrusted until CI provenance is independently checked; this
module never promotes a Golden, publishes a package, or executes Flutter.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
REPO = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
KINDS = {"DONOR", "CONSUMER", "ROLLBACK"}


def _version(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError("UNPINNED_SEMVER")
    return tuple(int(part) for part in value.split("."))


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def assess(manifest: dict[str, Any], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail closed on missing donor/consumer/rollback evidence.

    A structural acceptance is NOT independent CI verification. Trusted CI
    URLs, SHA and test outcome must be checked separately by a reviewer.
    """
    _require(isinstance(manifest, dict) and isinstance(receipts, list), "INVALID_INPUT")
    state = manifest.get("package_state")
    _require(state in {"SOURCE_EXTRACTED", "PACKAGE_TESTED",
                       "CONSUMER_VERIFIED", "CERTIFIED_MULTI_CONSUMER"}, "SOURCE_NOT_EXTRACTED")
    version = manifest.get("version")
    _version(version)
    golden = manifest.get("golden", {})
    provenance = manifest.get("provenance", {})
    compatibility = manifest.get("compatibility", {})
    tests = manifest.get("tests", {})
    release = manifest.get("release", {})
    _require(isinstance(golden, dict) and isinstance(provenance, dict)
             and isinstance(compatibility, dict) and isinstance(tests, dict)
             and isinstance(release, dict), "MANIFEST_SHAPE")
    factory_sha = manifest.get("factory_sha")
    donor_sha = provenance.get("donor_sha")
    _require(isinstance(factory_sha, str) and SHA.fullmatch(factory_sha) is not None
             and golden.get("registry_sha") == factory_sha
             and isinstance(donor_sha, str) and SHA.fullmatch(donor_sha) is not None,
             "SOURCE_NOT_PINNED")
    _require(isinstance(provenance.get("source_files"), list)
             and bool(provenance["source_files"])
             and manifest.get("license") in {"INTERNAL_APPROVED", "SPDX_VERIFIED"},
             "SOURCE_OR_LICENSE_NOT_ADMITTED")
    _require(isinstance(compatibility.get("tested_pairs"), list)
             and bool(compatibility["tested_pairs"]), "SDK_MATRIX_MISSING")
    _require(isinstance(tests.get("donor_ci_urls"), list) and bool(tests["donor_ci_urls"])
             and isinstance(tests.get("consumer_ci_urls"), list),
             "TEST_LEDGER_MISSING")
    _require(release.get("publish_authorized") is False, "PUBLISH_NOT_AUTHORIZED_BY_HARNESS")
    _require(isinstance(manifest.get("package_name"), str) and manifest["package_name"],
             "PACKAGE_NAME_MISSING")

    declared_consumers = manifest.get("consumers")
    _require(isinstance(declared_consumers, list), "CONSUMER_MATRIX_INVALID")
    declared = {}
    for consumer in declared_consumers:
        _require(isinstance(consumer, dict) and isinstance(consumer.get("repo"), str)
                 and REPO.fullmatch(consumer["repo"]) is not None
                 and isinstance(consumer.get("source_sha"), str)
                 and SHA.fullmatch(consumer["source_sha"]) is not None
                 and consumer.get("approved") is True and isinstance(consumer.get("test_url"), str),
                 "CONSUMER_NOT_APPROVED")
        # GitHub owner/repository identities are case-insensitive.
        normalized_repo = consumer["repo"].casefold()
        _require(normalized_repo not in declared, "DUPLICATE_CONSUMER")
        declared[normalized_repo] = consumer

    seen = set()
    counts = {"DONOR": 0, "CONSUMER": 0, "ROLLBACK": 0}
    for row in receipts:
        _require(isinstance(row, dict) and row.get("kind") in KINDS,
                 "UNSUPPORTED_RECEIPT")
        kind, repo, source_sha = row["kind"], row.get("repository"), row.get("source_sha")
        _require(isinstance(repo, str) and REPO.fullmatch(repo) is not None
                 and isinstance(source_sha, str) and SHA.fullmatch(source_sha) is not None,
                 "INVALID_RECEIPT_SOURCE")
        _require(row.get("package_name") == manifest["package_name"]
                 and row.get("version") == version and row.get("result") == "PASS"
                 and isinstance(row.get("run_url"), str)
                 and row["run_url"].startswith("https://github.com/")
                 and "/actions/runs/" in row["run_url"], "NO_MATCHING_PASS")
        key = (kind, repo.casefold())
        _require(key not in seen, "DUPLICATE_RECEIPT")
        seen.add(key)
        if kind == "DONOR":
            _require(repo.casefold() == str(provenance.get("donor_repo", "")).casefold() and source_sha == donor_sha
                     and row["run_url"] in tests["donor_ci_urls"], "DONOR_MISMATCH")
        elif kind == "CONSUMER":
            c = declared.get(repo.casefold())
            _require(c is not None and source_sha == c["source_sha"]
                     and row["run_url"] == c["test_url"]
                     and row["run_url"] in tests["consumer_ci_urls"], "CONSUMER_MISMATCH")
        else:
            rollback_version = release.get("rollback_version")
            _require(isinstance(rollback_version, str) and
                     _version(rollback_version) < _version(version)
                     and row.get("to_version") == rollback_version
                     and row.get("from_version") == version
                     and source_sha == donor_sha
                     and repo.casefold() == str(provenance.get("donor_repo", "")).casefold(), "ROLLBACK_MISMATCH")
        pair = (row.get("dart"), row.get("flutter"))
        _require(all(isinstance(v, str) and VERSION.fullmatch(v) is not None for v in pair),
                 "SDK_VERSION_MISSING")
        _require(any(isinstance(p, dict)
                     and all(isinstance(p.get(v), str) and VERSION.fullmatch(p[v]) is not None
                             for v in ("dart", "flutter"))
                     and pair == (p["dart"], p["flutter"])
                     and p.get("test_url") == row["run_url"]
                     for p in compatibility["tested_pairs"]), "SDK_PAIR_NOT_RECORDED")
        counts[kind] += 1

    _require(counts["DONOR"] == 1, "DONOR_TEST_MISSING")
    _require(counts["CONSUMER"] == len(declared) and counts["CONSUMER"] >= 1,
             "CONSUMER_TEST_MISSING")
    _require(counts["ROLLBACK"] == 1, "ROLLBACK_TEST_MISSING")
    if state == "CERTIFIED_MULTI_CONSUMER":
        _require(counts["CONSUMER"] >= 2, "TWO_CONSUMERS_REQUIRED")
    return {"state": "STRUCTURAL_PASS_REVIEW_REQUIRED", "package": manifest["package_name"],
            "version": version, "counts": counts, "automatic_promotion": False,
            "flutter_executed": False, "receipt_provenance_verified": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    receipts = json.loads(args.receipts.read_text(encoding="utf-8"))
    print(json.dumps(assess(manifest, receipts), sort_keys=True))


if __name__ == "__main__":
    main()
