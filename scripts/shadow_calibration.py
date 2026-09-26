#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
MAP={"system":"system_lab","performance":"performance_lab","network":"network_lab","persistence":"persistence_lab","configuration":"configuration_lab","resource_pressure":"resource_pressure_lab","background":"background_lab","storage":"storage_lab","upgrade":"upgrade_lab"}
def compare(plan:dict,result:dict)->dict:
    predicted=plan.get("predicted_selected_labs",plan.get("selected_labs",{})); divergences=[]; false_neg=[]
    for lab,field in MAP.items():
        actual=str(result.get(field,"SKIPPED")).upper()
        if not predicted.get(lab,False) and actual not in {"SKIPPED","N/A","NO_BASELINE"}:
            divergences.append({"lab":lab,"actual":actual})
            if actual in {"FAIL","ERROR"}: false_neg.append(lab)
    return {"schema_version":1,"shadow_full":bool(plan.get("shadow_full")),"divergences":divergences,
            "false_negative_labs":false_neg,"false_negative_count":len(false_neg),
            "safe":len(false_neg)==0}
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--plan"); ap.add_argument("--result"); ap.add_argument("--output"); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test:
        x=compare({"shadow_full":True,"predicted_selected_labs":{"network":False}},{"network_lab":"FAIL"})
        assert x["false_negative_count"]==1; print("AppLab shadow calibration self-test PASS"); return 0
    payload=compare(json.loads(Path(a.plan).read_text()),json.loads(Path(a.result).read_text()))
    Path(a.output).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
