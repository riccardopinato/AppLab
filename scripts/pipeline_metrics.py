#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def summarize(plan:dict,quality:dict|None=None,shadow:dict|None=None)->dict:
    q=quality or {}; s=shadow or {}
    return {"schema_version":1,"planner_ms":plan.get("planner_ms",0),"lane":plan.get("lane"),
      "risk_score":plan.get("risk_score"),"confidence":plan.get("confidence"),"changed_file_count":len(plan.get("changed_files",[])),
      "impacted_file_count":len(plan.get("impacted_files",[])),"selected_lab_count":sum(bool(v) for v in plan.get("selected_labs",{}).values()),
      "shadow_full":bool(plan.get("shadow_full")),"shadow_divergence_count":len(s.get("divergences",[])),
      "shadow_false_negative_count":int(s.get("false_negative_count",0) or 0),"timings":q.get("timings",{})}
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--plan"); ap.add_argument("--quality",default=""); ap.add_argument("--shadow",default=""); ap.add_argument("--output"); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test: assert summarize({"selected_labs":{},"changed_files":[]})["selected_lab_count"]==0; print("AppLab pipeline metrics self-test PASS"); return 0
    p=json.loads(Path(a.plan).read_text()); q=json.loads(Path(a.quality).read_text()) if a.quality and Path(a.quality).is_file() else {}; s=json.loads(Path(a.shadow).read_text()) if a.shadow and Path(a.shadow).is_file() else {}
    Path(a.output).write_text(json.dumps(summarize(p,q,s),indent=2,sort_keys=True)+"\n"); return 0
if __name__=="__main__": raise SystemExit(main())
