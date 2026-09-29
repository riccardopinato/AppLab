#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import app_intelligence
import audit_orchestrator
import behavioral_product_lab
import decision_brief
import evidence_calibration
import evidence_confidence_engine
import product_contract_audit
import state_edge_case_lab
import trusted_evidence_manifest
from product_review_common import find_json, write_report

SCHEMA_VERSION = 2
PLATFORM_VERSION = "3.2.0"


def build_review(
    repo_root: Path,
    runtime_evidence_root: Path | None,
    max_files: int = 3500,
    evidence_trust: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trust = evidence_trust or {"trusted": False, "state": "NOT_PROVIDED"}
    runtime_trusted = bool(trust.get("trusted"))
    effective_runtime_root = runtime_evidence_root if runtime_trusted else None

    app = app_intelligence.build_report(repo_root, max_files, 800_000)
    crawl_path, crawl = find_json(effective_runtime_root, ["interaction-crawl.json"])

    behavioral = behavioral_product_lab.build_report(
        app,
        crawl,
        str(crawl_path) if crawl_path else None,
        effective_runtime_root,
    )
    states = state_edge_case_lab.build_report(app, effective_runtime_root)
    calibration = evidence_calibration.build_report(app, behavioral, states)
    contract = product_contract_audit.build_report(repo_root, app, behavioral, states)
    evidence_confidence = evidence_confidence_engine.build_report(
        app, behavioral, states, calibration, contract, trust
    )
    brief = decision_brief.build_report(calibration, contract, app)
    audit = audit_orchestrator.build_plan(app, has_market_evidence=False)

    runtime_state = str(behavioral.get("runtime_evidence_state", "NOT_OBSERVED"))
    observed_states = int((states.get("summary") or {}).get("observed", 0))
    applicable_states = int((states.get("summary") or {}).get("applicable", 0))
    fix_now = len((brief.get("buckets") or {}).get("FIX_NOW", []))
    verify_next = len((brief.get("buckets") or {}).get("VERIFY_NEXT", []))

    contradiction_count = int(
        (evidence_confidence.get("summary") or {}).get("contradiction_count", 0) or 0
    )

    if not runtime_trusted:
        review_state = "EVIDENCE_INCOMPLETE"
    elif fix_now:
        review_state = "ATTENTION_REQUIRED"
    elif runtime_state == "NOT_OBSERVED":
        review_state = "EVIDENCE_INCOMPLETE"
    elif contradiction_count or verify_next:
        review_state = "REVIEW_REQUIRED"
    else:
        review_state = "READY_FOR_HUMAN_REVIEW"

    return {
        "schema_version": SCHEMA_VERSION,
        "platform_version": PLATFORM_VERSION,
        "review_state": review_state,
        "runtime_evidence_trust": {
            "state": str(trust.get("state", "TRUSTED" if runtime_trusted else "NOT_PROVIDED")),
            "trusted": runtime_trusted,
            "reason": str(trust.get("reason", "")),
            "binding": trust.get("binding", {}),
            "manifest_sha256": trust.get("manifest_sha256"),
            "file_count": int(trust.get("file_count", 0) or 0),
        },
        "app_intelligence": app,
        "behavioral_product": behavioral,
        "state_edge_case": states,
        "evidence_calibration": calibration,
        "evidence_confidence": evidence_confidence,
        "product_contract": contract,
        "decision_brief": brief,
        "audit_plan": audit,
        "summary": {
            "runtime_evidence_state": runtime_state,
            "runtime_evidence_trusted": runtime_trusted,
            "applicable_states": applicable_states,
            "observed_states": observed_states,
            "fix_now": fix_now,
            "verify_next": verify_next,
            "improve": len((brief.get("buckets") or {}).get("IMPROVE", [])),
            "no_action": len((brief.get("buckets") or {}).get("NO_ACTION", [])),
            "selected_labs": int(audit.get("selected_lab_count", 0) or 0),
            "calibrated_findings": int((calibration.get("summary") or {}).get("total", 0) or 0),
            "runtime_confirmed_findings": int((calibration.get("summary") or {}).get("runtime_confirmed", 0) or 0),
            "runtime_contradicted_findings": int((calibration.get("summary") or {}).get("runtime_contradicted", 0) or 0),
            "evidence_claims": int((evidence_confidence.get("summary") or {}).get("total_claims", 0) or 0),
            "evidence_confirmed": int((evidence_confidence.get("summary") or {}).get("confirmed", 0) or 0),
            "evidence_corroborated": int((evidence_confidence.get("summary") or {}).get("corroborated", 0) or 0),
            "evidence_contradicted": int((evidence_confidence.get("summary") or {}).get("contradicted", 0) or 0),
            "evidence_unverified": int((evidence_confidence.get("summary") or {}).get("unverified", 0) or 0),
            "evidence_stale": int((evidence_confidence.get("summary") or {}).get("stale", 0) or 0),
            "evidence_contradictions": contradiction_count,
            "contract_review_signals": int((contract.get("summary") or {}).get("review_signals", 0) or 0),
        },
        "guardrails": {
            "runtime_requires_trusted_manifest": True,
            "untrusted_runtime_is_ignored": True,
            "review_state_is_not_release_verdict": True,
            "runtime_absence_never_becomes_pass": True,
            "certification_remains_independent": True,
            "target_repository_read_only": True,
            "no_numeric_quality_score": True,
        },
    }


def write_full(review: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = [
        ("app-intelligence", review["app_intelligence"], app_intelligence.markdown(review["app_intelligence"])),
        ("behavioral-product", review["behavioral_product"], behavioral_product_lab.markdown(review["behavioral_product"])),
        ("state-edge-case", review["state_edge_case"], state_edge_case_lab.markdown(review["state_edge_case"])),
        ("evidence-calibration", review["evidence_calibration"], evidence_calibration.markdown(review["evidence_calibration"])),
        ("evidence-confidence", review["evidence_confidence"], evidence_confidence_engine.markdown(review["evidence_confidence"])),
        ("product-contract-audit", review["product_contract"], product_contract_audit.markdown(review["product_contract"])),
        ("decision-brief", review["decision_brief"], decision_brief.markdown(review["decision_brief"])),
    ]
    for stem, payload, markdown in sections:
        write_report(output_dir, stem, payload, markdown)

    (output_dir / "audit-plan.json").write_text(
        json.dumps(review["audit_plan"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary = review["summary"]
    trust = review["runtime_evidence_trust"]
    lines = [
        "# AppLab v3.2 — Evidence-Aware Autonomous App Review",
        "",
        f"- Review state: **{review['review_state']}**",
        f"- Runtime trust: **{trust['state']}**",
        f"- Runtime evidence: **{summary['runtime_evidence_state']}**",
        f"- Edge states observed: **{summary['observed_states']}/{summary['applicable_states']}**",
        f"- Runtime-confirmed findings: **{summary['runtime_confirmed_findings']}**",
        f"- Runtime-contradicted findings: **{summary['runtime_contradicted_findings']}**",
        f"- Evidence claims: **{summary['evidence_claims']}**",
        f"- Evidence contradictions: **{summary['evidence_contradictions']}**",
        f"- Unverified evidence claims: **{summary['evidence_unverified']}**",
        f"- Fix now: **{summary['fix_now']}**",
        f"- Verify next: **{summary['verify_next']}**",
        f"- Selected specialist labs: **{summary['selected_labs']}**",
        "",
        "## Decision Brief",
        "",
        decision_brief.markdown(review["decision_brief"]),
        "",
        "## Trust Boundary",
        "",
        "Runtime evidence is consumed only after Trusted Evidence Manifest validation.",
        "Unbound or tampered runtime evidence is ignored or rejected by strict callers.",
        "This review state is advisory and is not a release verdict.",
        "FAST/FULL runtime verification and CERTIFICATION remain authoritative.",
    ]
    write_report(
        output_dir,
        "autonomous-review",
        {
            key: value
            for key, value in review.items()
            if key
            not in {
                "app_intelligence",
                "behavioral_product",
                "state_edge_case",
                "evidence_calibration",
                "evidence_confidence",
                "product_contract",
                "decision_brief",
                "audit_plan",
            }
        },
        "\n".join(lines),
    )


def validate_runtime(
    runtime_root: Path | None,
    *,
    expected_repository: str | None,
    expected_sha: str | None,
    expected_run_id: str | None,
    require_trusted: bool,
) -> tuple[Path | None, dict[str, Any]]:
    if runtime_root is None:
        if require_trusted:
            raise trusted_evidence_manifest.EvidenceError(
                "Trusted runtime evidence is required but was not provided"
            )
        return None, {"trusted": False, "state": "NOT_PROVIDED"}

    if not expected_repository or not expected_sha:
        if require_trusted:
            raise trusted_evidence_manifest.EvidenceError(
                "Expected repository and SHA are required to bind runtime evidence"
            )
        return None, {
            "trusted": False,
            "state": "REJECTED",
            "reason": "Missing expected repository/SHA binding.",
        }

    try:
        checked = trusted_evidence_manifest.validate_manifest(
            runtime_root,
            expected_repository=expected_repository,
            expected_sha=expected_sha,
            expected_run_id=expected_run_id,
        )
    except trusted_evidence_manifest.EvidenceError as exc:
        if require_trusted:
            raise
        return None, {
            "trusted": False,
            "state": "REJECTED",
            "reason": str(exc),
        }

    checked["state"] = "TRUSTED"
    checked["reason"] = ""
    return runtime_root, checked


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        root = base / "target"
        root.mkdir()
        (root / "README.md").write_text(
            "# Demo\nAuthentication is implemented.\n",
            encoding="utf-8",
        )
        (root / "lib").mkdir()
        (root / "lib" / "home_screen.dart").write_text(
            "class HomeScreen {}\n",
            encoding="utf-8",
        )

        evidence = base / "evidence"
        evidence.mkdir()
        crawl_dir = evidence / "interaction-crawl"
        crawl_dir.mkdir()
        (crawl_dir / "01-after.xml").write_text(
            '<hierarchy><node text="Home" content-desc="Home"/></hierarchy>',
            encoding="utf-8",
        )
        (evidence / "interaction-crawl.json").write_text(
            json.dumps(
                {
                    "result": "PASS",
                    "actions": [
                        {
                            "label": "Home",
                            "status": "CHANGED",
                            "state_changed": True,
                            "ui_hierarchy": "interaction-crawl/01-after.xml",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        sha = "a" * 40
        (evidence / "result.json").write_text(
            json.dumps(
                {
                    "repository": "owner/demo",
                    "resolved_sha": sha,
                    "workflow_run_id": "12345",
                    "package_id": "com.example.demo",
                    "result": "PASS",
                    "pipeline_status": "success",
                }
            ),
            encoding="utf-8",
        )
        (evidence / "build-contract.json").write_text(
            json.dumps(
                {
                    "repository": "owner/demo",
                    "resolved_sha": sha,
                    "package_id": "com.example.demo",
                }
            ),
            encoding="utf-8",
        )
        trusted_evidence_manifest.create_manifest(
            evidence,
            repository="owner/demo",
            resolved_sha=sha,
            run_id="12345",
            analysis_mode="full",
            contract_fingerprint="contract",
            config_fingerprint="config",
            trusted_applab_sha="b" * 40,
        )
        runtime_root, trust = validate_runtime(
            evidence,
            expected_repository="owner/demo",
            expected_sha=sha,
            expected_run_id="12345",
            require_trusted=True,
        )
        review = build_review(root, runtime_root, 100, trust)
        assert review["platform_version"] == "3.2.0"
        assert review["summary"]["runtime_evidence_trusted"] is True
        assert review["summary"]["evidence_claims"] >= 1
        assert "evidence_confidence" in review
        assert review["runtime_evidence_trust"]["state"] == "TRUSTED"

        untrusted = build_review(root, evidence, 100, {"trusted": False, "state": "REJECTED"})
        assert untrusted["review_state"] == "EVIDENCE_INCOMPLETE"
        assert untrusted["summary"]["runtime_evidence_state"] == "NOT_OBSERVED"

        out = base / "out"
        write_full(review, out)
        assert (out / "autonomous-review.json").is_file()
        assert (out / "decision-brief.json").is_file()
    print("AppLab Autonomous App Review v3.1 self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--runtime-evidence-dir")
    parser.add_argument("--expected-repository")
    parser.add_argument("--expected-sha")
    parser.add_argument("--expected-run-id")
    parser.add_argument("--require-trusted-runtime", action="store_true")
    parser.add_argument("--output-dir", default="applab-autonomous-review")
    parser.add_argument("--max-files", type=int, default=3500)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.repo_root:
        raise SystemExit("--repo-root is required")

    root = Path(args.repo_root)
    if not root.is_dir():
        raise SystemExit("repo root does not exist")

    runtime_input = Path(args.runtime_evidence_dir) if args.runtime_evidence_dir else None
    try:
        runtime_root, trust = validate_runtime(
            runtime_input,
            expected_repository=args.expected_repository,
            expected_sha=args.expected_sha,
            expected_run_id=args.expected_run_id,
            require_trusted=args.require_trusted_runtime,
        )
    except trusted_evidence_manifest.EvidenceError as exc:
        raise SystemExit(f"Trusted runtime evidence rejected: {exc}") from exc

    review = build_review(
        root,
        runtime_root,
        max(1, min(args.max_files, 10000)),
        trust,
    )
    write_full(review, Path(args.output_dir))
    print(
        json.dumps(
            {
                "platform_version": PLATFORM_VERSION,
                "review_state": review["review_state"],
                **review["summary"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
