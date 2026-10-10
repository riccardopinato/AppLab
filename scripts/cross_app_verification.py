#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, tempfile
from pathlib import Path
from typing import Any
from ecosystem_core_contract import CANONICAL_APP_SCHEMES, clean, validate_envelope, validate_protocol

APPLAB_VERSION="4.8.0"; SCHEMA_VERSION=1
AUTHORITY="APPLAB_CROSS_APP_VERIFICATION"; RECORD_TYPE="CROSS_APP_VERIFICATION"
WORKFLOW_PATH=".github/workflows/cross-app-verification.yml"
PASS="PASS"; FAIL="FAIL"; BLOCKED="BLOCKED"; NOT_VERIFIED="NOT_VERIFIED"
STATES={PASS,FAIL,BLOCKED,NOT_VERIFIED}
SHA40_RE=re.compile(r"^[0-9a-f]{40}$"); SHA256_RE=re.compile(r"^[0-9a-f]{64}$")
REPO_RE=re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PACKAGE_RE=re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
REQUIRED_KINDS={"COPY","LINK","IDEMPOTENCY","PROVENANCE","OWNERSHIP","FAIL_CLOSED"}
TRANSPORT_KINDS={"DEEP_LINK_HANDOFF","FALLBACK_TRANSPORT"}
SUPPORTED_TRANSPORTS={"deep_link","android_intent","clipboard","fallback"}
INSTALLED_APP_TRANSPORTS=set(SUPPORTED_TRANSPORTS)
ASSERTIONS={
"COPY":{"explicit_review","materialized_once","provenance_preserved","source_ownership_preserved"},
"LINK":{"explicit_review","canonical_deep_link_present","source_ownership_preserved","no_background_sync"},
"IDEMPOTENCY":{"duplicate_noop","stable_bridge_id","mode_specific_key"},
"PROVENANCE":{"owner_app_preserved","owner_entity_preserved","owner_revision_preserved"},
"OWNERSHIP":{"no_shared_db","no_cross_app_mutation","destination_materialization_owned"},
"FAIL_CLOSED":{"incompatible_version_rejected","no_domain_mutation","private_media_rejected"},
"DEEP_LINK_HANDOFF":{"target_scheme_matches","target_app_matches","payload_validated"},
"FALLBACK_TRANSPORT":{"same_payload_contract","explicit_fallback","no_semantic_fork"},
}

def canonical_bytes(v:Any)->bytes: return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def digest(v:Any)->str: return hashlib.sha256(canonical_bytes(v)).hexdigest()
def load_json(path:Path)->dict[str,Any]:
    try: v=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise ValueError(f"Unable to read JSON object: {path}") from exc
    if not isinstance(v,dict): raise ValueError(f"Expected JSON object: {path}")
    return v

def state(v:object,label:str)->str:
    out=clean(v,label,32).upper()
    if out not in STATES: raise ValueError(f"{label} must be one of {sorted(STATES)}")
    return out

def identity(raw:Any,role:str)->dict[str,str]:
    if not isinstance(raw,dict): raise ValueError(f"{role} identity must be an object")
    repo=clean(raw.get("repository"),f"{role}.repository",200)
    sha=clean(raw.get("resolved_sha"),f"{role}.resolved_sha",40).lower()
    apk=clean(raw.get("artifact_sha256"),f"{role}.artifact_sha256",64).lower()
    pkg=clean(raw.get("package_id"),f"{role}.package_id",250)
    if not REPO_RE.fullmatch(repo): raise ValueError(f"{role}.repository must use owner/name format")
    if not SHA40_RE.fullmatch(sha): raise ValueError(f"{role}.resolved_sha must be 40 lowercase hex")
    if not SHA256_RE.fullmatch(apk): raise ValueError(f"{role}.artifact_sha256 must be 64 lowercase hex")
    if not PACKAGE_RE.fullmatch(pkg): raise ValueError(f"{role}.package_id is invalid")
    return {"repository":repo,"resolved_sha":sha,"artifact_sha256":apk,"package_id":pkg,
            "version_name":clean(raw.get("version_name"),f"{role}.version_name",128),
            "version_code":clean(raw.get("version_code"),f"{role}.version_code",64),
            "app_id":clean(raw.get("app_id"),f"{role}.app_id",64)}

