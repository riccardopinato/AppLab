#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from typing import Any

PRODUCERS={
 "SCRCPY_CAPTURE":{"wave":"PHYSICAL_CAPTURE","artifact_role":"PHYSICAL_CAPTURE","physical":True},
 "LEAKCANARY":{"wave":"DIAGNOSTIC_PILOT","artifact_role":"DEBUG_INSTRUMENTED","physical":False},
 "SEMGREP":{"wave":"FIRST_WAVE_SECURITY","artifact_role":"SOURCE_SECURITY","physical":False},
 "TRIVY":{"wave":"FIRST_WAVE_SECURITY","artifact_role":"DEPENDENCY_SECURITY","physical":False},
 "MOBSF":{"wave":"SECOND_WAVE_MOBILE","artifact_role":"MOBILE_SECURITY_ANALYSIS","physical":False},
}
SHA_RE=re.compile(r"^[0-9a-f]{40}$")
HASH_RE=re.compile(r"^[0-9a-f]{64}$")

def normalize(data:dict[str,Any])->dict[str,Any]:
    producer=str(data.get("producer","")).upper()
    if producer not in PRODUCERS: raise ValueError("unsupported pilot producer")
    repository=str(data.get("repository","")).strip()
    source_sha=str(data.get("source_sha","")).lower()
    if "/" not in repository or not SHA_RE.fullmatch(source_sha): raise ValueError("invalid repository/source identity")
    artifact_sha=str(data.get("artifact_sha256","")).lower()
    if artifact_sha and not HASH_RE.fullmatch(artifact_sha): raise ValueError("invalid artifact hash")
    if producer in {"SCRCPY_CAPTURE","LEAKCANARY"} and not HASH_RE.fullmatch(artifact_sha):
        raise ValueError("artifact-bound pilot requires exact artifact hash")
    rule=PRODUCERS[producer]
    if producer=="LEAKCANARY" and str(data.get("artifact_role","")).upper() in {"RELEASE","PRODUCTION_RELEASE"}:
        raise ValueError("diagnostic artifact cannot claim release identity")
    if rule["physical"] and data.get("physical_device") is not True:
        raise ValueError("physical capture requires explicit physical device")
    refs=data.get("evidence_refs")
    if not isinstance(refs,list) or not refs: raise ValueError("evidence refs required")
    return {
      "schema_version":1,"record_type":"ADVANCED_HARDENING_PILOT_EVIDENCE",
      "authority":"EVIDENCE_ONLY","producer":producer,"wave":rule["wave"],
      "artifact_role":rule["artifact_role"],"repository":repository,"source_sha":source_sha,
      "artifact_sha256":artifact_sha,"physical_device":bool(data.get("physical_device",False)),
      "evidence_refs":[str(x) for x in refs],
      "can_mint_pass":False,"can_mint_certified":False,
      "can_replace_trusted_runtime":False,"can_claim_store_distribution":False
    }

def self_test():
    sem=normalize({"producer":"SEMGREP","repository":"owner/app","source_sha":"a"*40,"evidence_refs":["report://1"]})
    assert sem["authority"]=="EVIDENCE_ONLY" and sem["can_mint_pass"] is False
    phy=normalize({"producer":"SCRCPY_CAPTURE","repository":"owner/app","source_sha":"b"*40,"artifact_sha256":"1"*64,"physical_device":True,"evidence_refs":["video://1"]})
    assert phy["physical_device"] is True and phy["can_claim_store_distribution"] is False
    try: normalize({"producer":"LEAKCANARY","repository":"owner/app","source_sha":"c"*40,"artifact_role":"RELEASE","artifact_sha256":"2"*64,"evidence_refs":["report://2"]})
    except ValueError: pass
    else: raise AssertionError("LeakCanary release identity must fail closed")
    try: normalize({"producer":"SCRCPY_CAPTURE","repository":"owner/app","source_sha":"d"*40,"physical_device":True,"evidence_refs":["video://2"]})
    except ValueError: pass
    else: raise AssertionError("physical capture without artifact hash must fail closed")
    try: normalize({"producer":"LEAKCANARY","repository":"owner/app","source_sha":"e"*40,"evidence_refs":["report://3"]})
    except ValueError: pass
    else: raise AssertionError("LeakCanary without debug artifact hash must fail closed")
    print("AppLab v5.6E advanced hardening pilot self-test PASS")

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--input",default=""); p.add_argument("--output",default=""); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.input: raise SystemExit("--input is required")
    out=normalize(json.loads(Path(a.input).read_text(encoding="utf-8")))
    if a.output: Path(a.output).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(out,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
