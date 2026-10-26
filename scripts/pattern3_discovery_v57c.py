#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from typing import Any

PRODUCT_TOKENS={"PRODUCT","UX","CONTENT","COPY","VISUAL_PRODUCT"}

def norm(text:str)->str:
    text=re.sub(r"\b[0-9a-f]{7,64}\b","<id>",text.lower())
    text=re.sub(r"\d+","<n>",text)
    return re.sub(r"\s+"," ",text).strip()[:120]

def queue_observations(queue:dict[str,Any])->list[dict[str,Any]]:
    out=[]
    for item in queue.get("items",[]):
        if not isinstance(item,dict): continue
        count=max(1,int(item.get("occurrences",1) or 1))
        category=str(item.get("category","GENERAL")).upper()
        code=str(item.get("code",""))
        message=str(item.get("message",""))
        sig=f"{category}|{code}|{norm(message)}"
        out.append({"signature":sig,"repository":str(item.get("repository","")),"category":category,"count":count})
    return out

def suggest(category:str,repo_count:int)->str:
    if category in PRODUCT_TOKENS and repo_count==1: return "APP-SPECIFIC"
    if repo_count<=1: return "DONOR"
    if repo_count==2: return "FACTORY PROCESS"
    return "GOLDEN CANDIDATE"

def build_report(queue:dict[str,Any])->dict[str,Any]:
    groups={}
    for obs in queue_observations(queue):
        g=groups.setdefault(obs["signature"],{"occurrences":0,"repositories":set(),"category":obs["category"]})
        g["occurrences"]+=obs["count"]
        if obs["repository"]: g["repositories"].add(obs["repository"])
    candidates=[]
    for signature,g in groups.items():
        if g["occurrences"]<3: continue
        repos=sorted(g["repositories"])
        candidates.append({
          "signature":signature,"occurrences":g["occurrences"],"repositories":repos,
          "repository_count":len(repos),"suggested_classification":suggest(g["category"],len(repos)),
          "classification_options":["APP-SPECIFIC","DONOR","FACTORY PROCESS","GOLDEN CANDIDATE"],
          "auto_promote":False,"review_required":True
        })
    candidates.sort(key=lambda x:(-x["occurrences"],x["signature"]))
    return {"schema_version":1,"record_type":"PATTERN3_DISCOVERY_V57C","authority":"PROPOSAL_ONLY","threshold":3,"candidates":candidates}

def self_test()->None:
    q={"items":[
      {"repository":"owner/a","category":"INFRASTRUCTURE","code":"TIMEOUT","message":"same timeout","occurrences":3},
      {"repository":"owner/b","category":"PRODUCT","code":"COPY","message":"wording issue","occurrences":3}
    ]}
    r=build_report(q); assert len(r["candidates"])==2
    assert all(x["auto_promote"] is False for x in r["candidates"])
    print("AppLab v5.7C Pattern-3 self-test PASS")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--queue",default=""); p.add_argument("--output",default=""); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.queue: raise SystemExit("--queue is required")
    report=build_report(json.loads(Path(a.queue).read_text(encoding="utf-8")))
    if a.output: Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
