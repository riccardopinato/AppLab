#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
DOMAINS={
 "core":["scripts/verify_apk.sh","scripts/run_external_android_gate.sh","scripts/smart_test_plan.py","scripts/adaptive_checks.py","scripts/package_build_contract.py","scripts/validate_build_contract.py"],
 "system":["scripts/system_lab.py"],"performance":["scripts/performance_lab.py"],"network":["scripts/network_lab.py"],
 "persistence":["scripts/persistence_lab.py"],"configuration":["scripts/configuration_lab.py"],
 "resource_pressure":["scripts/resource_pressure_lab.py"],"background":["scripts/background_lab.py"],
 "storage":["scripts/storage_lab.py"],"upgrade":["scripts/upgrade_lab.py"],
 "visual":["scripts/visual_qa.py","scripts/visual_policy.py","scripts/visual_regression.py","scripts/visual_journey.py","scripts/interaction_crawler.py"],
}
def digest(root:Path,files:list[str])->str:
    h=hashlib.sha256()
    for rel in files:
        p=root/rel; h.update(rel.encode()); h.update(b"\0"); h.update(p.read_bytes() if p.is_file() else b"<missing>"); h.update(b"\0")
    return h.hexdigest()[:16]
def compute(root:Path)->dict[str,str]: return {k:digest(root,v) for k,v in DOMAINS.items()}
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="."); ap.add_argument("--output",default=""); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test: assert "core" in compute(Path(a.root)); print("AppLab domain fingerprint self-test PASS"); return 0
    x=compute(Path(a.root)); text=json.dumps(x,indent=2,sort_keys=True)+"\n"; Path(a.output).write_text(text) if a.output else print(text,end=""); return 0
if __name__=="__main__": raise SystemExit(main())
