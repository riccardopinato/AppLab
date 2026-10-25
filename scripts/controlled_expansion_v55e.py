#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parent.parent
WATCHLIST=ROOT/"watchlist.json"
PILOT=ROOT/"integration"/"orchestration"/"v55-pilot.json"
CONFIG=ROOT/"integration"/"orchestration"/"v55e-expansion.json"
PILOT_REPOS=("riccardopinato/AppLab","riccardopinato/CamperBoss","riccardopinato/TrailPath")
SUPPORTED={"flutter","native_android","auto"}

class ExpansionError(ValueError): pass

def _load(path:Path)->dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def compatible_repositories()->list[str]:
    rows=_load(WATCHLIST)["repositories"]
    repos=[]
    for row in rows:
        if row.get("enabled") is True and row.get("engine") in SUPPORTED:
            repo=row.get("repository")
            if isinstance(repo,str) and repo and repo not in repos:
                repos.append(repo)
    return repos

def load_config()->dict[str,Any]:
    cfg=_load(CONFIG)
    if cfg.get("schema_version")!=1: raise ExpansionError("unsupported v5.5E config")
    if cfg.get("authority")!="ORCHESTRATION_ONLY": raise ExpansionError("authority drift")
    if cfg.get("coverage_reduction_enabled") is not False: raise ExpansionError("coverage reduction must remain disabled")
    if cfg.get("github_actions_fallback") is not True: raise ExpansionError("GitHub Actions fallback must remain enabled")
    if cfg.get("watcher_reconciliation") is not True: raise ExpansionError("watcher reconciliation must remain enabled")
    if not isinstance(cfg.get("global_kill_switch"),bool): raise ExpansionError("global kill switch must be boolean")
    if not isinstance(cfg.get("repository_kill_switches"),dict): raise ExpansionError("repository kill switches must be object")
    if cfg.get("rollout_stage") not in {"3","5","all"}: raise ExpansionError("rollout_stage must be 3, 5, or all")
    return cfg

def stage_repositories(stage:str)->list[str]:
    compatible=compatible_repositories()
    if any(repo not in compatible for repo in PILOT_REPOS):
        raise ExpansionError("pilot repository is no longer compatible")
    if stage=="3": return list(PILOT_REPOS)
    if stage=="5":
        extras=[r for r in compatible if r not in PILOT_REPOS]
        if len(extras)<2: raise ExpansionError("fewer than five compatible repositories")
        return list(PILOT_REPOS)+extras[:2]
    if stage=="all": return compatible
    raise ExpansionError("unsupported rollout stage")

def admission(repository:str,stage:str,config:dict[str,Any]|None=None)->dict[str,Any]:
    cfg=load_config() if config is None else config
    allowed=stage_repositories(stage)
    if repository not in allowed:
        return {"repository":repository,"stage":stage,"admitted":False,"reason":"OUTSIDE_STAGE"}
    if cfg["global_kill_switch"]:
        return {"repository":repository,"stage":stage,"admitted":False,"reason":"GLOBAL_KILL_SWITCH"}
    if cfg["repository_kill_switches"].get(repository,False):
        return {"repository":repository,"stage":stage,"admitted":False,"reason":"REPOSITORY_KILL_SWITCH"}
    return {"repository":repository,"stage":stage,"admitted":True,"reason":"CONTROLLED_EXPANSION"}

def live_control_config(repository:str,config:dict[str,Any]|None=None)->dict[str,Any]:
    cfg=load_config() if config is None else config
    stage=cfg["rollout_stage"]
    allowed=stage_repositories(stage)
    pilot=_load(PILOT)
    pilot_by_repo={row["repository"]:dict(row) for row in pilot["pilot_targets"]}
    watch_by_repo={row["repository"]:row for row in _load(WATCHLIST)["repositories"] if isinstance(row,dict) and row.get("repository")}
    targets=[]
    for repo in allowed:
        if repo in pilot_by_repo:
            target=pilot_by_repo[repo]
        else:
            row=watch_by_repo[repo]
            ref=str(row.get("ref") or "main")
            target={
                "repository":repo,
                "source_ref":f"refs/heads/{ref}",
                "event_types":["push","repository_dispatch","workflow_dispatch"],
                "run_maestro":bool(row.get("run_maestro",False)),
                "history_key":"v55e-"+repo.split("/",1)[-1].lower().replace("_","-"),
                "analysis_mode":"fast",
                "engine":row["engine"],
            }
        targets.append(target)
    stopped=bool(cfg["global_kill_switch"] or cfg["repository_kill_switches"].get(repository,False))
    return {
        "schema_version":1,
        "enabled":True,
        "kill_switch":stopped,
        "rollout":"MULTI_PROJECT_PILOT_SET",
        "max_live_operations_per_event":1,
        "ledger_authority":"NON_AUTHORITATIVE_PILOT_CONTINUITY",
        "pilot_targets":targets,
    }

