#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, urllib.error, urllib.parse, urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

import build_reuse_eligibility as reuse

def api_json(url:str,token:str="")->Any:
    headers={"Accept":"application/vnd.github+json","User-Agent":"AppLab-v5.7"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=urllib.request.Request(url,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code==404: return None
        raise

def api_text(repository:str,path:str,ref:str,token:str="")->str|None:
    q=urllib.parse.urlencode({"ref":ref})
    payload=api_json(
        f"https://api.github.com/repos/{repository}/contents/{urllib.parse.quote(path,safe='/')}?{q}",
        token,
    )
    if not isinstance(payload,dict) or not isinstance(payload.get("download_url"),str):
        return None
    req=urllib.request.Request(payload["download_url"],headers={"User-Agent":"AppLab-v5.7"})
    with urllib.request.urlopen(req,timeout=20) as response:
        return response.read().decode("utf-8",errors="replace")

def tree_paths(repository:str,ref:str,token:str="")->list[str]:
    payload=api_json(
        f"https://api.github.com/repos/{repository}/git/trees/{urllib.parse.quote(ref,safe='')}?recursive=1",
        token,
    )
    if not isinstance(payload,dict) or payload.get("truncated") is True:
        return []
    return [
        str(item.get("path"))
        for item in payload.get("tree",[])
        if isinstance(item,dict) and item.get("type")=="blob" and item.get("path")
    ]

def under_workdir(path:str,working:PurePosixPath)->bool:
    return reuse.under_workdir(path,working)

def trusted_applab_hook_safe(command:str)->bool:
    raw=command.strip()
    if not raw:
        return True
    match=reuse.TRUSTED_APPLAB_HOOK_COMMAND.fullmatch(raw)
    if not match:
        return False
    path=Path(__file__).resolve().parents[1]/"watch-profiles"/match.group(1)
    return path.is_file() and not path.is_symlink()

def evaluate(
    entry:dict[str,Any],
    *,
    has_pub_lock:bool=False,
    has_gradle_lock:bool=False,
    has_verification:bool=False,
    native_commands_safe:bool=True,
    dynamic_gradle:bool=False,
    trusted_hooks_safe:bool=True,
)->dict[str,Any]:
    engine=str(entry.get("engine","auto"))
    if engine=="flutter" or (engine=="auto" and has_pub_lock):
        has_hooks=bool(str(entry.get("prepare_command","")).strip() or str(entry.get("post_pub_get_command","")).strip())
        if not str(entry.get("flutter_version","")).strip():
            eligible=False; reason="FLOATING_FLUTTER_TOOLCHAIN"
        elif has_hooks and not trusted_hooks_safe:
            eligible=False; reason="MUTABLE_HOOK_COMMAND"
        elif not has_pub_lock:
            eligible=False; reason="MISSING_TRACKED_PUBSPEC_LOCK"
        else:
            eligible=True
            reason="LOCKED_FLUTTER_INPUTS_WITH_TRUSTED_APPLAB_HOOKS" if has_hooks else "LOCKED_FLUTTER_INPUTS"
    elif engine=="native_android":
        if str(entry.get("prepare_command","")).strip():
            eligible=False; reason="MUTABLE_HOOK_COMMAND"
        elif not native_commands_safe:
            eligible=False; reason="NON_HERMETIC_GRADLE_COMMAND"
        elif not has_gradle_lock:
            eligible=False; reason="MISSING_GRADLE_DEPENDENCY_LOCKS"
        elif not has_verification:
            eligible=False; reason="MISSING_GRADLE_VERIFICATION_METADATA"
        elif dynamic_gradle:
            eligible=False; reason="DYNAMIC_GRADLE_VERSION"
        else:
            eligible=True; reason="LOCKED_VERIFIED_GRADLE_INPUTS"
    else:
        eligible=False; reason="ENGINE_OR_BUILD_CONTRACT_NOT_READY"
    return {
      "eligible_for_shadow_reuse":eligible,
      "reason":reason,
      "production_reuse_enabled":False,
      "exact_artifact_manifest_required":True,
      "promotion_required":True
    }

def native_source_assessment(repository:str,ref:str,entry:dict[str,Any],token:str)->tuple[bool,bool,bool,bool]:
    working=reuse.safe_relative(str(entry.get("working_directory",".")))
    paths=tree_paths(repository,ref,token)
    scoped=[path for path in paths if under_workdir(path,working)]
    has_lock=any(reuse._is_gradle_lock(path) for path in scoped)
    has_verification=any(
        PurePosixPath(path).name=="verification-metadata.xml" and "gradle" in PurePosixPath(path).parts
        for path in scoped
    )
    commands_safe=(
        reuse._safe_gradle_command(str(entry.get("build_command","")),required=True)
        and reuse._safe_gradle_command(str(entry.get("test_command","")),required=False)
        and reuse._safe_gradle_command(str(entry.get("lint_command","")),required=False)
    )
    dynamic=False
    for path in scoped:
        if not reuse._is_gradle_config(path):
            continue
        text=api_text(repository,path,ref,token)
        if text is None:
            dynamic=True
            break
        if reuse.DYNAMIC_GRADLE.search(text):
            dynamic=True
            break
    return has_lock,has_verification,commands_safe,dynamic

def build_report(observatory:dict[str,Any],watchlist:dict[str,Any],token:str="")->dict[str,Any]:
    by_repo={str(x.get("repository","")):x for x in watchlist.get("repositories",[]) if isinstance(x,dict)}
    rows=[]
    for row in observatory.get("repositories",[]):
        if not isinstance(row,dict):
            continue
        repo=row["repository"]; ref=row.get("ref","main")
        entry=by_repo.get(repo)
        reuse_carrier=bool(row.get("pilot")) or bool(entry and entry.get("reuse_pilot"))
        if not reuse_carrier:
            continue
        if row.get("status")!="ADOPTED":
            rows.append({"repository":repo,"state":"WAITING_ADOPTION_MANIFEST","production_reuse_enabled":False})
            continue
        if not entry:
            rows.append({"repository":repo,"state":"NOT_WATCHLISTED","production_reuse_enabled":False})
            continue
        engine=str(entry.get("engine","auto"))
        working=reuse.safe_relative(str(entry.get("working_directory",".")))
        prefix="" if working==PurePosixPath(".") else working.as_posix().rstrip("/")+"/"
        paths=set(tree_paths(repo,ref,token))
        has_pub=(prefix+"pubspec.lock") in paths
        hooks_safe=(
            trusted_applab_hook_safe(str(entry.get("prepare_command","")))
            and trusted_applab_hook_safe(str(entry.get("post_pub_get_command","")))
        )
        if engine=="native_android":
            lock,verification,commands_safe,dynamic=native_source_assessment(repo,ref,entry,token)
            assessment=evaluate(
                entry,
                has_gradle_lock=lock,
                has_verification=verification,
                native_commands_safe=commands_safe,
                dynamic_gradle=dynamic,
            )
        else:
            assessment=evaluate(entry,has_pub_lock=has_pub,trusted_hooks_safe=hooks_safe)
        assessment.update({
          "repository":repo,
          "state":"SHADOW_READY" if assessment["eligible_for_shadow_reuse"] else "HOLD"
        })
        rows.append(assessment)
    return {
      "schema_version":1,
      "record_type":"VERIFICATION_REUSE_V57E",
      "authority":"SHADOW_ADVISORY_ONLY",
      "repositories":rows,
      "coverage_reduction_enabled":False
    }

def self_test()->None:
    flutter={"engine":"flutter","flutter_version":"3.47.5","prepare_command":"","post_pub_get_command":""}
    assert evaluate(flutter,has_pub_lock=True)["eligible_for_shadow_reuse"] is True
    trusted_command='bash "$GITHUB_WORKSPACE/.applab/watch-profiles/battery_guard.sh"'
    trusted=dict(flutter,prepare_command=trusted_command)
    assert trusted_applab_hook_safe(trusted_command) is True
    for rejected_hook in (
      "bash setup.sh",
      "bash '$GITHUB_WORKSPACE/.applab/watch-profiles/battery_guard.sh'",
      'bash "\\$GITHUB_WORKSPACE/.applab/watch-profiles/battery_guard.sh"',
    ):
      assert trusted_applab_hook_safe(rejected_hook) is False
    assert evaluate(
      trusted,
      has_pub_lock=True,
      trusted_hooks_safe=trusted_applab_hook_safe(trusted_command),
    )["eligible_for_shadow_reuse"] is True
    assert evaluate(
      dict(flutter,prepare_command="bash setup.sh"),
      has_pub_lock=True,
      trusted_hooks_safe=trusted_applab_hook_safe("bash setup.sh"),
    )["eligible_for_shadow_reuse"] is False
    native={
      "engine":"native_android","prepare_command":"",
      "build_command":"./gradlew :app:assembleDebug --stacktrace",
      "test_command":"./gradlew test","lint_command":"./gradlew lint"
    }
    assert evaluate(native,has_gradle_lock=True,has_verification=True,native_commands_safe=True,dynamic_gradle=False)["eligible_for_shadow_reuse"] is True
    assert evaluate(native,has_gradle_lock=True,has_verification=True,native_commands_safe=False,dynamic_gradle=False)["eligible_for_shadow_reuse"] is False
    assert evaluate(native,has_gradle_lock=True,has_verification=True,native_commands_safe=True,dynamic_gradle=True)["reason"]=="DYNAMIC_GRADLE_VERSION"
    print("AppLab v5.7E verification reuse self-test PASS")

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--observatory",default="")
    p.add_argument("--watchlist",default="watchlist.json")
    p.add_argument("--output",default="")
    p.add_argument("--token",default=os.environ.get("GITHUB_TOKEN",""))
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        self_test(); return 0
    obs=json.loads(Path(a.observatory).read_text(encoding="utf-8"))
    watch=json.loads(Path(a.watchlist).read_text(encoding="utf-8"))
    report=build_report(obs,watch,a.token)
    if a.output:
        Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
