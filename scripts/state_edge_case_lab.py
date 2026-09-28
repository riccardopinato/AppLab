#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from product_review_common import find_json, load_json, result_state, write_report

SCHEMA_VERSION=1
LAB_VERSION="2.8.0"

REPORTS={
    "normal": ["interaction-crawl.json"],
    "offline": ["network-lab.json"],
    "restart": ["persistence-lab.json"],
    "configuration": ["configuration-lab.json"],
    "process_death": ["resource-pressure-lab.json","resource-pressure.json"],
    "storage": ["storage-lab.json","storage-integrity.json"],
    "background": ["background-lab.json","background-doze-recovery.json"],
    "permissions": ["system-lab.json","permissions-system-ui.json"],
}

KEYWORDS={
    "empty": ("empty","nessun","no items","no data"),
    "loading": ("loading","caricamento","progress"),
    "error": ("error","errore","failed","failure"),
    "auth": ("login","sign in","signin","account","autentic"),
    "permission_denied": ("permission denied","permesso negato","allow permission","autorizz"),
}


def scan_keyword_states(root: Path | None) -> dict[str,list[str]]:
    found={key:[] for key in KEYWORDS}
    if root is None or not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".xml",".json",".txt",".md"}:
            continue
        try:
            if path.stat().st_size>500_000:
                continue
            text=path.read_text(encoding="utf-8",errors="ignore").lower()
        except OSError:
            continue
        for key,terms in KEYWORDS.items():
            if any(term in text for term in terms):
                found[key].append(str(path))
                found[key]=found[key][:8]
    return found


def build_report(app: dict[str,Any], evidence_root: Path | None) -> dict[str,Any]:
    states:dict[str,dict[str,Any]]={}
    for state,names in REPORTS.items():
        path,payload=find_json(evidence_root,names)
        states[state]={
            "status":result_state(payload),
            "source":str(path) if path else None,
            "result":str(payload.get("result","")) if payload else None,
        }

    keyword=scan_keyword_states(evidence_root)
    for state,paths in keyword.items():
        states[state]={
            "status":"OBSERVED" if paths else "NOT_OBSERVED",
            "source":paths,
            "result":None,
        }

    product=app.get("product") if isinstance(app.get("product"),dict) else {}
    features=product.get("feature_signals") if isinstance(product.get("feature_signals"),list) else []
    capabilities={str(x.get("label","")) for x in features if isinstance(x,dict) and str(x.get("status","")).upper()=="PRESENT"}

    applicability={
        "offline": bool(capabilities & {"network_api","cloud_or_sync"}),
        "auth": "authentication" in capabilities,
        "permissions": bool(capabilities & {"notifications","maps_or_location","camera","microphone"}),
        "permission_denied": bool(capabilities & {"notifications","maps_or_location","camera","microphone"}),
        "restart": True,
        "configuration": True,
        "process_death": True,
        "storage": True,
        "background": "background_execution" in capabilities,
        "empty": True,
        "loading": bool(capabilities & {"network_api","cloud_or_sync"}),
        "error": True,
        "normal": True,
    }

    findings=[]
    for state,row in states.items():
        applicable=applicability.get(state,True)
        if not applicable:
            row["applicability"]="NOT_APPLICABLE"
            continue
        row["applicability"]="APPLICABLE"
        if row["status"]=="OBSERVED_FAIL":
            findings.append({"kind":"EDGE_STATE_RUNTIME_FAILURE","severity":"HIGH_REVIEW","confidence":"HIGH","state":state,"message":f"Runtime evidence failed in {state} state.","evidence":[row["source"]] if row["source"] else []})
        elif row["status"] in {"NOT_OBSERVED","OBSERVED_UNKNOWN"}:
            findings.append({"kind":"EDGE_STATE_NOT_OBSERVED","severity":"REVIEW","confidence":"MEDIUM","state":state,"message":f"Applicable product state {state} has no bounded runtime observation.","evidence":[]})

    return {
        "schema_version":SCHEMA_VERSION,
        "lab_version":LAB_VERSION,
        "states":states,
        "summary":{
            "applicable":sum(1 for k in states if applicability.get(k,True)),
            "observed":sum(1 for k,v in states.items() if applicability.get(k,True) and v["status"] not in {"NOT_OBSERVED","OBSERVED_UNKNOWN"}),
            "failed":sum(1 for v in states.values() if v["status"]=="OBSERVED_FAIL"),
            "review_signals":len(findings),
        },
        "findings":findings,
        "guardrails":{"missing_state_is_review_not_fail":True,"applicability_is_capability_driven":True,"no_runtime_verdict_override":True},
    }


def markdown(r:dict[str,Any])->str:
    lines=["# AppLab State & Edge-Case Lab","",f"- Applicable states: **{r['summary']['applicable']}**",f"- Observed states: **{r['summary']['observed']}**",f"- Runtime failures: **{r['summary']['failed']}**",""]
    for k,v in r["states"].items():
        lines.append(f"- **{k}**: {v['status']} · {v.get('applicability','')}")
    return "\n".join(lines)


def self_test()->None:
    app={"product":{"feature_signals":[{"label":"network_api","status":"PRESENT"},{"label":"authentication","status":"PRESENT"}]}}
    with tempfile.TemporaryDirectory() as raw:
        root=Path(raw)
        (root/"network-lab.json").write_text('{"result":"PASS"}',encoding="utf-8")
        (root/"interaction-crawl.json").write_text('{"result":"PASS"}',encoding="utf-8")
        (root/"ui.xml").write_text('<node text="Login"/>',encoding="utf-8")
        r=build_report(app,root)
        assert r["states"]["offline"]["status"]=="OBSERVED_PASS"
        assert r["states"]["auth"]["status"]=="OBSERVED"
        assert r["summary"]["observed"]>=2
    print("AppLab State & Edge-Case Lab self-test PASS")


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--app-intelligence")
    p.add_argument("--runtime-evidence-dir")
    p.add_argument("--output-dir",default="applab-state-edge")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.app_intelligence: raise SystemExit("--app-intelligence is required")
    app=load_json(Path(a.app_intelligence))
    if app is None: raise SystemExit("invalid app intelligence")
    root=Path(a.runtime_evidence_dir) if a.runtime_evidence_dir else None
    r=build_report(app,root)
    write_report(Path(a.output_dir),"state-edge-case",r,markdown(r))
    print(json.dumps({"lab_version":LAB_VERSION,**r["summary"]}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
