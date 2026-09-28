#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_review_common import load_json, write_report

SCHEMA_VERSION=1
LAB_VERSION="2.9.0"


def _tokens(*values:str)->set[str]:
    import re
    result=set()
    for value in values:
        result.update(x for x in re.findall(r"[a-z0-9]{3,}", value.lower()) if x not in {"review","possible","candidate","static","runtime"})
    return result


def build_report(app:dict[str,Any], behavioral:dict[str,Any]|None, states:dict[str,Any]|None)->dict[str,Any]:
    consistency=app.get("product_consistency") if isinstance(app.get("product_consistency"),dict) else {}
    static_findings=consistency.get("findings") if isinstance(consistency.get("findings"),list) else []
    behavioral=behavioral or {}
    states=states or {}

    matched_ids={str(x.get("id","")) for x in behavioral.get("runtime_matched_surfaces",[]) if isinstance(x,dict)}
    runtime_findings=[x for x in behavioral.get("findings",[]) if isinstance(x,dict)]
    state_findings=[x for x in states.get("findings",[]) if isinstance(x,dict)]
    runtime_all=runtime_findings+state_findings

    calibrated=[]
    for row in static_findings:
        if not isinstance(row,dict):
            continue
        item=dict(row)
        item["evidence_class"]="STATIC_HEURISTIC"
        item["runtime_relation"]="NOT_OBSERVED"
        item["recommended_disposition"]="VERIFY"

        subject=str(row.get("subject",""))
        kind=str(row.get("kind",""))
        static_tokens=_tokens(subject,kind,str(row.get("message","")))

        if kind=="ORPHAN_SURFACE_CANDIDATE" and subject in matched_ids:
            item["evidence_class"]="RUNTIME_CONTRADICTED"
            item["runtime_relation"]="CONTRADICTED"
            item["recommended_disposition"]="NO_ACTION"
        else:
            for runtime in runtime_all:
                runtime_tokens=_tokens(
                    str(runtime.get("subject","")),
                    str(runtime.get("state","")),
                    str(runtime.get("kind","")),
                    str(runtime.get("message","")),
                )
                overlap=static_tokens & runtime_tokens
                if not overlap:
                    continue
                sev=str(runtime.get("severity","")).upper()
                if sev=="HIGH_REVIEW":
                    item["evidence_class"]="RUNTIME_CORROBORATED"
                    item["runtime_relation"]="CORROBORATED"
                    item["recommended_disposition"]="FIX_OR_REPRODUCE"
                    break
                if item["evidence_class"]=="STATIC_HEURISTIC":
                    item["evidence_class"]="STATIC_CORROBORATED"
                    item["runtime_relation"]="PARTIAL"
                    item["recommended_disposition"]="VERIFY_NEXT"

        calibrated.append(item)

    for runtime in runtime_all:
        sev=str(runtime.get("severity","")).upper()
        if sev not in {"HIGH_REVIEW","REVIEW"}:
            continue
        calibrated.append({
            "id":f"runtime::{runtime.get('kind','runtime')}::{runtime.get('subject',runtime.get('state',''))}",
            "domain":"runtime",
            "kind":str(runtime.get("kind","RUNTIME_REVIEW")),
            "severity":sev,
            "confidence":"HIGH" if sev=="HIGH_REVIEW" else str(runtime.get("confidence","MEDIUM")),
            "subject":str(runtime.get("subject",runtime.get("state",""))),
            "message":str(runtime.get("message","Runtime evidence requires review.")),
            "evidence":runtime.get("evidence",[]),
            "evidence_class":"RUNTIME_CONFIRMED",
            "runtime_relation":"DIRECT",
            "recommended_disposition":"FIX_OR_REPRODUCE" if sev=="HIGH_REVIEW" else "VERIFY_NEXT",
        })

    order={"RUNTIME_CONFIRMED":0,"RUNTIME_CORROBORATED":1,"STATIC_CORROBORATED":2,"STATIC_HEURISTIC":3,"RUNTIME_CONTRADICTED":4}
    calibrated.sort(key=lambda x:(order.get(str(x.get("evidence_class")),9),str(x.get("severity","")),str(x.get("domain","")),str(x.get("kind",""))))
    counts={}
    for row in calibrated:
        key=str(row.get("evidence_class","UNKNOWN"))
        counts[key]=counts.get(key,0)+1

    return {
        "schema_version":SCHEMA_VERSION,
        "lab_version":LAB_VERSION,
        "calibrated_findings":calibrated,
        "summary":{
            "total":len(calibrated),
            "by_evidence_class":dict(sorted(counts.items())),
            "runtime_confirmed":counts.get("RUNTIME_CONFIRMED",0),
            "runtime_contradicted":counts.get("RUNTIME_CONTRADICTED",0),
            "static_only":counts.get("STATIC_HEURISTIC",0),
        },
        "evidence_order":["RUNTIME_CONFIRMED","RUNTIME_CORROBORATED","STATIC_CORROBORATED","STATIC_HEURISTIC","RUNTIME_CONTRADICTED"],
        "guardrails":{"runtime_does_not_auto_pass_static_findings":True,"contradicted_findings_are_suppressed_not_deleted":True,"no_numeric_quality_score":True,"no_certification_override":True},
    }


def markdown(r:dict[str,Any])->str:
    lines=["# AppLab Evidence Calibration Engine","",f"- Calibrated findings: **{r['summary']['total']}**",f"- Runtime confirmed: **{r['summary']['runtime_confirmed']}**",f"- Runtime contradicted: **{r['summary']['runtime_contradicted']}**",f"- Static-only: **{r['summary']['static_only']}**",""]
    for row in r["calibrated_findings"][:30]:
        lines.append(f"- **{row['evidence_class']} / {row.get('severity','')} / {row.get('kind','')}** · {row.get('subject','')}")
    return "\n".join(lines)


def self_test()->None:
    app={"product_consistency":{"findings":[{"id":"a","domain":"product_flow","kind":"ORPHAN_SURFACE_CANDIDATE","severity":"REVIEW","subject":"lib/settings_screen.dart","message":"orphan"}]}}
    behavioral={"runtime_matched_surfaces":[{"id":"lib/settings_screen.dart"}],"findings":[{"kind":"RUNTIME_INTERACTION_FAILURE","severity":"HIGH_REVIEW","subject":"Save","message":"failure"}]}
    r=build_report(app,behavioral,{"findings":[]})
    assert any(x["evidence_class"]=="RUNTIME_CONTRADICTED" for x in r["calibrated_findings"])
    assert any(x["evidence_class"]=="RUNTIME_CONFIRMED" for x in r["calibrated_findings"])
    print("AppLab Evidence Calibration Engine self-test PASS")


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--app-intelligence")
    p.add_argument("--behavioral")
    p.add_argument("--state-edge")
    p.add_argument("--output-dir",default="applab-evidence-calibration")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test: self_test(); return 0
    app=load_json(Path(a.app_intelligence)) if a.app_intelligence else None
    if app is None: raise SystemExit("--app-intelligence is required and must be valid")
    behavioral=load_json(Path(a.behavioral)) if a.behavioral else None
    states=load_json(Path(a.state_edge)) if a.state_edge else None
    r=build_report(app,behavioral,states)
    write_report(Path(a.output_dir),"evidence-calibration",r,markdown(r))
    print(json.dumps({"lab_version":LAB_VERSION,**r["summary"]}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
