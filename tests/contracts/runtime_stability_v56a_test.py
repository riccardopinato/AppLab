#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"scripts"))
import runtime_stability_v56a as mod

def main() -> int:
    mod.self_test()
    assert mod.retry_allowed({"result":"FAIL","failure_intelligence":{"kind":"UNKNOWN_FAILURE","retryable":True}}) is False
    assert mod.retry_allowed({"result":"FAIL","failure_intelligence":{"kind":"INFRA_ERROR","retryable":True}}) is True
    print("v5.6A runtime stability contract PASS")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
