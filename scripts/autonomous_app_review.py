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
import product_contract_audit
import state_edge_case_lab
from product_review_common import find_json, load_json, write_report

SCHEMA_VERSION=1
PLATFORM_VERSION="3.0.0"


def build_review(repo_root:Path, runtime_evidence_root:Path|None, max_files:int=3500)->dict[str,Any]:
    app=app_intelligence.build_report(repo_root,max_files,800_000)
    _,crawl=find_json(runtime_evidence_root,["interaction-crawl.json"])
    crawl_path=None
    if runtime_evidence_root:
        cp,_=find_json(runtime_evidence_root,["interaction-crawl.json"])
        crawl_path=str(cp) if cp else None

    behavioral=behavioral_product_lab.build_report(app,crawl,crawl_path)
    states=state_edge_case_lab.build_report(app,runtime_evidence_root)
    calibration=evidence_calibration.build_report(app,behavioral,states)
    contract=product_contract_audit.build_report(repo_root,app,behavioral,states)
    brief=decision_brief.build_report(calibration,contract,app)
    audit=audit_orchestrator.build_plan(app,has_market_evidence=False)

    runtime_state=str(behavioral.get("runtime_evidence_state","NOT_OBSERVED"))
    observed_states=int((states.get("summary") or {}).get("observed",0))
    applicable_states=int((states.get("summary") or {}).get("applicable",0))
    fix_now=len((brief.get("buckets") or {}).get("FIX_NOW",[]))
    verify_next=len((brief.get("buckets") or {}).get("VERIFY_NEXT",[]))

    if fix_now:
        review_state="ATTENTION_REQUIRED"
    elif runtime_state=="NOT_OBSERVED":
        review_state="EVIDENCE_INCOMPLETE"
    elif verify_next:
        review_state="REVIEW_REQUIRED"
    else:
        review_state="READY_FOR_HUMAN_REVIEW"

    return {
        "schema_version":SCHEMA_VERSION,
        "platform_version":PLATFORM_VERSION,
        "review_state":review_state,
        "app_intelligence":app,
        "behavioral_product":behavioral,
        "state_edge_case":states,
        "evidence_calibration":calibration,
        "product_contract":contract,
        "decision_brief":brief,
        "audit_plan":audit,
        "summary":{
            "runtime_evidence_state":runtime_state,
            "applicable_states":applicable_states,
            "observed_states":observed_states,
            "fix_now":fix_now,
            "verify_next":verify_next,
            "improve":len((brief.get("buckets") or {}).get("IMPROVE",[])),
            "no_action":len((brief.get("buckets") or {}).get("NO_ACTION",[])),
            "selected_labs":int(audit.get("selected_lab_count",0) or 0),
            "calibrated_findings":int((calibration.get("summary") or {}).get("total",0) or 0),
            "contract_review_signals":int((contract.get("summary") or {}).get("review_signals",0) or 0),
        },
        "guardrails":{
            "review_state_is_not_release_verdict":True,
            "runtime_absence_never_becomes_pass":True,
            "certification_remains_independent":True,
            "target_repository_read_only":True,
            "no_numeric_quality_score":True,
        },
    }


def write_full(review:dict[str,Any],output_dir:Path)->None:
    output_dir.mkdir(parents=True,exist_ok=True)
    sections=[
        ("app-intelligence",review["app_intelligence"],app_intelligence.markdown(review["app_intelligence"])),
        ("behavioral-product",review["behavioral_product"],behavioral_product_lab.markdown(review["behavioral_product"])),
        ("state-edge-case",review["state_edge_case"],state_edge_case_lab.markdown(review["state_edge_case"])),
        ("evidence-calibration",review["evidence_calibration"],evidence_calibration.markdown(review["evidence_calibration"])),
        ("product-contract-audit",review["product_contract"],product_contract_audit.markdown(review["product_contract"])),
        ("decision-brief",review["decision_brief"],decision_brief.markdown(review["decision_brief"])),
    ]
    for stem,payload,md in sections:
        write_report(output_dir,stem,payload,md)
    (output_dir/"audit-plan.json").write_text(json.dumps(review["audit_plan"],indent=2,sort_keys=True)+"\n",encoding="utf-8")
    summary=review["summary"]
    lines=[
        "# AppLab v3.0 — Autonomous App Review","",
        f"- Review state: **{review['review_state']}**",
        f"- Runtime evidence: **{summary['runtime_evidence_state']}**",
        f"- Edge states observed: **{summary['observed_states']}/{summary['applicable_states']}**",
        f"- Fix now: **{summary['fix_now']}**",
        f"- Verify next: **{summary['verify_next']}**",
        f"- Selected specialist labs: **{summary['selected_labs']}**","",
        "## Decision Brief","",
        decision_brief.markdown(review["decision_brief"]),
        "",
        "## Trust Boundary","",
        "This review state is advisory and is not a release verdict.",
        "FAST/FULL runtime verification and CERTIFICATION remain authoritative.",
    ]
    write_report(output_dir,"autonomous-review",{
        k:v for k,v in review.items() if k not in {
            "app_intelligence","behavioral_product","state_edge_case",
            "evidence_calibration","product_contract","decision_brief","audit_plan"
        }
    },"\n".join(lines))


def self_test()->None:
    with tempfile.TemporaryDirectory() as raw:
        root=Path(raw)/"target"; root.mkdir()
        (root/"README.md").write_text("# Demo\nAuthentication feature.\n",encoding="utf-8")
        (root/"lib").mkdir()
        (root/"lib"/"home_screen.dart").write_text("class HomeScreen {}\n",encoding="utf-8")
        evidence=Path(raw)/"evidence"; evidence.mkdir()
        (evidence/"interaction-crawl.json").write_text(json.dumps({"result":"PASS","actions":[{"label":"Home","status":"CHANGED","state_changed":True}]}),encoding="utf-8")
        review=build_review(root,evidence,100)
        assert review["platform_version"]=="3.0.0"
        assert review["summary"]["runtime_evidence_state"]=="OBSERVED_PASS"
        out=Path(raw)/"out"; write_full(review,out)
        assert (out/"autonomous-review.json").is_file()
        assert (out/"decision-brief.json").is_file()
    print("AppLab Autonomous App Review v3.0 self-test PASS")


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--repo-root")
    p.add_argument("--runtime-evidence-dir")
    p.add_argument("--output-dir",default="applab-autonomous-review")
    p.add_argument("--max-files",type=int,default=3500)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.repo_root: raise SystemExit("--repo-root is required")
    root=Path(a.repo_root)
    if not root.is_dir(): raise SystemExit("repo root does not exist")
    evidence=Path(a.runtime_evidence_dir) if a.runtime_evidence_dir else None
    review=build_review(root,evidence,max(1,min(a.max_files,10000)))
    write_full(review,Path(a.output_dir))
    print(json.dumps({"platform_version":PLATFORM_VERSION,"review_state":review["review_state"],**review["summary"]}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