def watcher_role(stage:str,evidence_sufficient:bool)->str:
    if stage=="all" and evidence_sufficient:
        return "RECONCILIATION_WATCHDOG"
    return "PRIMARY_SCHEDULER_AND_RECONCILIATION"

def self_test()->dict[str,Any]:
    cfg=load_config()
    pilot=_load(PILOT)
    pilot_names=[x["repository"] for x in pilot["pilot_targets"]]
    assert pilot_names==list(PILOT_REPOS)
    s3=stage_repositories("3"); s5=stage_repositories("5"); sall=stage_repositories("all")
    assert s3==list(PILOT_REPOS)
    assert len(s5)==5 and s5[:3]==s3
    assert len(sall)>=len(s5) and all(r in sall for r in s5)
    assert all(admission(r,"3")["admitted"] for r in s3)
    assert admission(s5[3],"3")["reason"]=="OUTSIDE_STAGE"
    global_stop=dict(cfg,global_kill_switch=True)
    assert admission(s3[0],"3",global_stop)["reason"]=="GLOBAL_KILL_SWITCH"
    repo_stop=dict(cfg,global_kill_switch=False,repository_kill_switches={s3[1]:True})
    assert admission(s3[1],"3",repo_stop)["reason"]=="REPOSITORY_KILL_SWITCH"
    assert admission(s3[0],"3",repo_stop)["admitted"] is True
    live=live_control_config(s3[0],dict(cfg,rollout_stage="3"))
    assert live["kill_switch"] is False and [x["repository"] for x in live["pilot_targets"]]==s3
    live_global=live_control_config(s3[0],dict(cfg,rollout_stage="3",global_kill_switch=True))
    assert live_global["kill_switch"] is True
    live_repo=live_control_config(s3[1],dict(cfg,rollout_stage="3",repository_kill_switches={s3[1]:True}))
    assert live_repo["kill_switch"] is True
    live5=live_control_config(s5[3],dict(cfg,rollout_stage="5"))
    assert any(x["repository"]==s5[3] for x in live5["pilot_targets"])
    assert watcher_role("3",True)=="PRIMARY_SCHEDULER_AND_RECONCILIATION"
    assert watcher_role("5",True)=="PRIMARY_SCHEDULER_AND_RECONCILIATION"
    assert watcher_role("all",False)=="PRIMARY_SCHEDULER_AND_RECONCILIATION"
    assert watcher_role("all",True)=="RECONCILIATION_WATCHDOG"
    return {"schema_version":1,"record_type":"APPLAB_V55E_CONTROLLED_EXPANSION_PROOF","status":"PASS",
      "stage_3":s3,"stage_5":s5,"all_compatible_count":len(sall),
      "global_kill_switch_proven":True,"per_repo_kill_switch_proven":True,
      "github_actions_fallback":True,"watcher_reconciliation":True,"coverage_reduction_enabled":False,
      "authority":"ORCHESTRATION_ONLY"}

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--materialize-live-config",type=Path)
    p.add_argument("--repository")
    a=p.parse_args()
    if a.self_test:
        self_test();print("AppLab v5.5E controlled expansion PASS");return 0
    if a.materialize_live_config is not None:
        if not a.repository:p.error("--repository is required with --materialize-live-config")
        payload=live_control_config(a.repository)
        a.materialize_live_config.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\\n",encoding="utf-8")
        return 0
    p.error("--self-test or --materialize-live-config is required")
if __name__=="__main__":raise SystemExit(main())
