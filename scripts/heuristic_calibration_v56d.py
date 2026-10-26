#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median
from typing import Any

MIN_REPOSITORIES=4
MIN_CATEGORIES=3
MIN_SAMPLES=20
MAX_STALE_DAYS=45

def parse_time(value:Any)->datetime|None:
    text=str(value or "").strip()
    if not text: return None
    try: dt=datetime.fromisoformat(text.replace("Z","+00:00"))
    except ValueError: return None
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def read_history(path:Path)->list[dict[str,Any]]:
    rows=[]
    if not path.is_file(): return rows
    for raw in path.read_text(encoding="utf-8",errors="ignore").splitlines():
        try: item=json.loads(raw)
        except json.JSONDecodeError: continue
        if isinstance(item,dict): rows.append(item)
    return rows

def percentile(values:list[float],q:float)->float|None:
    if not values: return None
    ordered=sorted(values); rank=max(1,math.ceil(q*len(ordered)))
    return round(float(ordered[rank-1]),3)

def category(row:dict[str,Any])->str:
    p=row.get("playbook")
    if not isinstance(p,dict): return "unknown"
    return str(p.get("category","") or "unknown").strip().lower()

def build_profile(rows:list[dict[str,Any]],now:datetime)->dict[str,Any]:
    fresh=[]
    stale=0
    for row in rows:
        ts=parse_time(row.get("recorded_at",row.get("observed_at")))
        if ts is None or ts>now or now-ts>timedelta(days=MAX_STALE_DAYS):
            stale+=1; continue
        fresh.append(row)

    usable=[]
    for r in fresh:
        metrics=r.get("pipeline_metrics")
        lane=str(r.get("analysis_lane","")).strip()
        if (
            isinstance(r.get("risk_score"),(int,float))
            and not isinstance(r.get("risk_score"),bool)
            and isinstance(r.get("confidence"),(int,float))
            and not isinstance(r.get("confidence"),bool)
            and isinstance(metrics,dict)
            and isinstance(metrics.get("wall_clock_seconds"),(int,float))
            and not isinstance(metrics.get("wall_clock_seconds"),bool)
            and lane
            and lane!="UNKNOWN"
        ):
            usable.append(r)

    repos=Counter(str(r.get("repository","")).strip().lower() for r in usable if str(r.get("repository","")).strip())
    cats=Counter(category(r) for r in usable if category(r)!="unknown")
    risks=[float(r["risk_score"]) for r in usable]
    confidences=[float(r["confidence"]) for r in usable]
    wall=[]
    lane_counts=Counter()
    failures=Counter()
    for r in usable:
        lane=str(r.get("analysis_lane","")).strip()
        lane_counts[lane]+=1
        metrics=r.get("pipeline_metrics")
        wall.append(float(metrics["wall_clock_seconds"]))
        fi=r.get("failure_intelligence")
        if isinstance(fi,dict):
            kind=str(fi.get("kind","")).strip()
            if kind and kind!="NONE": failures[kind]+=1
    ready=len(repos)>=MIN_REPOSITORIES and len(cats)>=MIN_CATEGORIES and len(usable)>=MIN_SAMPLES
    candidate={
        "risk_median":round(median(risks),3) if risks else None,
        "confidence_median":round(median(confidences),3) if confidences else None,
        "wall_clock_p50":percentile(wall,.5),
        "wall_clock_p95":percentile(wall,.95),
        "dominant_lane":lane_counts.most_common(1)[0][0] if lane_counts else None,
        "dominant_failure":failures.most_common(1)[0][0] if failures else None,
    }
    return {
      "schema_version":1,
      "record_type":"MULTI_PROJECT_HEURISTIC_CALIBRATION_V56D",
      "authority":"ADVISORY_CANDIDATE_ONLY",
      "state":"CANDIDATE_READY" if ready else "COLLECTING",
      "applied_to_production":False,
      "freshness":{"max_age_days":MAX_STALE_DAYS,"fresh_samples":len(fresh),"usable_samples":len(usable),"stale_undated_or_future":stale},
      "diversity":{"repositories":len(repos),"categories":len(cats),"repository_samples":dict(sorted(repos.items())),"category_samples":dict(sorted(cats.items()))},
      "before_after":{
        "before":"current production Smart Test Plan thresholds unchanged",
        "candidate_profile":candidate,
        "after":"not applied; requires separate promotion evidence"
      },
      "failure_mix":dict(sorted(failures.items())),
      "guardrails":{"smart_test_plan_authority_unchanged":True,"coverage_reduction_enabled":False,"stale_data_excluded":True}
    }

def self_test():
    now=datetime(2026,10,26,tzinfo=timezone.utc)
    rows=[]
    cats=("ui_change","database_migration","general_code_change","release_ops")
    for i in range(24):
        rows.append({
          "repository":f"owner/app-{i%4}","recorded_at":"2026-10-20T00:00:00Z","playbook":{"category":cats[i%4]},
          "risk_score":20+i%5,"confidence":80-i%4,"analysis_lane":"FAST_RUNTIME" if i%2 else "FULL_RUNTIME",
          "pipeline_metrics":{"wall_clock_seconds":100+i},
          "failure_intelligence":{"kind":"NONE"}
        })
    rows.append({"repository":"owner/stale","recorded_at":"2026-01-01T00:00:00Z","playbook":{"category":"ui_change"}})
    report=build_profile(rows,now)
    assert report["state"]=="CANDIDATE_READY"
    assert report["applied_to_production"] is False
    assert report["freshness"]["stale_undated_or_future"]==1
    incomplete=[
        {"repository":f"owner/app-{i%4}","recorded_at":"2026-10-20T00:00:00Z","playbook":{"category":cats[i%4]}}
        for i in range(24)
    ]
    assert build_profile(incomplete,now)["state"]=="COLLECTING"
    future=[dict(row,recorded_at="2036-10-20T00:00:00Z") for row in rows[:24]]
    future_report=build_profile(future,now)
    assert future_report["state"]=="COLLECTING"
    assert future_report["freshness"]["usable_samples"]==0
    assert report["diversity"]["repositories"]==4
    sparse=build_profile(rows[:3],now)
    assert sparse["state"]=="COLLECTING"
    print("AppLab v5.6D heuristic calibration self-test PASS")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--history-file",default=""); p.add_argument("--output",default=""); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.history_file: raise SystemExit("--history-file is required")
    report=build_profile(read_history(Path(a.history_file)),datetime.now(timezone.utc))
    if a.output: Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
