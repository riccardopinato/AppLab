#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

LAB_FIELDS = (
    "system_lab","network_lab","persistence_lab","configuration_lab",
    "resource_pressure_lab","background_lab","storage_lab","upgrade_lab","performance_lab",
)

def compare(fast: dict, full: dict) -> dict:
    fast_result = str(fast.get("result","")).upper()
    full_result = str(full.get("result","")).upper()
    missed_failures = []
    divergences = []
    for field in LAB_FIELDS:
        fv = str(fast.get(field,"SKIPPED")).upper()
        uv = str(full.get(field,"SKIPPED")).upper()
        if fv != uv:
            divergences.append({"gate":field,"fast":fv,"full":uv})
        if fv in {"SKIPPED","NO_BASELINE"} and uv in {"FAIL","ERROR"}:
            missed_failures.append(field)
    critical = bool(missed_failures) or (fast_result == "PASS" and full_result == "FAIL")
    return {
        "schema_version":1,
        "applab_version":"0.9.0",
        "fast_result":fast_result,
        "full_result":full_result,
        "critical_divergence":critical,
        "false_negative":critical,
        "missed_failure_gates":missed_failures,
        "divergences":divergences,
        "fast_lane":fast.get("analysis_lane") or fast.get("adaptive_plan",{}).get("lane",""),
        "fast_risk":fast.get("risk") or fast.get("adaptive_plan",{}).get("risk",{}),
        "fast_confidence":fast.get("confidence") or fast.get("adaptive_plan",{}).get("confidence",{}),
    }

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--fast",required=True); p.add_argument("--full",required=True)
    p.add_argument("--output-json",required=True); p.add_argument("--output-md",required=True)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        row=compare({"result":"PASS","network_lab":"SKIPPED"},{"result":"FAIL","network_lab":"FAIL"})
        assert row["false_negative"] and row["missed_failure_gates"]==["network_lab"]
        print("AppLab shadow calibration self-test PASS"); return 0
    fast=json.loads(Path(a.fast).read_text(encoding="utf-8"))
    full=json.loads(Path(a.full).read_text(encoding="utf-8"))
    out=compare(fast,full)
    Path(a.output_json).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    lines=["# AppLab FAST/FULL Shadow Calibration","",
           f"- FAST: {out['fast_result']}",f"- FULL: {out['full_result']}",
           f"- Critical divergence: {'yes' if out['critical_divergence'] else 'no'}",
           f"- Missed failing gates: {', '.join(out['missed_failure_gates']) or 'none'}",""]
    Path(a.output_md).write_text("\n".join(lines)+"\n",encoding="utf-8")
    return 2 if out["critical_divergence"] else 0

if __name__=="__main__": raise SystemExit(main())
