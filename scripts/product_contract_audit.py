#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from product_review_common import bounded_text_files, load_json, write_report

SCHEMA_VERSION=1
LAB_VERSION="2.10.0"

ALIASES={
    "authentication":("authentication","auth","login","sign in","account"),
    "local_persistence":("local persistence","offline-first","offline first","database","room","sqlite","drift"),
    "network_api":("network api","api","backend","server"),
    "background_execution":("background","workmanager","foreground service"),
    "notifications":("notification","notifications","reminder","push"),
    "monetization":("premium","subscription","revenuecat","billing","iap","admob"),
    "ai_or_ml":("ai","artificial intelligence","llm","machine learning","gemini","openai"),
    "export_or_backup":("export","backup","restore"),
    "maps_or_location":("maps","map","location","gps","geolocation"),
    "cloud_or_sync":("sync","cloud","firebase","supabase"),
}


def docs(root:Path)->list[tuple[Path,str]]:
    names=["README.md","ROADMAP.md","PRODUCT_BIBLE.md","PRODUCT_BIBLE.txt","FEATURES.md","FEATURES.txt","PROJECT_STATE.md"]
    return bounded_text_files(root,names)


def mentioned(text:str,label:str)->bool:
    terms=ALIASES.get(label,(label.replace("_"," "),label))
    lower=text.lower()
    return any(re.search(rf"\b{re.escape(term.lower())}\b",lower) for term in terms)


def build_report(root:Path, app:dict[str,Any], behavioral:dict[str,Any]|None, states:dict[str,Any]|None)->dict[str,Any]:
    documents=docs(root)
    joined="\n".join(text for _,text in documents)
    truth=app.get("feature_truth") if isinstance(app.get("feature_truth"),dict) else {}
    caps=truth.get("capabilities") if isinstance(truth.get("capabilities"),list) else []
    behavioral=behavioral or {}
    states=states or {}
    runtime_labels=" ".join(str(x.get("label","")) for x in behavioral.get("runtime_controls",[]) if isinstance(x,dict)).lower()

    rows=[]; findings=[]
    for cap in caps:
        if not isinstance(cap,dict):
            continue
        label=str(cap.get("capability","")).strip()
        if not label: continue
        promised=mentioned(joined,label)
        implementation=str(cap.get("truth","NOT_DETECTED"))
        reachable=any(term.lower() in runtime_labels for term in ALIASES.get(label,(label.replace("_"," "),)))
        verified="NOT_OBSERVED"
        if label in {"network_api","cloud_or_sync"}:
            verified=str((states.get("states") or {}).get("offline",{}).get("status","NOT_OBSERVED"))
        elif label=="authentication":
            verified=str((states.get("states") or {}).get("auth",{}).get("status","NOT_OBSERVED"))
        elif label=="background_execution":
            verified=str((states.get("states") or {}).get("background",{}).get("status","NOT_OBSERVED"))
        elif label=="notifications":
            verified=str((states.get("states") or {}).get("permissions",{}).get("status","NOT_OBSERVED"))
        elif behavioral:
            verified=str(behavioral.get("runtime_evidence_state","NOT_OBSERVED"))

        evidence=[str(path) for path,text in documents if mentioned(text,label)][:8]
        row={"capability":label,"promised":promised,"implementation":implementation,"runtime_reachable":"OBSERVED" if reachable else "NOT_OBSERVED","runtime_verified":verified,"contract_evidence":evidence}
        rows.append(row)

        if promised and implementation not in {"CODE_CONFIRMED","CONFIG_SIGNAL"}:
            findings.append({"kind":"PROMISED_WITHOUT_IMPLEMENTATION_EVIDENCE","severity":"HIGH_REVIEW" if implementation=="NOT_DETECTED" else "REVIEW","capability":label,"message":"Product documentation mentions this capability without strong bounded implementation evidence.","evidence":evidence})
        elif implementation=="CODE_CONFIRMED" and not promised and documents:
            findings.append({"kind":"IMPLEMENTED_WITHOUT_PRODUCT_CONTRACT","severity":"INFO","capability":label,"message":"Implementation evidence exists but the bounded product contract does not mention the capability.","evidence":cap.get("provenance",{}).get("CODE",[]) if isinstance(cap.get("provenance"),dict) else []})
        if implementation=="CODE_CONFIRMED" and verified=="NOT_OBSERVED":
            findings.append({"kind":"IMPLEMENTED_NOT_RUNTIME_VERIFIED","severity":"REVIEW","capability":label,"message":"Implementation evidence exists, but no matching bounded runtime verification was observed.","evidence":[]})

    completed=[]
    for path,text in documents:
        for line in text.splitlines():
            if re.match(r"\s*[-*]\s*\[[xX]\]\s+",line):
                completed.append({"path":str(path),"claim":re.sub(r"^\s*[-*]\s*\[[xX]\]\s+","",line).strip()[:240]})
                if len(completed)>=80: break
        if len(completed)>=80: break

    return {
        "schema_version":SCHEMA_VERSION,
        "lab_version":LAB_VERSION,
        "documents":[str(path) for path,_ in documents],
        "capabilities":rows,
        "completed_roadmap_claims":completed,
        "findings":findings,
        "summary":{"documents":len(documents),"capabilities":len(rows),"promised":sum(1 for x in rows if x["promised"]),"code_confirmed":sum(1 for x in rows if x["implementation"]=="CODE_CONFIRMED"),"runtime_verified":sum(1 for x in rows if str(x["runtime_verified"]).startswith("OBSERVED")),"review_signals":sum(1 for x in findings if x["severity"] in {"REVIEW","HIGH_REVIEW"})},
        "guardrails":{"documentation_is_claim_evidence_not_truth":True,"not_observed_is_not_missing":True,"checked_roadmap_items_are_not_auto_passed":True,"no_certification_override":True},
    }


