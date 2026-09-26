#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path

def load_history(path: Path) -> list[dict]:
    rows=[]
    if not path.is_file(): return rows
    for raw in path.read_text(encoding="utf-8",errors="ignore").splitlines():
        try: item=json.loads(raw)
        except json.JSONDecodeError: continue
        if isinstance(item,dict): rows.append(item)
    return rows

def build(rows: list[dict]) -> dict:
    adaptive=[r for r in rows if str(r.get("applab_version","")).startswith("0.9")]
    lanes=Counter(str(r.get("analysis_lane") or r.get("adaptive_plan",{}).get("lane","unknown")) for r in adaptive)
    modes=Counter(str(r.get("analysis_mode","unknown")) for r in adaptive)
    risks=Counter(str((r.get("risk") or r.get("adaptive_plan",{}).get("risk",{})).get("level","unknown")) for r in adaptive)
    confidences=[]
    for r in adaptive:
        raw=(r.get("confidence") or r.get("adaptive_plan",{}).get("confidence",{})).get("score")
        try: confidences.append(float(raw))
        except (TypeError,ValueError): pass
    shadows=[r.get("shadow_calibration") for r in adaptive if isinstance(r.get("shadow_calibration"),dict)]
    false_negatives=sum(1 for s in shadows if s.get("false_negative"))
    return {
        "schema_version":1,"applab_version":"0.9.0","samples":len(adaptive),
        "lanes":dict(lanes),"modes":dict(modes),"risk_levels":dict(risks),
        "average_confidence": round(sum(confidences)/len(confidences),3) if confidences else None,
        "shadow_samples":len(shadows),"shadow_false_negatives":false_negatives,
        "shadow_false_negative_rate": round(false_negatives/len(shadows),4) if shadows else None,
    }

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--history"); p.add_argument("--output"); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test:
        out=build([{"applab_version":"0.9.0","analysis_lane":"no_runtime","confidence":{"score":1.0}}])
        assert out["samples"]==1 and out["lanes"]["no_runtime"]==1
        print("AppLab adaptive telemetry self-test PASS"); return 0
    if not a.history or not a.output: raise SystemExit("--history and --output are required")
    out=build(load_history(Path(a.history)))
    Path(a.output).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(out,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
