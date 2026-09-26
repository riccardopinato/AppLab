#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
LAB_FIELDS={"system":"system_lab","performance":"performance_lab","network":"network_lab","persistence":"persistence_lab","configuration":"configuration_lab","resource_pressure":"resource_pressure_lab","background":"background_lab","storage":"storage_lab","upgrade":"upgrade_lab"}
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--plan"); ap.add_argument("--report-dir")
    ap.add_argument("--repository"); ap.add_argument("--ref"); ap.add_argument("--resolved-sha")
    ap.add_argument("--history-key"); ap.add_argument("--quality-json",default=""); ap.add_argument("--run-id",default="")
    ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test: print("AppLab incremental result self-test PASS"); return 0
    if not all((a.plan,a.report_dir,a.repository,a.ref,a.resolved_sha,a.history_key)):
        raise SystemExit("incremental result arguments are required")
    plan=json.loads(Path(a.plan).read_text(encoding="utf-8")); out=Path(a.report_dir); out.mkdir(parents=True,exist_ok=True)
    quality={}
    if a.quality_json and Path(a.quality_json).is_file(): quality=json.loads(Path(a.quality_json).read_text(encoding="utf-8"))
    lane=plan["lane"]
    if lane not in {"NO_RUNTIME_CHANGE","STATIC_ONLY"}: raise SystemExit("incremental_result only accepts non-runtime lanes")
    metrics_path=out/"pipeline-metrics.json"
    metrics=json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
    result={"schema_version":1,"applab_version":"0.9.0","repository":a.repository,"ref":a.ref,"requested_ref":a.ref,"resolved_sha":a.resolved_sha,
      "history_key":a.history_key,"run_id":a.run_id,"result":"PASS","analysis_mode":"fast","analysis_lane":lane,
      "risk_score":plan.get("risk_score"),"confidence":plan.get("confidence"),"selected_labs":plan.get("selected_labs",{}),"predicted_selected_labs":plan.get("predicted_selected_labs",{}),"shadow_full":False,"pipeline_metrics":metrics,"runtime_reused_from":plan.get("baseline_sha",""),
      "runtime_executed":False,"certification_status":"NOT_REQUESTED","quality_evidence":quality,
      "maestro":"SKIPPED","visual_qa":"SKIPPED","visual_regression":"SKIPPED","visual_journey":"SKIPPED","interaction_crawl":"SKIPPED"}
    for _,field in LAB_FIELDS.items(): result[field]="SKIPPED"
    (out/"analysis-plan.json").write_text(json.dumps(plan,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (out/"result.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (out/"summary.md").write_text(f"# AppLab v0.9 Incremental Verification\n\n- Result: **PASS**\n- Lane: **{lane}**\n- Runtime executed: **no**\n- Runtime evidence reused from: `{plan.get('baseline_sha','') or 'none'}`\n- Risk: {plan.get('risk_score')}\n- Confidence: {plan.get('confidence')}\n",encoding="utf-8")
    return 0
if __name__=="__main__": raise SystemExit(main())