def evidence(values:Any)->list[dict[str,str]]:
    if values is None: return []
    if not isinstance(values,list) or len(values)>64: raise ValueError("evidence_refs must be an array with <=64 items")
    out=[]
    for i,x in enumerate(values):
        if not isinstance(x,dict): raise ValueError(f"evidence_refs[{i}] must be an object")
        sha=clean(x.get("sha256"),f"evidence_refs[{i}].sha256",64).lower()
        if not SHA256_RE.fullmatch(sha): raise ValueError(f"evidence_refs[{i}].sha256 must be 64 lowercase hex")
        out.append({"kind":clean(x.get("kind"),f"evidence_refs[{i}].kind",32).lower(),"uri":clean(x.get("uri"),f"evidence_refs[{i}].uri",2000),"sha256":sha})
    return out

def scenario(raw:Any,p:dict[str,str],c:dict[str,str])->dict[str,Any]:
    if not isinstance(raw,dict): raise ValueError("scenario must be an object")
    kind=clean(raw.get("kind"),"scenario.kind",64).upper()
    if kind not in ASSERTIONS: raise ValueError(f"Unsupported cross-app scenario kind: {kind}")
    result=state(raw.get("result"),f"{kind}.result")
    direction=clean(raw.get("direction"),f"{kind}.direction",32).lower()
    if direction not in {"producer_to_consumer","consumer_to_producer"}: raise ValueError(f"Unsupported {kind}.direction")
    a=raw.get("assertions")
    if not isinstance(a,dict) or set(a)!=ASSERTIONS[kind] or not all(isinstance(v,bool) for v in a.values()):
        raise ValueError(f"{kind}.assertions must exactly contain {sorted(ASSERTIONS[kind])} booleans")
    if result==PASS and not all(a.values()): raise ValueError(f"{kind} cannot PASS with false required assertions")
    if result==FAIL and all(a.values()): raise ValueError(f"{kind} FAIL must expose a false assertion")
    source,target=(p,c) if direction=="producer_to_consumer" else (c,p)
    observed=None
    if raw.get("observed_contract") is not None:
        expected="copy" if kind=="COPY" else "link" if kind=="LINK" else None
        observed=validate_envelope(raw["observed_contract"],source_app=source["app_id"],target_app=target["app_id"],expected_mode=expected)
    elif kind in {"COPY","LINK","IDEMPOTENCY","PROVENANCE","OWNERSHIP"}: raise ValueError(f"{kind} requires observed_contract evidence")
    return {"id":clean(raw.get("id"),f"{kind}.id",128),"kind":kind,"direction":direction,
            "transport":clean(raw.get("transport"),f"{kind}.transport",64).lower(),"result":result,
            "assertions":dict(sorted(a.items())),"observed_contract":observed,"evidence_refs":evidence(raw.get("evidence_refs",[]))}

