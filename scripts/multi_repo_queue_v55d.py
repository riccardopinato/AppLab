#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, tempfile
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

def persist(store:storemod.SQLiteShadowStore, opid:str, repo:str, sha_seed:int, priority:int=200):
    return queue_mod._persist_operation(
        store,opid,repo,"refs/heads/main",f"{sha_seed:040x}",priority=priority
    )

def expect_capacity_rejection(q:queue_mod.DurablePerRepoQueue, operation_id:str, now:float)->str:
    before=len(q.snapshot())
    try:
        q.enqueue(operation_id,now_ts=now)
    except queue_mod.QueueError as exc:
        assert "pending queue capacity exhausted" in str(exc)
        assert len(q.snapshot())==before
        return str(exc)
    raise AssertionError("pending overflow was accepted")

def self_test()->dict[str,Any]:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)

        # Primary bounded multi-repository workload: valid durable IDs, explicit
        # priority ordering, overlapping leases, fairness and telemetry.
        with storemod.SQLiteShadowStore(root/"load.sqlite3") as store:
            q=queue_mod.DurablePerRepoQueue(
                store,max_ready_global=6,max_ready_per_repo=2,
                max_pending_global=12,max_pending_per_repo=4,
                max_active_global=2,max_active_per_repo=1,
                lease_seconds=30,retry_base_seconds=2,max_age_bonus=50,
            )
            enqueued:dict[str,float]={}; n=0
            priorities=[200,400,300,500]
            for round_no in range(4):
                for repo_no,repo in enumerate(PILOT_REPOSITORIES):
                    n+=1; opid=f"op_v55d-{repo_no}-{round_no}"; now=1000.0+n
                    op=persist(store,opid,repo,n,priorities[round_no])
                    q.enqueue(op["operation_id"],now_ts=now); enqueued[opid]=now
            snapshot=q.snapshot()
            assert len(snapshot)==12
            assert any(x["state"]=="DEFERRED" for x in snapshot)

            # Highest priority must win, while fairness breaks equal-priority
            # candidates across repositories. Keep two cross-repo leases active
            # to prove the global limit, and prove a second lease from the same
            # repository is ineligible while its first lease is outstanding.
            q.rebalance(now_ts=1100.0)
            first=q.claim_next("worker-0",now_ts=1100.0)
            assert first is not None
            assert q._entry(first["operation_id"])["priority"]==500
            same_repo_ready=[
                x for x in q.snapshot()
                if x["repository"]==first["repository"] and x["state"]=="QUEUED"
            ]
            assert same_repo_ready
            second=q.claim_next("worker-1",now_ts=1100.1)
            assert second is not None and second["repository"]!=first["repository"]
            assert q._active_count()==2
            assert q._repo_active_count(first["repository"])==1
            assert q._repo_active_count(second["repository"])==1
            assert q.claim_next("worker-overflow",now_ts=1100.2) is None
            assert q.integrity_report()["ok"] is True

            claims=[first,second]
            starts=[
                1100.0-enqueued[first["operation_id"]],
                1100.1-enqueued[second["operation_id"]],
            ]
            runtimes=[3.0,4.0]
            q.complete(first["operation_id"],first["worker_id"],now_ts=1103.0)
            q.complete(second["operation_id"],second["worker_id"],now_ts=1104.1)
            clock=1105.0
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
            assert {x["repository"] for x in claims[:6]}==set(PILOT_REPOSITORIES)
            repo_claims={r:sum(1 for x in claims if x["repository"]==r) for r in PILOT_REPOSITORIES}
            assert set(repo_claims.values())=={4}
            assert q.integrity_report()["ok"] is True
            assert all(x["state"]=="DONE" for x in q.snapshot())

        # Aging proof: a lower-priority operation aged by 31 minutes must beat a
        # fresh operation whose base priority is only 30 points higher.
        with storemod.SQLiteShadowStore(root/"aging.sqlite3") as store:
            aq=queue_mod.DurablePerRepoQueue(
                store,max_ready_global=4,max_ready_per_repo=4,
                max_pending_global=8,max_pending_per_repo=8,
                max_active_global=1,max_active_per_repo=1,max_age_bonus=50,
            )
            aged=persist(store,"op_aged","owner/aging",300,200)
            fresh=persist(store,"op_fresh","owner/aging",301,230)
            aq.enqueue(aged["operation_id"],now_ts=1000.0)
            aq.enqueue(fresh["operation_id"],now_ts=2860.0)
            assert aq._effective_priority(aq._entry(aged["operation_id"]),2860.0)==231
            assert aq._effective_priority(aq._entry(fresh["operation_id"]),2860.0)==230
            aging_claim=aq.claim_next("aging-worker",now_ts=2860.0)
            assert aging_claim and aging_claim["operation_id"]==aged["operation_id"]

        # Repository isolation proof: with global capacity still available and
        # only same-repository work ready, a second lease must be refused while
        # the first lease remains active. This isolates the per-repository gate
        # from global capacity and priority/fairness ordering.
        with storemod.SQLiteShadowStore(root/"repo-isolation.sqlite3") as store:
            iq=queue_mod.DurablePerRepoQueue(
                store,max_ready_global=3,max_ready_per_repo=3,
                max_pending_global=4,max_pending_per_repo=4,
                max_active_global=2,max_active_per_repo=1,
            )
            iso_a=persist(store,"op_iso-a","owner/isolation",400,300)
            iso_b=persist(store,"op_iso-b","owner/isolation",401,200)
            iq.enqueue(iso_a["operation_id"],now_ts=400.0)
            iq.enqueue(iso_b["operation_id"],now_ts=401.0)
            iso_first=iq.claim_next("iso-worker-0",now_ts=402.0)
            assert iso_first is not None
            assert iq._active_count()==1 < iq.max_active_global
            assert iq._repo_active_count("owner/isolation")==1
            assert iq.claim_next("iso-worker-1",now_ts=402.1) is None
            assert iq._entry(iso_b["operation_id"])["state"]=="QUEUED"
            iq.complete(iso_first["operation_id"],iso_first["worker_id"],now_ts=403.0)
            iso_second=iq.claim_next("iso-worker-1",now_ts=403.1)
            assert iso_second is not None and iso_second["operation_id"]==iso_b["operation_id"]

        # Per-repository pending overflow while global capacity remains free.
        with storemod.SQLiteShadowStore(root/"repo-cap.sqlite3") as store:
            rq=queue_mod.DurablePerRepoQueue(
                store,max_ready_global=5,max_ready_per_repo=2,
                max_pending_global=5,max_pending_per_repo=2,
                max_active_global=1,max_active_per_repo=1,
            )
            for i in range(3):
                op=persist(store,f"op_rpcap-{i}","owner/repo-cap",100+i)
                if i<2: rq.enqueue(op["operation_id"],now_ts=100+i)
                else: repo_rejection=expect_capacity_rejection(rq,op["operation_id"],102.0)
            assert rq._pending_count()==2 and rq._pending_count()<rq.max_pending_global

        # Global pending overflow with no repository at its per-repo cap.
        with storemod.SQLiteShadowStore(root/"global-cap.sqlite3") as store:
            gq=queue_mod.DurablePerRepoQueue(
                store,max_ready_global=3,max_ready_per_repo=2,
                max_pending_global=3,max_pending_per_repo=3,
                max_active_global=1,max_active_per_repo=1,
            )
            repos=("owner/a","owner/b","owner/c","owner/d")
            for i,repo in enumerate(repos):
                op=persist(store,f"op_glcap-{i}",repo,200+i)
                if i<3: gq.enqueue(op["operation_id"],now_ts=200+i)
                else: global_rejection=expect_capacity_rejection(gq,op["operation_id"],203.0)
            assert gq._pending_count()==3
            assert all(gq._repo_pending_count(r)<gq.max_pending_per_repo for r in repos[:3])

        return {
          "schema_version":1,"record_type":"APPLAB_V55D_MULTI_REPO_QUEUE_PROOF","status":"PASS",
          "repositories":list(PILOT_REPOSITORIES),"operations":len(claims),
          "fairness":{"claims_per_repository":repo_claims,"all_repositories_in_first_six":True},
          "priority":{"highest_priority_claimed_first":True,"aging_order_change_proven":True,"max_age_bonus":50},
          "backpressure":{
              "deferred_observed":True,
              "global_pending_overflow_rejected":"global pending" in global_rejection,
              "per_repo_pending_overflow_rejected":"repository pending" in repo_rejection,
              "global_pending_limit":12,"per_repo_pending_limit":4,
          },
          "repository_isolation":{
              "overlapping_cross_repo_leases":True,
              "same_repo_second_lease_blocked":True,
              "global_active_limit_observed":True,
              "max_active_per_repo":1,"integrity_ok":True,
          },
          "telemetry":{
              "queue_start_seconds":{"p50":percentile(starts,.5),"p95":percentile(starts,.95)},
              "runtime_seconds":{"p50":percentile(runtimes,.5),"p95":percentile(runtimes,.95)},
          },
          "authority":"ORCHESTRATION_ONLY","coverage_reduction_enabled":False,
          "github_actions_fallback":True,"smart_test_plan_authority":"UNCHANGED",
          "trusted_verifier_authority":"UNCHANGED","release_assurance_authority":"UNCHANGED",
          "production_certification_authority":"UNCHANGED"
        }

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if not a.self_test: p.error("--self-test is required")
    print(json.dumps(self_test(),indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
