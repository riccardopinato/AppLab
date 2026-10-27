#!/usr/bin/env python3
from __future__ import annotations
import copy, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import agent_memory_v60f as mod  # noqa: E402

def main()->int:
    mod.self_test()
    contract=mod.load_contract()
    base={
      "schema_version":1,"record_type":"APPLAB_AGENT_EPISODE","episode_id":"ep_fixture",
      "repository":"owner/app","source_sha":"b"*40,"failure_signature":"sha256:"+"1"*64,
      "failure_class":"APP_RUNTIME_FAILURE","surfaces":[],"candidate_files":[],
      "repair_outcome":"STOPPED","successful_patterns":[],"failed_patterns":[{"attempt":1}],
      "regression_targets":[],"evidence_refs":[],"source_records":[],
      "guardrails":{"policy_mutation_authority":"NONE"}
    }
    mod.validate_episode(base,contract)
    bad=copy.deepcopy(base); bad["guardrails"]["policy_mutation_authority"]="WRITE"
    try: mod.validate_episode(bad,contract)
    except mod.MemoryError as exc: assert "cannot mutate policy" in str(exc)
    else: raise AssertionError("policy-mutating memory accepted")
    memory=mod.merge_memory({"episodes":[]},[base])
    q=mod.query_memory(memory,repository="owner/other",failure_class="APP_RUNTIME_FAILURE")
    assert q["results"]==[]
    cross=mod.query_memory(memory,repository="owner/other",failure_class="APP_RUNTIME_FAILURE",allow_cross_repository=True)
    assert cross["results"] and "CROSS_REPOSITORY_ADVISORY_ONLY" in cross["results"][0]["reasons"]
    print("AppLab v6.0F episodic memory contract PASS")
    return 0
if __name__=="__main__": raise SystemExit(main())