def physical(raw:Any,required:bool,p:dict[str,str],c:dict[str,str],rows:list[dict[str,Any]])->dict[str,Any]:
    if raw is None: return {"required":required,"state":BLOCKED if required else NOT_VERIFIED,"reason":"paired physical-device evidence missing" if required else "not required"}
    if not isinstance(raw,dict) or raw.get("physical") is not True: raise ValueError("physical_evidence must identify a physical device")
    result=state(raw.get("result"),"physical_evidence.result")
    if clean(raw.get("producer_artifact_sha256"),"physical producer sha",64).lower()!=p["artifact_sha256"] or clean(raw.get("consumer_artifact_sha256"),"physical consumer sha",64).lower()!=c["artifact_sha256"]: raise ValueError("paired physical evidence artifact identity mismatch")
    ids=raw.get("scenario_ids")
    if not isinstance(ids,list): raise ValueError("physical_evidence.scenario_ids must be an array")
    covered={clean(x,"physical scenario id",128) for x in ids}; needed={r["id"] for r in rows if r["transport"] in {"deep_link","android_intent","clipboard","fallback"}}
    reason=clean(raw.get("observed_result"),"physical_evidence.observed_result",4000)
    refs=evidence(raw.get("evidence_refs",[])); missing_coverage=required and not needed.issubset(covered); missing_refs=required and not refs
    problems=[]
    if missing_coverage: problems.append("paired physical evidence does not cover all installed-app transport scenarios")
    if missing_refs: problems.append("paired physical evidence requires at least one hashed evidence reference")
    if problems:
        reason=reason+"; "+"; ".join(problems)
        if result!=FAIL: result=BLOCKED
    return {"required":required,"state":result,"device":{"manufacturer":clean(raw.get("device_manufacturer"),"device manufacturer",128),"model":clean(raw.get("device_model"),"device model",128),"os_version":clean(raw.get("os_version"),"os version",128),"os_build":clean(raw.get("os_build"),"os build",256)},"scenario_ids":sorted(covered),"evidence_refs":refs,"reason":reason}

def reality(raw:Any,i:dict[str,str])->dict[str,Any]:
    if raw is None: return {"provided":False,"status":NOT_VERIFIED,"current_level":"UNKNOWN","identity_match":False}
    if not isinstance(raw,dict): raise ValueError("release reality must be an object")
    s=raw.get("source") if isinstance(raw.get("source"),dict) else {}; a=raw.get("artifact") if isinstance(raw.get("artifact"),dict) else {}
    checks={"repository":(str(s.get("repository","")).strip(),i["repository"]),"resolved_sha":(str(s.get("resolved_sha","")).strip().lower(),i["resolved_sha"]),"artifact_sha256":(str(a.get("actual_sha256") or a.get("sha256") or "").strip().lower(),i["artifact_sha256"]),"package_id":(str(a.get("package_id","")).strip(),i["package_id"]),"version_name":(str(a.get("version_name","")).strip(),i["version_name"]),"version_code":(str(a.get("version_code","")).strip(),i["version_code"])}
    mismatch=[k for k,(got,want) in checks.items() if got!=want]
    cert=raw.get("certification"); status=str(cert.get("status",NOT_VERIFIED) if isinstance(cert,dict) else raw.get("certification_status",NOT_VERIFIED)).upper()
    return {"provided":True,"status":status,"current_level":str(raw.get("current_level","UNKNOWN")),"identity_match":not mismatch,"identity_mismatches":mismatch}

def attestation(args:argparse.Namespace)->dict[str,Any]|None:
    if not args.workflow_run_id: return None
    repo=clean(args.workflow_repository,"workflow_repository",200); sha=clean(args.trusted_applab_sha,"trusted_applab_sha",40).lower(); run=clean(args.workflow_run_id,"workflow_run_id",32); attempt=clean(args.workflow_run_attempt,"workflow_run_attempt",16)
    if not REPO_RE.fullmatch(repo) or not SHA40_RE.fullmatch(sha) or not run.isdigit() or not attempt.isdigit(): raise ValueError("invalid workflow attestation identity")
    return {"authority":AUTHORITY,"workflow_repository":repo,"workflow_path":WORKFLOW_PATH,"workflow_run_id":run,"workflow_run_attempt":attempt,"trusted_applab_sha":sha,"actor":clean(args.actor,"actor",128),"event":"workflow_dispatch","operator_attested_pair_evidence":True,"artifact_bytes_reverified_by_cross_app_hub":False}

