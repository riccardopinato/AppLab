#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import controlled_expansion_v55e as mod

def main()->int:
    proof=mod.self_test()
    assert proof["status"]=="PASS"
    assert len(proof["stage_3"])==3
    assert len(proof["stage_5"])==5
    assert proof["all_compatible_count"]>=5
    assert proof["global_kill_switch_proven"] is True
    assert proof["per_repo_kill_switch_proven"] is True
    assert proof["github_actions_fallback"] is True
    assert proof["watcher_reconciliation"] is True
    assert proof["coverage_reduction_enabled"] is False
    assert proof["authority"]=="ORCHESTRATION_ONLY"
    print("v5.5E controlled-expansion contract PASS")
    return 0
if __name__=="__main__":raise SystemExit(main())
