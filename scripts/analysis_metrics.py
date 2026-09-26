#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values=sorted(values)
    if len(values)==1:
        return round(values[0],2)
    pos=(len(values)-1)*q
    lo=math.floor(pos); hi=math.ceil(pos)
    if lo==hi:
        return round(values[lo],2)
    frac=pos-lo
    return round(values[lo]*(1-frac)+values[hi]*frac,2)

def read_history(path: Path) -> list[dict[str,Any]]:
    rows=[]
    if not path.is_file():
        return rows
    for raw in path.read_text(encoding="utf-8",errors="ignore").splitlines():
        try: item=json.loads(raw)
        except json.JSONDecodeError: continue
        if isinstance(item,dict): rows.append(item)
    return rows

def build_metrics(rows: list[dict[str,Any]]) -> dict[str,Any]:
    lane=Counter()
    mode=Counter()
    planner=[]; preflight=[]; build=[]; runtime=[]; total=[]
    shadow_samples=shadow_diverged=false_negatives=0
    fallback=0
    results=Counter()
    for row in rows:
        results[str(row.get("result","UNKNOWN"))]+=1
        lane[str(row.get("analysis_lane","UNKNOWN"))]+=1
        mode[str(row.get("analysis_mode","unknown"))]+=1
        if bool(row.get("analysis_risk",{})) and str(row.get("analysis_lane",""))=="FULL_RUNTIME" and str(row.get("analysis_requested_mode",""))=="fast":
            fallback+=1
        value=row.get("planner_elapsed_ms")
        if isinstance(value,(int,float)): planner.append(float(value))
        timings=row.get("timings",{})
        if isinstance(timings,dict):
            for key,target in (
                ("preflight_elapsed_seconds",preflight),
                ("build_job_elapsed_seconds",build),
                ("runtime_job_elapsed_seconds",runtime),
                ("estimated_total_seconds",total),
            ):
                value=timings.get(key)
                if isinstance(value,(int,float)): target.append(float(value))
        cal=row.get("shadow_calibration",{})
        if isinstance(cal,dict) and cal.get("status") not in {None,"NOT_SAMPLED"}:
            shadow_samples+=1
            if cal.get("status")=="DIVERGED": shadow_diverged+=1
            false_negatives+=int(cal.get("false_negative_count",0) or 0)
    def stats(values:list[float])->dict[str,Any]:
        return {"count":len(values),"p50":percentile(values,.50),"p95":percentile(values,.95)}
    return {
        "schema_version":1,
        "runs":len(rows),
        "results":dict(results),
        "lanes":dict(lane),
        "modes":dict(mode),
        "fast_full_escalations":fallback,
        "shadow":{"samples":shadow_samples,"diverged":shadow_diverged,"false_negatives":false_negatives},
        "timings":{
            "planner_ms":stats(planner),
            "preflight_seconds":stats(preflight),
            "build_seconds":stats(build),
            "runtime_seconds":stats(runtime),
            "estimated_total_seconds":stats(total),
        },
    }

def self_test()->None:
    rows=[
        {"result":"PASS","analysis_lane":"FAST_RUNTIME","analysis_mode":"fast","planner_elapsed_ms":100,
         "timings":{"preflight_elapsed_seconds":2,"build_job_elapsed_seconds":20,"runtime_job_elapsed_seconds":30,"estimated_total_seconds":52},
         "shadow_calibration":{"status":"MATCH","false_negative_count":0}},
        {"result":"PASS","analysis_lane":"FULL_RUNTIME","analysis_requested_mode":"fast","analysis_mode":"full","analysis_risk":{"level":"HIGH"},"planner_elapsed_ms":200,
         "timings":{"preflight_elapsed_seconds":3,"build_job_elapsed_seconds":30,"runtime_job_elapsed_seconds":40,"estimated_total_seconds":73},
         "shadow_calibration":{"status":"DIVERGED","false_negative_count":1}},
    ]
    out=build_metrics(rows)
    assert out["runs"]==2
    assert out["fast_full_escalations"]==1
    assert out["shadow"]["samples"]==2 and out["shadow"]["false_negatives"]==1
    assert out["timings"]["planner_ms"]["p50"]==150
    print("AppLab analysis metrics self-test PASS")

def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--history-file")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--repository",default="")
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if not args.history_file or not args.output_json:
        raise SystemExit("--history-file and --output-json are required")
    rows=read_history(Path(args.history_file))
    if args.repository:
        rows=[r for r in rows if str(r.get("repository",""))==args.repository]
    metrics=build_metrics(rows)
    Path(args.output_json).write_text(json.dumps(metrics,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    if args.output_md:
        t=metrics["timings"]
        lines=[
            "# AppLab Adaptive Analysis Metrics","",
            f"- Runs: {metrics['runs']}",
            f"- FAST→FULL escalations: {metrics['fast_full_escalations']}",
            f"- Shadow samples: {metrics['shadow']['samples']}",
            f"- Shadow divergences: {metrics['shadow']['diverged']}",
            f"- FAST false negatives observed by shadow FULL: {metrics['shadow']['false_negatives']}","",
            "| Phase | p50 | p95 | Samples |","| --- | ---: | ---: | ---: |",
        ]
        for key,label in (("planner_ms","Planner ms"),("preflight_seconds","Preflight s"),("build_seconds","Build s"),("runtime_seconds","Runtime s"),("estimated_total_seconds","Estimated total s")):
            row=t[key]
            lines.append(f"| {label} | {row['p50']} | {row['p95']} | {row['count']} |")
        lines.extend(["","## Lane distribution",""])
        for key,value in sorted(metrics["lanes"].items()):
            lines.append(f"- {key}: {value}")
        Path(args.output_md).write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(metrics,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