def build_report(session:dict[str,Any],producer_release_reality:dict[str,Any]|None=None,consumer_release_reality:dict[str,Any]|None=None,attestation_record:dict[str,Any]|None=None)->dict[str,Any]:
    session_version=session.get("schema_version",1)
    if not isinstance(session_version,int) or isinstance(session_version,bool) or session_version!=1: raise ValueError("session.schema_version must be integer 1")
    protocol=validate_protocol(session.get("protocol")); p=identity(session.get("producer"),"producer"); c=identity(session.get("consumer"),"consumer")
    if (p["repository"],p["resolved_sha"])==(c["repository"],c["resolved_sha"]): raise ValueError("producer and consumer must be distinct app identities")
    if p["artifact_sha256"]==c["artifact_sha256"]: raise ValueError("producer and consumer cannot use identical APK bytes")
    if p["app_id"] not in CANONICAL_APP_SCHEMES or c["app_id"] not in CANONICAL_APP_SCHEMES or p["app_id"]==c["app_id"]: raise ValueError("producer/consumer app ids must be distinct registered Shared Ecosystem Core v1 ids")
    t=session.get("transport")
    if not isinstance(t,dict): raise ValueError("transport must be an object")
    kind=clean(t.get("kind"),"transport.kind",64).lower()
    if kind not in SUPPORTED_TRANSPORTS: raise ValueError(f"unsupported cross-app transport: {kind}")
    installed=kind in INSTALLED_APP_TRANSPORTS; declared=t.get("requires_installed_apps")
    if not isinstance(declared,bool) or declared is not installed: raise ValueError("transport.requires_installed_apps must match the validated transport requirement")
    if t.get("protocol_transport_separated") is not True: raise ValueError("transport must preserve protocol/transport separation")
    raw=session.get("scenarios")
    if not isinstance(raw,list) or not raw: raise ValueError("scenarios must be non-empty")
    rows=[scenario(x,p,c) for x in raw]; ids=[r["id"] for r in rows]
    if len(ids)!=len(set(ids)): raise ValueError("scenario ids must be unique")
    kinds={r["kind"] for r in rows}; errors=[]
    semantic=[r for r in rows if r["kind"] in {"COPY","LINK","IDEMPOTENCY","PROVENANCE","OWNERSHIP"}]
    lineage={(r["direction"],r["observed_contract"]["bridge_id"],r["observed_contract"]["revision"],r["observed_contract"]["owner_app"],r["observed_contract"]["owner_entity_type"],r["observed_contract"]["owner_entity_id"],r["observed_contract"]["target_app"]) for r in semantic}
    if len(lineage)>1: errors.append("semantic contract lineage mismatch across COPY/LINK/idempotency/provenance/ownership")
    missing=sorted(REQUIRED_KINDS-kinds)
    if missing: errors.append("missing required scenarios: "+", ".join(missing))
    if not kinds & TRANSPORT_KINDS: errors.append("missing explicit transport scenario")
    if kind=="deep_link" and "DEEP_LINK_HANDOFF" not in kinds: errors.append("deep_link transport requires DEEP_LINK_HANDOFF scenario")
    if kind in {"clipboard","fallback"} and "FALLBACK_TRANSPORT" not in kinds: errors.append("fallback transport requires FALLBACK_TRANSPORT scenario")
    ph=physical(session.get("physical_evidence"),installed,p,c,rows); pr=reality(producer_release_reality,p); cr=reality(consumer_release_reality,c)
    if pr["provided"] and not pr["identity_match"]: errors.append("producer Release Reality identity mismatch")
    if cr["provided"] and not cr["identity_match"]: errors.append("consumer Release Reality identity mismatch")
    states=[r["result"] for r in rows]
    if FAIL in states or ph.get("state")==FAIL: overall=FAIL
    elif errors or BLOCKED in states or ph.get("state")==BLOCKED: overall=BLOCKED
    elif NOT_VERIFIED in states: overall=NOT_VERIFIED
    elif installed and ph.get("state")!=PASS: overall=BLOCKED
    else: overall=PASS
    pair={"producer":p,"consumer":c}; pair["pair_sha256"]=digest({"producer":p,"consumer":c,"protocol":{"name":protocol["name"],"version":protocol["version"]}})
    blockers=errors+[f"{r['id']}: {r['result']}" for r in rows if r["result"]!=PASS]
    if ph.get("state") not in {PASS,NOT_VERIFIED if not ph.get("required") else ""}: blockers.append(f"paired physical evidence: {ph.get('state')}")
    report={"schema_version":SCHEMA_VERSION,"applab_version":APPLAB_VERSION,"record_type":RECORD_TYPE,"authority":AUTHORITY,"protocol":protocol,"pair_identity":pair,"transport":{"kind":kind,"requires_installed_apps":installed,"protocol_transport_separated":True},"single_app_release_reality":{"producer":pr,"consumer":cr,"note":"Single-app certification is identity-bound context only and cannot promote cross-app round-trip state."},"scenarios":rows,"scenario_coverage":{"required_kinds":sorted(REQUIRED_KINDS),"transport_kinds":sorted(TRANSPORT_KINDS),"observed_kinds":sorted(kinds),"errors":errors},"physical_evidence":ph,"cross_app_round_trip":{"state":overall,"pass":overall==PASS,"independent_from_single_app_pass":True,"blockers":blockers},"guardrails":{"no_parallel_cross_app_protocol":True,"shared_ecosystem_core_is_canonical":True,"transport_does_not_redefine_protocol":True,"single_app_pass_is_not_cross_app_pass":True,"missing_pair_evidence_never_becomes_pass":True,"physical_evidence_required_when_transport_depends_on_installed_apps":True}}
    if attestation_record: report["attestation"]=attestation_record
    report["record_digest_sha256"]=digest(report); return report