def markdown(r:dict[str,Any])->str:
    lines=["# AppLab Product Contract Audit","",f"- Product documents: **{r['summary']['documents']}**",f"- Capabilities mapped: **{r['summary']['capabilities']}**",f"- Runtime verified: **{r['summary']['runtime_verified']}**",f"- Review signals: **{r['summary']['review_signals']}**",""]
    for row in r["capabilities"]:
        lines.append(f"- **{row['capability']}** · promised={row['promised']} · implementation={row['implementation']} · reachable={row['runtime_reachable']} · verified={row['runtime_verified']}")
    return "\n".join(lines)


def self_test()->None:
    with tempfile.TemporaryDirectory() as raw:
        root=Path(raw)
        (root/"README.md").write_text("Authentication and cloud sync are product features.",encoding="utf-8")
        app={"feature_truth":{"capabilities":[{"capability":"authentication","truth":"CODE_CONFIRMED","provenance":{"CODE":["auth.dart"]}},{"capability":"cloud_or_sync","truth":"DOC_ONLY_SIGNAL","provenance":{"DOCUMENTATION":["README.md"]}}]}}
        r=build_report(root,app,{"runtime_controls":[{"label":"Login"}],"runtime_evidence_state":"OBSERVED_PASS"},{"states":{"auth":{"status":"OBSERVED"},"offline":{"status":"NOT_OBSERVED"}}})
        assert r["summary"]["promised"]==2
        assert any(x["kind"]=="PROMISED_WITHOUT_IMPLEMENTATION_EVIDENCE" for x in r["findings"])
    print("AppLab Product Contract Audit self-test PASS")


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--repo-root")
    p.add_argument("--app-intelligence")
    p.add_argument("--behavioral")
    p.add_argument("--state-edge")
    p.add_argument("--output-dir",default="applab-product-contract")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.repo_root or not a.app_intelligence: raise SystemExit("--repo-root and --app-intelligence are required")
    app=load_json(Path(a.app_intelligence))
    if app is None: raise SystemExit("invalid app intelligence")
    r=build_report(Path(a.repo_root),app,load_json(Path(a.behavioral)) if a.behavioral else None,load_json(Path(a.state_edge)) if a.state_edge else None)
    write_report(Path(a.output_dir),"product-contract-audit",r,markdown(r))
    print(json.dumps({"lab_version":LAB_VERSION,**r["summary"]}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
