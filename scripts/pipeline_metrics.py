#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def read_json(path: str) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {}
    try:
        value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError):
        return {}
    return value if isinstance(value,dict) else {}

def as_bool(value: str) -> bool | None:
    raw=str(value or "").strip().lower()
    if raw in {"true","1","yes"}: return True
    if raw in {"false","0","no"}: return False
    return None

def parse_started_at(value:str)->datetime|None:
    raw=str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z","+00:00"))
    except ValueError:
        return None

def summarize(plan:dict,quality:dict|None=None,shadow:dict|None=None,runtime:dict|None=None,
              avd_cache_hit:bool|None=None,maestro_cache_hit:bool|None=None,
              workflow_started_at:str="")->dict:
    q=quality or {}; s=shadow or {}; r=runtime or {}
    timings={k:float(v) for k,v in (q.get("timings") or {}).items() if isinstance(v,(int,float))}
    runtime_seconds=float(r.get("runtime_seconds",0) or 0)
    quality_seconds=sum(timings.values())
    planner_seconds=float(plan.get("planner_ms",0) or 0)/1000.0
    observed=round(planner_seconds+quality_seconds+runtime_seconds,3)
    started=parse_started_at(workflow_started_at)
    wall_clock_seconds=None
    setup_overhead_seconds=None
    if started is not None:
        now=datetime.now(timezone.utc)
        if started.tzinfo is None:
            started=started.replace(tzinfo=timezone.utc)
        wall_clock_seconds=round(max(0.0,(now-started).total_seconds()),3)
        setup_overhead_seconds=round(max(0.0,wall_clock_seconds-observed),3)
    budget_raw=plan.get("verification_budget_seconds")
    budget_seconds=float(budget_raw) if isinstance(budget_raw,(int,float)) and budget_raw>0 else None
    budget_exceeded=(
        bool(wall_clock_seconds is not None and budget_seconds is not None and wall_clock_seconds>budget_seconds)
    )
    budget_ratio=(
        round(wall_clock_seconds/budget_seconds,4)
        if wall_clock_seconds is not None and budget_seconds is not None else None
    )
    return {
      "schema_version":3,
      "planner_ms":plan.get("planner_ms",0),
      "lane":plan.get("lane"),
      "risk_score":plan.get("risk_score"),
      "confidence":plan.get("confidence"),
      "changed_file_count":len(plan.get("changed_files",[])),
      "impacted_file_count":len(plan.get("impacted_files",[])),
      "selected_lab_count":sum(bool(v) for v in plan.get("selected_labs",{}).values()),
      "shadow_full":bool(plan.get("shadow_full")),
      "shadow_divergence_count":len(s.get("divergences",[])),
      "shadow_false_negative_count":int(s.get("false_negative_count",0) or 0),
      "shadow_missed_warning_count":int(s.get("missed_warning_count",0) or 0),
      "shadow_missing_baseline_count":int(s.get("missing_baseline_count",0) or 0),
      "shadow_over_selection_count":int(s.get("over_selection_count",0) or 0),
      "predicted_selection_ratio":s.get("predicted_selection_ratio"),
      "timings":timings,
      "runtime_seconds":round(runtime_seconds,3),
      "quality_seconds":round(quality_seconds,3),
      "total_observed_seconds":observed,
      "wall_clock_seconds":wall_clock_seconds,
      "setup_overhead_seconds":setup_overhead_seconds,
      "verification_budget_seconds":budget_seconds,
      "budget_exceeded":budget_exceeded,
      "budget_ratio":budget_ratio,
      "historical_lane_p95_seconds":plan.get("historical_lane_p95_seconds"),
      "budget_pressure":bool(plan.get("budget_pressure",False)),
      "learning_applied_lab_count":len(plan.get("learning_applied_labs",[]) or []),
      "avd_cache_hit":avd_cache_hit,
      "maestro_cache_hit":maestro_cache_hit,
    }

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--plan"); ap.add_argument("--quality",default=""); ap.add_argument("--shadow",default="")
    ap.add_argument("--runtime-timing",default=""); ap.add_argument("--avd-cache-hit",default="")
    ap.add_argument("--maestro-cache-hit",default=""); ap.add_argument("--workflow-started-at",default="")
    ap.add_argument("--output"); ap.add_argument("--self-test",action="store_true")
    a=ap.parse_args()
    if a.self_test:
        x=summarize({"selected_labs":{},"changed_files":[],"planner_ms":1000},{"timings":{"build_seconds":2}},runtime={"runtime_seconds":3})
        assert x["selected_lab_count"]==0 and x["total_observed_seconds"]==6.0
        assert x["wall_clock_seconds"] is None
        y=summarize(
            {"selected_labs":{},"changed_files":[],"verification_budget_seconds":1},
            workflow_started_at="2000-01-01T00:00:00Z",
        )
        assert y["budget_exceeded"] and y["budget_ratio"] is not None
        print("AppLab pipeline metrics self-test PASS"); return 0
    if not a.plan or not a.output: raise SystemExit("--plan and --output are required")
    p=read_json(a.plan); q=read_json(a.quality); s=read_json(a.shadow); r=read_json(a.runtime_timing)
    payload=summarize(
        p,q,s,r,as_bool(a.avd_cache_hit),as_bool(a.maestro_cache_hit),a.workflow_started_at
    )
    Path(a.output).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return 0
if __name__=="__main__": raise SystemExit(main())