def markdown(r:dict[str,Any])->str:
    p=r["pair_identity"]; rt=r["cross_app_round_trip"]; ph=r["physical_evidence"]
    lines=["# AppLab v4.8 — Cross-App Verification","",f"- Round-trip state: **{rt['state']}**",f"- Protocol: **{r['protocol']['name']} v{r['protocol']['version']}**",f"- Transport: **{r['transport']['kind']}**",f"- Pair SHA-256: `{p['pair_sha256']}`","","## Producer","",f"- Repository: `{p['producer']['repository']}`",f"- Source SHA: `{p['producer']['resolved_sha']}`",f"- APK SHA-256: `{p['producer']['artifact_sha256']}`","","## Consumer","",f"- Repository: `{p['consumer']['repository']}`",f"- Source SHA: `{p['consumer']['resolved_sha']}`",f"- APK SHA-256: `{p['consumer']['artifact_sha256']}`","","## Scenario matrix",""]
    lines += [f"- **{x['kind']}** · `{x['id']}` · {x['direction']} · **{x['result']}**" for x in r["scenarios"]]
    lines += ["","## Paired physical evidence","",f"- Required: **{'YES' if ph.get('required') else 'NO'}**",f"- State: **{ph.get('state')}**",f"- Detail: {ph.get('reason','')}","","## Authority boundary","","- Single-app Release Reality/certification remains separate from cross-app round-trip verification.","- Two individually green apps do not imply a green pair.","- Shared Ecosystem Core v1 remains canonical; transport cannot redefine ownership, COPY/LINK, revision, provenance or idempotency.","","## Blockers",""]
    lines += [f"- {x}" for x in (rt.get("blockers") or ["None."])]; return "\n".join(lines)+"\n"

def write_outputs(report:dict[str,Any],out:Path)->None:
    out.mkdir(parents=True,exist_ok=True); (out/"cross-app-verification.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8"); (out/"cross-app-verification.md").write_text(markdown(report),encoding="utf-8")

