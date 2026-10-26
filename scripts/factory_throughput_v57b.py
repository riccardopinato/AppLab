#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math, os, urllib.error, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

def dt(value:str)->datetime:
    return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)

def pct(values:list[float],q:float)->float|None:
    if not values: return None
    ordered=sorted(values); rank=max(1,math.ceil(q*len(ordered)))
    return round(ordered[rank-1],1)

def api_json(url:str,token:str="")->Any:
    headers={"Accept":"application/vnd.github+json","User-Agent":"AppLab-v5.7"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None

def collect_repo(repository:str,token:str,max_prs:int,window_days:int,now:datetime)->list[dict[str,Any]]:
    payload=api_json(f"https://api.github.com/repos/{repository}/pulls?state=closed&per_page=50&sort=updated&direction=desc",token)
    if not isinstance(payload,list): return []
    cutoff=now-timedelta(days=window_days); out=[]
    for pr in payload:
        if not isinstance(pr,dict) or not pr.get("merged_at"): continue
        merged=dt(str(pr["merged_at"]))
        if merged<cutoff: continue
        commits=api_json(str(pr.get("commits_url","")),token) if pr.get("commits_url") else None
        first=None
        if isinstance(commits,list) and commits:
            dates=[]
            for commit in commits:
                try: dates.append(dt(str(commit["commit"]["author"]["date"])))
                except Exception: pass
            if dates: first=min(dates)
        opened=dt(str(pr["created_at"]))
        start=first or opened
        out.append({
          "number":pr.get("number"),"created_at":opened.isoformat(),"merged_at":merged.isoformat(),
          "first_commit_at":first.isoformat() if first else None,
          "first_commit_to_merge_seconds":max(0,(merged-start).total_seconds()),
          "pr_open_to_merge_seconds":max(0,(merged-opened).total_seconds())
        })
        if len(out)>=max_prs: break
    return out

def summarize(samples:list[dict[str,Any]])->dict[str,Any]:
    step=[float(x["first_commit_to_merge_seconds"]) for x in samples]
    pr=[float(x["pr_open_to_merge_seconds"]) for x in samples]
    return {
      "samples":len(samples),
      "first_commit_to_merge_p50_seconds":pct(step,.5),
      "first_commit_to_merge_p95_seconds":pct(step,.95),
      "pr_open_to_merge_p50_seconds":pct(pr,.5),
      "pr_open_to_merge_p95_seconds":pct(pr,.95)
    }

def build_report(observatory:dict[str,Any],pilots:dict[str,Any],samples_by_repo:dict[str,list[dict[str,Any]]])->dict[str,Any]:
    adoption={row["repository"]:row for row in observatory.get("repositories",[]) if isinstance(row,dict)}
    minimum=int(pilots["throughput"]["minimum_merged_samples_for_promotion"])
    rows=[]
    for pilot in pilots.get("pilots",[]):
        repo=pilot["repository"]; adopted=adoption.get(repo,{}).get("status")=="ADOPTED"
        metrics=summarize(samples_by_repo.get(repo,[]))
        state="MEASURING" if adopted else "WAITING_ADOPTION_MANIFEST"
        if adopted and metrics["samples"]>=minimum: state="EVIDENCE_READY"
        rows.append({"repository":repo,"label":pilot.get("label",""),"adopted":adopted,"state":state,"metrics":metrics})
    ready=bool(rows) and all(r["state"]=="EVIDENCE_READY" for r in rows)
    return {
      "schema_version":1,"record_type":"FACTORY_THROUGHPUT_V57B","authority":"MEASUREMENT_ONLY",
      "measurement":"FIRST_COMMIT_TO_MERGE_PROXY","promotion_ready":ready,
      "pilots":rows,
      "guardrails":{"no_synthetic_samples":True,"missing_adoption_is_not_success":True}
    }

def self_test()->None:
    samples=[{"first_commit_to_merge_seconds":10,"pr_open_to_merge_seconds":8},{"first_commit_to_merge_seconds":30,"pr_open_to_merge_seconds":20},{"first_commit_to_merge_seconds":20,"pr_open_to_merge_seconds":15}]
    s=summarize(samples); assert s["samples"]==3 and s["first_commit_to_merge_p50_seconds"]==20
    obs={"repositories":[{"repository":"owner/a","status":"ADOPTED"},{"repository":"owner/b","status":"MISSING_MANIFEST"}]}
    pilots={"throughput":{"minimum_merged_samples_for_promotion":3},"pilots":[{"repository":"owner/a"},{"repository":"owner/b"}]}
    report=build_report(obs,pilots,{"owner/a":samples})
    assert report["promotion_ready"] is False
    assert report["pilots"][1]["state"]=="WAITING_ADOPTION_MANIFEST"
    print("AppLab v5.7B throughput self-test PASS")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--observatory",default=""); p.add_argument("--pilots",default="integration/factory/v57-pilots.json"); p.add_argument("--output",default=""); p.add_argument("--token",default=os.environ.get("GITHUB_TOKEN","")); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test: self_test(); return 0
    obs=json.loads(Path(a.observatory).read_text(encoding="utf-8")); pilots=json.loads(Path(a.pilots).read_text(encoding="utf-8"))
    now=datetime.now(timezone.utc); cfg=pilots["throughput"]; samples={}
    for item in pilots.get("pilots",[]):
        samples[item["repository"]]=collect_repo(item["repository"],a.token,int(cfg["max_merged_prs_per_repo"]),int(cfg["window_days"]),now)
    report=build_report(obs,pilots,samples)
    if a.output: Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
