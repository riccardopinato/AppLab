#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, statistics, tempfile
from pathlib import Path
from typing import Any
import durable_queue_v54e as queue_mod
import durable_store_v54b as storemod

PILOT_REPOSITORIES=("riccardopinato/AppLab","riccardopinato/CamperBoss","riccardopinato/TrailPath")

def percentile(values:list[float], p:float)->float:
    ordered=sorted(values)
    if not ordered: return 0.0
    k=(len(ordered)-1)*p
    lo=int(k); hi=min(lo+1,len(ordered)-1); frac=k-lo
    return ordered[lo]*(1-frac)+ordered[hi]*frac

def self_test()->dict[str,Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"multi-repo.sqlite3"
        with storemod.SQLiteShadowStore(path) as store:
            q=queue_mod.DurablePerRepoQueue(store,max_ready_global=6,max_ready_per_repo=2,max_pending_global=12,max_pending_per_repo=4,max_active_global=2,max_active_per_repo=1,lease_seconds=30,retry_base_seconds=2)
            enqueued:dict[str,float]={}; priorities=[200,400,300,500]
            n=0
            for round_no in range(4):
                for repo_no,repo in enumerate(PILOT_REPOSITORIES):
                    n+=1; opid=f"v55d-{repo_no}-{round_no}"; now=1000.0+n
                    op=queue_mod._persist_operation(store,opid,repo,"refs/heads/main",f"{n:040x}",priority=priorities[round_no])
                    q.enqueue(op["operation_id"],now_ts=now); enqueued[opid]=now
            snapshot=q.snapshot()
            assert len(snapshot)==12
            assert all(sum(1 for x in snapshot if x["repository"]==r)<=4 for r in PILOT_REPOSITORIES)
            assert any(x["state"]=="DEFERRED" for x in snapshot)

            claims=[]; starts=[]; runtimes=[]; clock=1100.0
            while True:
                q.rebalance(now_ts=clock)
                claim=q.claim_next(f"worker-{len(claims)}",now_ts=clock)
                if claim is None:
                    pending=[x for x in q.snapshot() if x["state"] in {"QUEUED","DEFERRED"}]
                    if not pending: break
                    clock+=1; continue
                claims.append(claim)
                starts.append(clock-enqueued[claim["operation_id"]])
                runtime=2.0+(len(claims)%4); runtimes.append(runtime)
                q.complete(claim["operation_id"],claim["worker_id"],now_ts=clock+runtime)
                clock+=runtime
            assert len(claims)==12
            first_six={x["repository"] for x in claims[:6]}
            assert first_six==set(PILOT_REPOSITORIES)
            assert q.integrity_report()["ok"] is True
            assert all(x["state"]=="DONE" for x in q.snapshot())
            repo_claims={r:sum(1 for x in claims if x["repository"]==r) for r in PILOT_REPOSITORIES}
            assert set(repo_claims.values())=={4}
            return {
              "schema_version":1,"record_type":"APPLAB_V55D_MULTI_REPO_QUEUE_PROOF","status":"PASS",
              "repositories":list(PILOT_REPOSITORIES),"operations":len(claims),
              "fairness":{"claims_per_repository":repo_claims,"all_repositories_in_first_six":True},
              "priority":{"aging_enabled":True,"max_age_bonus":q.max_age_bonus},
              "backpressure":{"deferred_observed":True,"global_pending_limit":q.max_pending_global,"per_repo_pending_limit":q.max_pending_per_repo},
              "repository_isolation":{"max_active_per_repo":q.max_active_per_repo,"integrity_ok":True},
              "telemetry":{"queue_start_seconds":{"p50":percentile(starts,.5),"p95":percentile(starts,.95)},"runtime_seconds":{"p50":percentile(runtimes,.5),"p95":percentile(runtimes,.95)}},
              "authority":"ORCHESTRATION_ONLY","coverage_reduction_enabled":False,"github_actions_fallback":True,
              "smart_test_plan_authority":"UNCHANGED","trusted_verifier_authority":"UNCHANGED","release_assurance_authority":"UNCHANGED","production_certification_authority":"UNCHANGED"
            }

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if not a.self_test: p.error("--self-test is required")
    print(json.dumps(self_test(),indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
