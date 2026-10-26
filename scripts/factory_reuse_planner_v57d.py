#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, json, os, urllib.error, urllib.request
from pathlib import Path
from typing import Any
import yaml

GENERAL_IDS=["roadmap_fast_continuous_maintenance","applab_qa_certification","immutable_build_test_artifact"]
FLUTTER_IDS=["ci_release_web_deploy","localization","profile_standard","theme_m3"]

def api_json(url:str,token:str="")->Any:
    headers={"Accept":"application/vnd.github+json","User-Agent":"AppLab-v5.7"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

def content(repository:str,path:str,ref:str,token:str="")->str:
    payload=api_json(f"https://api.github.com/repos/{repository}/contents/{path}?ref={ref}",token)
    return base64.b64decode(payload["content"]).decode("utf-8")

def load_core_registry(token:str="")->tuple[str,dict[str,Any]]:
    sha=api_json("https://api.github.com/repos/riccardopinato/App-Factory-Core/commits/main",token)["sha"]
    current=yaml.safe_load(content("riccardopinato/App-Factory-Core","CURRENT.yaml",sha,token))
    path=current["golden_registry"]["path"]
    registry=yaml.safe_load(content("riccardopinato/App-Factory-Core",path,sha,token))
    return sha,registry

def build_report(observatory:dict[str,Any],watchlist:dict[str,Any],core_sha:str,registry:dict[str,Any])->dict[str,Any]:
    by_repo={str(x.get("repository","")):x for x in watchlist.get("repositories",[]) if isinstance(x,dict)}
    by_id={str(x.get("id","")):x for x in registry.get("goldens",[]) if isinstance(x,dict)}
    rows=[]
    for adoption in observatory.get("repositories",[]):
        if not isinstance(adoption,dict) or adoption.get("status")!="ADOPTED": continue
        repo=adoption["repository"]; engine=str(by_repo.get(repo,{}).get("engine","auto"))
        ids=list(GENERAL_IDS)+(FLUTTER_IDS if engine=="flutter" else [])
        candidates=[]
        for gid in ids:
            item=by_id.get(gid)
            if not item or str(item.get("status","")).startswith("DEPRECATED"): continue
            candidates.append({"id":gid,"title":item.get("title",""),"status":item.get("status",""),"path":item.get("path",""),"action":"COMPATIBILITY_REVIEW"})
        rows.append({"repository":repo,"engine":engine,"candidates":candidates,"automatic_code_change":False})
    return {"schema_version":1,"record_type":"FACTORY_REUSE_PLANNER_V57D","authority":"ADVISORY_ONLY","core_sha":core_sha,"repositories":rows}

def self_test()->None:
    obs={"repositories":[{"repository":"owner/a","status":"ADOPTED"},{"repository":"owner/b","status":"MISSING_MANIFEST"}]}
    watch={"repositories":[{"repository":"owner/a","engine":"flutter"}]}
    reg={"goldens":[{"id":"applab_qa_certification","title":"QA","status":"CERTIFIED PROCESS","path":"qa"},{"id":"localization","title":"L10n","status":"COPY-READY GOLDEN","path":"l10n"}]}
    r=build_report(obs,watch,"a"*40,reg)
    assert len(r["repositories"])==1 and r["repositories"][0]["automatic_code_change"] is False
    print("AppLab v5.7D reuse planner self-test PASS")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--observatory",default=""); p.add_argument("--watchlist",default="watchlist.json"); p.add_argument("--output",default=""); p.add_argument("--token",default=os.environ.get("GITHUB_TOKEN","")); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test: self_test(); return 0
    obs=json.loads(Path(a.observatory).read_text(encoding="utf-8")); watch=json.loads(Path(a.watchlist).read_text(encoding="utf-8"))
    sha,registry=load_core_registry(a.token); report=build_report(obs,watch,sha,registry)
    if a.output: Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
