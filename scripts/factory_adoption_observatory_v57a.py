#!/usr/bin/env python3
from __future__ import annotations

import argparse, base64, json, os, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from typing import Any
import yaml

EXPECTED_PROFILE_VERSION=1
EXPECTED_STRATEGY="INTEGRATE_PRESERVE_EXISTING"

def api_json(url:str, token:str="")->Any:
    headers={"Accept":"application/vnd.github+json","User-Agent":"AppLab-v5.7"}
    if token:
        headers["Authorization"]=f"Bearer {token}"
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code==404:
            return None
        raise

def repo_content(repository:str,path:str,ref:str,token:str="")->str|None:
    quoted=urllib.parse.quote(path,safe="/")
    query=urllib.parse.urlencode({"ref":ref})
    payload=api_json(f"https://api.github.com/repos/{repository}/contents/{quoted}?{query}",token)
    if not isinstance(payload,dict):
        return None
    raw=payload.get("content")
    if not isinstance(raw,str):
        return None
    return base64.b64decode(raw).decode("utf-8")

def workflow_names(repository:str,ref:str,token:str="")->list[str]:
    query=urllib.parse.urlencode({"ref":ref})
    payload=api_json(f"https://api.github.com/repos/{repository}/contents/.github/workflows?{query}",token)
    if not isinstance(payload,list):
        return []
    return sorted(
        str(item.get("name"))
        for item in payload
        if isinstance(item,dict) and str(item.get("name","")).endswith((".yml",".yaml"))
    )

def repo_inventory(watchlist:dict[str,Any], pilots:dict[str,Any])->list[dict[str,str]]:
    rows:dict[str,dict[str,str]]={}
    for item in watchlist.get("repositories",[]):
        if not isinstance(item,dict) or not item.get("enabled"):
            continue
        repository=str(item.get("repository","")).strip()
        if not repository:
            continue
        rows[repository]={"repository":repository,"ref":str(item.get("ref","main")),"source":"WATCHLIST"}
    for item in pilots.get("pilots",[]):
        if not isinstance(item,dict):
            continue
        repository=str(item.get("repository","")).strip()
        if not repository:
            continue
        rows.setdefault(repository,{"repository":repository,"ref":str(item.get("ref","main")),"source":"PILOT"})
        rows[repository]["pilot"]="true"
        rows[repository]["label"]=str(item.get("label",""))
    return [rows[key] for key in sorted(rows)]

def analyze_manifest(repository:str,ref:str,raw:str|None,workflows:list[str],source:str,pilot:bool=False,label:str="")->dict[str,Any]:
    result={
      "repository":repository,"ref":ref,"source":source,"pilot":pilot,"label":label,
      "status":"MISSING_MANIFEST","profile_version":None,"mode":"","workflow_strategy":"",
      "workflow_count":len(workflows),"workflow_files":workflows,"gaps":[]
    }
    if raw is None:
        result["gaps"].append("APP_FACTORY_ADOPTION.yaml")
        return result
    try:
        data=yaml.safe_load(raw)
    except yaml.YAMLError:
        result["status"]="INVALID_MANIFEST"
        result["gaps"].append("INVALID_YAML")
        return result
    if not isinstance(data,dict):
        result["status"]="INVALID_MANIFEST"
        result["gaps"].append("MANIFEST_NOT_OBJECT")
        return result
    factory=data.get("factory") if isinstance(data.get("factory"),dict) else {}
    integration=data.get("workflow_integration") if isinstance(data.get("workflow_integration"),dict) else {}
    profile=factory.get("profile_version")
    strategy=integration.get("strategy")
    result["profile_version"]=profile
    result["workflow_strategy"]=str(strategy or "")
    result["mode"]="ROADMAP_FAST_PLUS_CONTINUOUS_MAINTENANCE"
    if str(data.get("repository",""))!=repository:
        result["gaps"].append("REPOSITORY_IDENTITY_MISMATCH")
    if profile!=EXPECTED_PROFILE_VERSION:
        result["gaps"].append("PROFILE_VERSION_DRIFT")
    if strategy!=EXPECTED_STRATEGY or integration.get("overwrite_existing") is not False:
        result["gaps"].append("WORKFLOW_INTEGRATION_DRIFT")
    result["status"]="ADOPTED" if not result["gaps"] else "DRIFT"
    return result

def build_report(records:list[dict[str,Any]])->dict[str,Any]:
    counts={}
    for row in records:
        counts[row["status"]]=counts.get(row["status"],0)+1
    pilots=[row for row in records if row.get("pilot")]
    return {
      "schema_version":1,
      "record_type":"FACTORY_ADOPTION_OBSERVATORY_V57A",
      "authority":"OBSERVATION_ONLY",
      "summary":{
        "repositories":len(records),"pilots":len(pilots),"status_counts":dict(sorted(counts.items())),
        "pilot_adopted":sum(row["status"]=="ADOPTED" for row in pilots)
      },
      "repositories":records,
      "boundaries":["read-only observation","no repository mutation","no PASS/CERTIFIED authority"]
    }

def render_md(report:dict[str,Any])->str:
    lines=["# Factory Adoption Observatory v5.7A","",
      "| Repository | Pilot | Status | Profile | Workflows | Gaps |",
      "| --- | --- | --- | ---: | ---: | --- |"]
    for row in report["repositories"]:
        lines.append(f"| {row['repository']} | {'yes' if row.get('pilot') else 'no'} | {row['status']} | {row.get('profile_version') or '-'} | {row['workflow_count']} | {', '.join(row['gaps']) or '-'} |")
    lines+=["","Observation only. AppLab does not modify downstream repositories.",""]
    return "\n".join(lines)

def self_test()->None:
    good=yaml.safe_dump({
      "schema_version":1,"repository":"owner/app",
      "factory":{"profile_version":1},
      "workflow_integration":{"strategy":EXPECTED_STRATEGY,"overwrite_existing":False}
    })
    a=analyze_manifest("owner/app","main",good,["ci.yml"],"PILOT",True,"App")
    assert a["status"]=="ADOPTED"
    b=analyze_manifest("owner/missing","main",None,[],"WATCHLIST")
    assert b["status"]=="MISSING_MANIFEST"
    bad=good.replace("profile_version: 1","profile_version: 2")
    c=analyze_manifest("owner/app","main",bad,[],"PILOT",True,"App")
    assert c["status"]=="DRIFT" and "PROFILE_VERSION_DRIFT" in c["gaps"]
    report=build_report([a,b,c])
    assert report["summary"]["repositories"]==3
    print("AppLab v5.7A adoption observatory self-test PASS")

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--watchlist",default="watchlist.json")
    p.add_argument("--pilots",default="integration/factory/v57-pilots.json")
    p.add_argument("--output-json",default="")
    p.add_argument("--output-md",default="")
    p.add_argument("--token",default=os.environ.get("GITHUB_TOKEN",""))
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        self_test(); return 0
    watch=json.loads(Path(a.watchlist).read_text(encoding="utf-8"))
    pilots=json.loads(Path(a.pilots).read_text(encoding="utf-8"))
    rows=[]
    for item in repo_inventory(watch,pilots):
        repo=item["repository"]; ref=item["ref"]
        raw=repo_content(repo,"APP_FACTORY_ADOPTION.yaml",ref,a.token)
        workflows=workflow_names(repo,ref,a.token)
        rows.append(analyze_manifest(repo,ref,raw,workflows,item["source"],item.get("pilot")=="true",item.get("label","")))
    report=build_report(rows)
    if a.output_json: Path(a.output_json).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if a.output_md: Path(a.output_md).write_text(render_md(report),encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
