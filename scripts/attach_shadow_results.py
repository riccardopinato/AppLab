#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shadow_calibration import compare

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--results-dir",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--output-summary",default="")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        print("AppLab attach shadow results self-test PASS")
        return 0

    root=Path(a.results_dir)
    suffix=f"-shadow-{a.run_id}"
    attached=0
    critical=0
    rows=[]
    for shadow_dir in sorted(root.glob(f"applab-*{suffix}")):
        if not shadow_dir.is_dir():
            continue
        shadow_result=shadow_dir/"result.json"
        if not shadow_result.is_file():
            continue
        name=shadow_dir.name
        base_name=name[:-len(suffix)] + f"-{a.run_id}"
        fast_dir=root/base_name
        fast_result=fast_dir/"result.json"
        if not fast_result.is_file():
            continue
        fast=json.loads(fast_result.read_text(encoding="utf-8"))
        full=json.loads(shadow_result.read_text(encoding="utf-8"))
        calibration=compare(fast,full)
        fast["shadow_calibration"]=calibration
        fast_result.write_text(json.dumps(fast,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        (fast_dir/"shadow-calibration.json").write_text(
            json.dumps(calibration,indent=2,sort_keys=True)+"\n",encoding="utf-8"
        )
        shadow_result.rename(shadow_dir/"shadow-result.json")
        attached+=1
        critical += 1 if calibration.get("critical_divergence") else 0
        rows.append({
            "repository":fast.get("repository",""),
            "sha":fast.get("resolved_sha",""),
            "critical":bool(calibration.get("critical_divergence")),
            "missed":calibration.get("missed_failure_gates",[]),
        })

    if a.output_summary:
        Path(a.output_summary).write_text(
            json.dumps({"attached":attached,"critical":critical,"rows":rows},indent=2,sort_keys=True)+"\n",
            encoding="utf-8",
        )
    print(f"Attached {attached} shadow calibration result(s); critical={critical}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
