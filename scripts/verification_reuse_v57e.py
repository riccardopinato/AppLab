#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, json, os, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

def api_exists(repository:str,path:str,ref:str,token:str="")->bool:
    headers={"Accept":"application/vnd.github+json","User-Agent":"AppLab-v5.7"}
    if token: headers["Authorization"]=f"Bearer {token}"
    q=urllib.parse.urlencode({"ref":ref})
    req=urllib.request.Request(f"https://api.github.com/repos/{repository}/contents/{urllib.parse.quote(path,safe='/')}?{q}",headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=20): return True
    except urllib.error.HTTPError as exc:
        if exc.code==404: return False
        raise

def evaluate(entry:dict[str,Any],has_pub_lock:bool=False,has_gradle_lock:bool=False,has_verification:bool=False)->dict[str,Any]:
    engine=str(entry.get("engine","auto"))
    if engine=="flutter" or (engine=="auto" and has_pub_lock):
        eligible=bool(str(entry.get("flutter_version","")).strip()) and not str(entry.get("prepare_command","")).strip() and not str(entry.get("post_pub_get_command","")).strip() and has_pub_lock
        reason="LOCKED_FLUTTER_INPUTS" if eligible else "FLUTTER_INPUTS_NOT_HERMETIC"
    elif engine=="native_android":
        eligible=has_gradle_lock and has_verification and not str(entry.get("prepare_command","")).strip()
        reason="LOCKED_VERIFIED_GRADLE_INPUTS" if eligible else "NATIVE_INPUTS_NOT_HERMETIC"
    else:
        eligible=False; reason="ENGINE_OR_BUILD_CONTRACT_NOT_READY"
    return {"eligible_for_shadow_reuse":eligible,"reason":reason,"production_reuse_enabled":False,"exact_artifact_manifest_required":True,"promotion_required":True}

def build_report(observatory:dict[str,Any],watchlist:dict[str,Any],token:str="")->dict[str,Any]:
    by_repo={str(x.get("repository","")):x for x in watchlist.get("repositories",[]) if isinstance(x,dict)}
    rows=[]
    for row in observatory.get("repositories",[]):
        if not isinstance(row,dict) or not row.get("pilot"): continue
        repo=row["repository"]; ref=row.get("ref","main")
        if row.get("status")!="ADOPTED":
            rows.append({"repository":repo,"state":"WAITING_ADOPTION_MANIFEST","production_reuse_enabled":False}); continue
        entry=by_repo.get(repo)
        if not entry:
            rows.append({"repository":repo,"state":"NOT_WATCHLISTED","production_reuse_enabled":False}); continue
        wd=str(entry.get("working_directory",".")).strip().strip("/")
        prefix="" if wd in ("",".") else wd+"/"
        pub=api_exists(repo,prefix+"pubspec.lock",ref,token)
        gradle=api_exists(repo,prefix+"gradle.lockfile",ref,token)
        verification=api_exists(repo,prefix+"gradle/verification-metadata.xml",ref,token)
        assessment=evaluate(entry,pub,gradle,verification)
        assessment.update({"repository":repo,"state":"SHADOW_READY" if assessment["eligible_for_shadow_reuse"] else "HOLD"})
        rows.append(assessment)
    return {"schema_version":1,"record_type":"VERIFICATION_REUSE_V57E","authority":"SHADOW_ADVISORY_ONLY","repositories":rows,"coverage_reduction_enabled":False}

def self_test()->None:
    flutter={"engine":"flutter","flutter_version":"3.47.5","prepare_command":"","post_pub_get_command":""}
    assert evaluate(flutter,has_pub_lock=True)["eligible_for_shadow_reuse"] is True
    assert evaluate(dict(flutter,prepare_command="bash setup.sh"),has_pub_lock=True)["eligible_for_shadow_reuse"] is False
    native={"engine":"native_android","prepare_command":""}
    assert evaluate(native,has_gradle_lock=True,has_verification=True)["eligible_for_shadow_reuse"] is True
    print("AppLab v5.7E verification reuse self-test PASS")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--observatory",default=""); p.add_argument("--watchlist",default="watchlist.json"); p.add_argument("--output",default=""); p.add_argument("--token",default=os.environ.get("GITHUB_TOKEN","")); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test: self_test(); return 0
    obs=json.loads(Path(a.observatory).read_text(encoding="utf-8")); watch=json.loads(Path(a.watchlist).read_text(encoding="utf-8"))
    report=build_report(obs,watch,a.token)
    if a.output: Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