def self_test()->None:
    p={"repository":"owner/wonderlog","resolved_sha":"a"*40,"artifact_sha256":"1"*64,"package_id":"dev.example.wonderlog","version_name":"1.0","version_code":"1","app_id":"wonderlog"}; c={"repository":"owner/anna","resolved_sha":"b"*40,"artifact_sha256":"2"*64,"package_id":"dev.example.anna","version_name":"1.0","version_code":"1","app_id":"annas_diary"}
    def env(mode:str)->dict[str,Any]:
        bridge="ecosystem:v1:wonderlog:journey:j42"; return {"schemaVersion":1,"bridgeId":bridge,"sourceApp":"wonderlog","privacyScope":"explicitShare","transferMode":mode,"revision":7,"idempotencyKey":f"{bridge}:7:{mode}","sourceDeepLink":"wonderlog://journey/j42","provenance":{"ownerApp":"wonderlog","ownerEntityType":"journey","ownerEntityId":"j42","ownerRevision":7,"canonicalDeepLink":"wonderlog://journey/j42"},"transport":{"transportVersion":1,"targetApp":"annas_diary"},"media":[{"handoff":{"kind":"omitted"}}]}
    def sc(k:str,contract:dict[str,Any]|None=None,result:str=PASS)->dict[str,Any]: return {"id":k.lower(),"kind":k,"direction":"producer_to_consumer","transport":"deep_link","result":result,"assertions":{x:True for x in ASSERTIONS[k]},**({"observed_contract":contract} if contract else {}),"evidence_refs":[]}
    rows=[sc("COPY",env("copy")),sc("LINK",env("link")),sc("IDEMPOTENCY",env("copy")),sc("PROVENANCE",env("copy")),sc("OWNERSHIP",env("copy")),sc("FAIL_CLOSED"),sc("DEEP_LINK_HANDOFF")]
    session={"schema_version":1,"protocol":{"name":"Shared Ecosystem Core","version":1,"contract_ref":"App-Factory-Core@golden/ecosystem/GOLDEN_ECOSYSTEM_BRIDGE_FLUTTER_v1_DRAFT.txt"},"producer":p,"consumer":c,"transport":{"kind":"deep_link","requires_installed_apps":True,"protocol_transport_separated":True},"scenarios":rows,"physical_evidence":{"physical":True,"result":PASS,"producer_artifact_sha256":p["artifact_sha256"],"consumer_artifact_sha256":c["artifact_sha256"],"device_manufacturer":"Test","device_model":"Device","os_version":"13","os_build":"test/build","scenario_ids":[x["id"] for x in rows],"observed_result":"Round trip observed on exact pair","evidence_refs":[{"kind":"screenshot","uri":"artifact://pair-round-trip.png","sha256":"3"*64}]}}
    assert build_report(session)["cross_app_round_trip"]["state"]==PASS

    no_ph=json.loads(json.dumps(session)); no_ph.pop("physical_evidence")
    assert build_report(no_ph)["cross_app_round_trip"]["state"]==BLOCKED

    no_refs=json.loads(json.dumps(session)); no_refs["physical_evidence"]["evidence_refs"]=[]
    assert build_report(no_refs)["cross_app_round_trip"]["state"]==BLOCKED

    bad=json.loads(json.dumps(session)); bad["scenarios"][2]["assertions"]["duplicate_noop"]=False; bad["scenarios"][2]["result"]=FAIL
    assert build_report(bad)["cross_app_round_trip"]["state"]==FAIL

    physical_fail=json.loads(json.dumps(session)); physical_fail["physical_evidence"]["result"]=FAIL; physical_fail["physical_evidence"]["scenario_ids"]=["copy"]
    assert build_report(physical_fail)["cross_app_round_trip"]["state"]==FAIL

    lineage=json.loads(json.dumps(session))
    observed=lineage["scenarios"][3]["observed_contract"]
    observed["bridgeId"]="ecosystem:v1:wonderlog:journey:other"
    observed["idempotencyKey"]="ecosystem:v1:wonderlog:journey:other:7:copy"
    observed["sourceDeepLink"]="wonderlog://journey/other"
    observed["provenance"]["ownerEntityId"]="other"
    observed["provenance"]["canonicalDeepLink"]="wonderlog://journey/other"
    lineage_report=build_report(lineage)
    assert lineage_report["cross_app_round_trip"]["state"]==BLOCKED
    assert any("lineage mismatch" in x for x in lineage_report["cross_app_round_trip"]["blockers"])

    same_apk=json.loads(json.dumps(session)); same_apk["consumer"]["artifact_sha256"]=same_apk["producer"]["artifact_sha256"]; same_apk["physical_evidence"]["consumer_artifact_sha256"]=same_apk["producer"]["artifact_sha256"]
    try:
        build_report(same_apk)
    except ValueError as exc:
        assert "identical APK bytes" in str(exc)
    else:
        raise AssertionError("identical producer/consumer APK bytes must fail closed")

    unsupported=json.loads(json.dumps(session)); unsupported["transport"]["kind"]="telepathy"; unsupported["transport"]["requires_installed_apps"]=False
    try:
        build_report(unsupported)
    except ValueError as exc:
        assert "unsupported cross-app transport" in str(exc)
    else:
        raise AssertionError("unsupported transport must fail closed")

    bad_schema=json.loads(json.dumps(session)); bad_schema["schema_version"]=True
    try:
        build_report(bad_schema)
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("boolean session schema version must fail closed")

    def rr(i:dict[str,str])->dict[str,Any]: return {"source":{"repository":i["repository"],"resolved_sha":i["resolved_sha"]},"artifact":{"actual_sha256":i["artifact_sha256"],"package_id":i["package_id"],"version_name":i["version_name"],"version_code":i["version_code"]},"current_level":"CERTIFIED","certification":{"status":"CERTIFIED"}}
    blocked=build_report(no_ph,rr(p),rr(c)); assert blocked["single_app_release_reality"]["producer"]["status"]=="CERTIFIED" and blocked["cross_app_round_trip"]["state"]==BLOCKED

    with tempfile.TemporaryDirectory() as d:
        write_outputs(build_report(session),Path(d))
        assert (Path(d)/"cross-app-verification.json").is_file()
    print("AppLab Cross-App Verification v4.8 self-test PASS")

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--session"); ap.add_argument("--producer-release-reality"); ap.add_argument("--consumer-release-reality"); ap.add_argument("--output-dir",default="applab-cross-app-verification"); ap.add_argument("--self-test",action="store_true"); ap.add_argument("--workflow-repository",default=""); ap.add_argument("--workflow-run-id",default=""); ap.add_argument("--workflow-run-attempt",default=""); ap.add_argument("--trusted-applab-sha",default=""); ap.add_argument("--actor",default=""); args=ap.parse_args()
    if args.self_test: self_test(); return 0
    if not args.session: ap.error("--session is required unless --self-test is used")
    r=build_report(load_json(Path(args.session)),load_json(Path(args.producer_release_reality)) if args.producer_release_reality else None,load_json(Path(args.consumer_release_reality)) if args.consumer_release_reality else None,attestation(args)); write_outputs(r,Path(args.output_dir)); print(json.dumps({"applab_version":APPLAB_VERSION,"state":r["cross_app_round_trip"]["state"],"pair_sha256":r["pair_identity"]["pair_sha256"]},sort_keys=True)); return 0 if r["cross_app_round_trip"]["state"]==PASS else 1
if __name__=="__main__":
    try: raise SystemExit(main())
    except (ValueError,OSError,AssertionError) as exc: raise SystemExit(f"AppLab Cross-App Verification failed: {exc}") from exc
