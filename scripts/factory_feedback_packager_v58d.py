#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_packages(pattern3: dict[str, Any], reuse: dict[str, Any]) -> dict[str, Any]:
    reuse_by_repo = {
        str(item.get("repository", "")): item
        for item in reuse.get("repositories", [])
        if isinstance(item, dict)
    }
    packages = []
    for candidate in pattern3.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        repos = [str(x) for x in candidate.get("repositories", []) if str(x)]
        suggested = str(candidate.get("suggested_classification", "DONOR"))
        compatible = []
        for repo in repos:
            for item in reuse_by_repo.get(repo, {}).get("candidates", []):
                if isinstance(item, dict):
                    compatible.append({
                        "repository": repo,
                        "id": item.get("id"),
                        "status": item.get("status"),
                        "path": item.get("path"),
                    })
        packages.append({
            "signature": candidate.get("signature"),
            "occurrences": int(candidate.get("occurrences", 0) or 0),
            "repositories": repos,
            "suggested_classification": suggested,
            "donor_provenance": {
                "repositories": repos,
                "evidence_signature": candidate.get("signature"),
            },
            "generalization": {
                "invariants_required": True,
                "app_specific_details_must_be_removed": True,
                "existing_factory_candidates": compatible,
            },
            "contract_candidate": {
                "required": suggested in {"FACTORY PROCESS", "GOLDEN CANDIDATE"},
                "status": "DRAFT_REQUIRED",
            },
            "promotion_evidence": {
                "independent_pilot_required": True,
                "exact_head_validation_required": True,
                "auto_promote": False,
            },
        })
    return {
        "schema_version": 1,
        "record_type": "FACTORY_FEEDBACK_PACKAGE_V58D",
        "authority": "PROPOSAL_ONLY",
        "packages": packages,
        "guardrails": {
            "can_modify_core": False,
            "can_promote_golden": False,
            "can_mark_certified": False,
        },
    }


def self_test() -> None:
    pattern = {
        "candidates": [{
            "signature": "INFRA|TIMEOUT|same",
            "occurrences": 4,
            "repositories": ["owner/a", "owner/b"],
            "suggested_classification": "FACTORY PROCESS",
        }]
    }
    reuse = {
        "repositories": [{
            "repository": "owner/a",
            "candidates": [{"id": "applab_qa_certification", "status": "CERTIFIED PROCESS", "path": "x"}],
        }]
    }
    report = build_packages(pattern, reuse)
    assert len(report["packages"]) == 1
    pkg = report["packages"][0]
    assert pkg["contract_candidate"]["required"] is True
    assert pkg["promotion_evidence"]["auto_promote"] is False
    assert report["guardrails"]["can_modify_core"] is False
    print("AppLab v5.8D Factory feedback packager self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pattern3", default="")
    p.add_argument("--reuse-plan", default="")
    p.add_argument("--output", default="")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if not a.pattern3 or not a.reuse_plan:
        raise SystemExit("--pattern3 and --reuse-plan are required")
    pattern = json.loads(Path(a.pattern3).read_text(encoding="utf-8"))
    reuse = json.loads(Path(a.reuse_plan).read_text(encoding="utf-8"))
    report = build_packages(pattern, reuse)
    if a.output:
        Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
