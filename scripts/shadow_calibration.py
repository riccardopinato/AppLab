#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
MAP={"system":"system_lab","performance":"performance_lab","network":"network_lab","persistence":"persistence_lab","configuration":"configuration_lab","resource_pressure":"resource_pressure_lab","background":"background_lab","storage":"storage_lab","upgrade":"upgrade_lab"}
NON_APPLICABLE={"SKIPPED","N/A","NO_BASELINE"}
def compare(plan:dict,result:dict)->dict:
    predicted=plan.get("predicted_selected_labs",plan.get("selected_labs",{}))
    divergences=[]; false_neg=[]; over_selection=[]
    for lab,field in MAP.items():
        actual=str(result.get(field,"SKIPPED")).upper()
        selected=bool(predicted.get(lab,False))
        if not selected and actual not in NON_APPLICABLE:
            divergences.append({"lab":lab,"actual":actual,"kind":"predicted_skip_but_full_executed"})
            if actual in {"FAIL","ERROR"}: false_neg.append(lab)
        if selected and actual in NON_APPLICABLE:
            over_selection.append(lab)
    selected_count=sum(bool(v) for v in predicted.values())
    return {"schema_version":2,"shadow_full":bool(plan.get("shadow_full")),"divergences":divergences,
            "false_negative_labs":false_neg,"false_negative_count":len(false_neg),
            "over_selection_labs":over_selection,"over_selection_count":len(over_selection),
            "predicted_selected_count":selected_count,
            "predicted_selection_ratio":round(selected_count/max(1,len(MAP)),4),
            "safe":len(false_neg)==0}
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--plan"); ap.add_argument("--result"); ap.add_argument("--output"); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test:
        x=compare({"shadow_full":True,"predicted_selected_labs":{"network":False,"storage":True}},{"network_lab":"FAIL","storage_lab":"SKIPPED"})
        assert x["false_negative_count"]==1 and x["over_selection_count"]==1
        print("AppLab shadow calibration self-test PASS"); return 0
    payload=compare(json.loads(Path(a.plan).read_text()),json.loads(Path(a.result).read_text()))
    Path(a.output).write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
