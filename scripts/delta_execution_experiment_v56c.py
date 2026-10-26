#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any

def build_experiment(cal:dict[str,Any])->dict[str,Any]:
    ready=cal.get("state")=="READY_FOR_EXPERIMENT"
    summary=cal.get("summary") if isinstance(cal.get("summary"),dict) else {}
    candidates=cal.get("lab_candidates") if isinstance(cal.get("lab_candidates"),list) else []
    false_neg=int(summary.get("false_negatives",0) or 0)
    missed=int(summary.get("missed_warnings",0) or 0)
    missing=int(summary.get("missing_baselines",0) or 0)
    safe=ready and false_neg==0 and missed==0 and missing==0 and bool(candidates)
    return {
      "schema_version":1,
      "record_type":"DELTA_EXECUTION_CONTROLLED_EXPERIMENT",
      "authority":"SHADOW_ADVISORY_ONLY",
      "state":"SHADOW_ELIGIBLE" if safe else "HOLD",
      "coverage_reduction_enabled":False,
      "production_behavior_changed":False,
      "candidate_labs":sorted(str(x) for x in candidates),
      "safety":{"false_negatives":false_neg,"missed_warnings":missed,"missing_baselines":missing},
      "readiness_source_state":str(cal.get("state","UNKNOWN")),
      "guardrails":{
        "smart_test_plan_remains_single_authority":True,
        "full_shadow_comparison_required":True,
        "promotion_requires_separate_exact_head_change":True
      }
    }

def self_test():
    good=build_experiment({"state":"READY_FOR_EXPERIMENT","summary":{"false_negatives":0,"missed_warnings":0,"missing_baselines":0},"lab_candidates":["network","storage"]})
    assert good["state"]=="SHADOW_ELIGIBLE"
    assert good["coverage_reduction_enabled"] is False
    assert good["production_behavior_changed"] is False
    bad=build_experiment({"state":"READY_FOR_EXPERIMENT","summary":{"false_negatives":1,"missed_warnings":0,"missing_baselines":0},"lab_candidates":["network"]})
    assert bad["state"]=="HOLD"
    incomplete=build_experiment({"state":"COLLECTING","summary":{},"lab_candidates":[]})
    assert incomplete["state"]=="HOLD"
    print("AppLab v5.6C delta experiment self-test PASS")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--calibration",default=""); p.add_argument("--output",default=""); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.calibration: raise SystemExit("--calibration is required")
    data=json.loads(Path(a.calibration).read_text(encoding="utf-8"))
    out=build_experiment(data)
    if a.output: Path(a.output).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(out,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
