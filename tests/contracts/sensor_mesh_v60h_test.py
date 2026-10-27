#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import sensor_mesh_v60h as mod  # noqa: E402

def main()->int:
    mod.self_test()
    low=mod.plan_sensors({"repository":"owner/app","source_sha":"a"*40,"risk":"LOW","changed_files":["README.md"]})
    assert low["producer_count"]==0
    dep=mod.plan_sensors({"repository":"owner/app","source_sha":"a"*40,"risk":"NORMAL","changed_files":["pubspec.lock"]})
    assert {x["producer"] for x in dep["selected_producers"]}=={"TRIVY"}
    net=mod.plan_sensors({"repository":"owner/app","source_sha":"a"*40,"risk":"NORMAL","changed_files":["lib/api.dart"],"network_replay_allowed":False})
    assert "HETTY" not in {x["producer"] for x in net["selected_producers"]}
    assert "SEMGREP" in {x["producer"] for x in net["selected_producers"]}
    print("AppLab v6.0H sensor mesh contract PASS")
    return 0
if __name__=="__main__": raise SystemExit(main())
