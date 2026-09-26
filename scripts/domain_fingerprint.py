#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

VERSION = "0.9.0"
CORE = (
    "scripts/verify_apk.sh",
    "scripts/impact_engine.py",
    "scripts/smart_test_plan.py",
    "scripts/targeted_execution.py",
    "scripts/validate_build_contract.py",
    "scripts/package_build_contract.py",
    ".github/workflows/trusted-apk-verifier.yml",
)
DOMAINS = {
    "system": ("scripts/system_lab.py",),
    "performance": ("scripts/performance_lab.py", "scripts/prepare_performance_baseline.py"),
    "network": ("scripts/network_lab.py",),
    "persistence": ("scripts/persistence_lab.py",),
    "configuration": ("scripts/configuration_lab.py",),
    "resource_pressure": ("scripts/resource_pressure_lab.py",),
    "background": ("scripts/background_lab.py",),
    "storage": ("scripts/storage_lab.py",),
    "upgrade": ("scripts/upgrade_lab.py", "scripts/prepare_upgrade_baseline.py"),
    "visual": (
        "scripts/visual_qa.py", "scripts/visual_policy.py", "scripts/visual_regression.py",
        "scripts/visual_journey.py", "scripts/visual_journey_runtime.py",
        "scripts/interaction_crawler.py",
    ),
}

def digest_files(root: Path, files: list[str], label: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"AppLab {VERSION} {label}\0".encode())
    for relative in files:
        path = root / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()[:16]

def compute(root: Path) -> dict[str, str]:
    payload = {"core": digest_files(root, list(CORE), "core")}
    for domain, files in DOMAINS.items():
        payload[domain] = digest_files(root, [*CORE, *files], domain)
    return payload

def selected_fingerprint(root: Path, plan: dict) -> str:
    fingerprints = compute(root)
    selected = plan.get("selected_labs", {}) if isinstance(plan.get("selected_labs"), dict) else {}
    lane = str(plan.get("lane", ""))
    keys = ["core"]
    if lane not in {"NO_RUNTIME_CHANGE", "STATIC_ONLY"}:
        keys.append("visual")
    keys.extend(sorted(k for k, enabled in selected.items() if enabled and k in fingerprints))
    digest = hashlib.sha256()
    for key in sorted(set(keys)):
        digest.update(key.encode())
        digest.update(b"=")
        digest.update(fingerprints[key].encode())
        digest.update(b"\0")
    return digest.hexdigest()[:16]

def self_test() -> None:
    root = Path(__file__).resolve().parent.parent
    payload = compute(root)
    assert "core" in payload and "network" in payload and len(payload["core"]) == 16
    print("AppLab v0.9 Domain Fingerprint self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan")
    parser.add_argument("--output")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    root = Path(args.root).resolve()
    payload = compute(root)
    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        payload["selected"] = selected_fingerprint(root, plan)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"selected_contract_fingerprint={payload.get('selected', payload['core'])}\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
