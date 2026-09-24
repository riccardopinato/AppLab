#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

CONTRACT_FILES = (
    "scripts/verify_apk.sh",
    "scripts/run_external_android_gate.sh",
    "scripts/dismiss_foreign_anr.py",
    "scripts/visual_qa.py",
    "scripts/visual_policy.py",
    "scripts/visual_regression.py",
    "scripts/visual_journey.py",
    "scripts/visual_journey_runtime.py",
    "scripts/prepare_visual_baseline.py",
    "scripts/validate_build_contract.py",
    "scripts/package_build_contract.py",
    "scripts/install_maestro.sh",
    "scripts/interaction_crawler.py",
    "scripts/system_lab.py",
    "scripts/performance_lab.py",
    "scripts/network_lab.py",
    "scripts/persistence_lab.py",
    "scripts/configuration_lab.py",
    "scripts/resource_pressure_lab.py",
    "scripts/upgrade_lab.py",
    "scripts/prepare_upgrade_baseline.py",
    "scripts/prepare_performance_baseline.py",
    "scripts/project_autodiscover.py",
    ".github/workflows/external-project-runner.yml",
    ".github/workflows/external-native-android-runner.yml",
    ".github/workflows/universal-project-runner.yml",
    ".github/workflows/trusted-apk-verifier.yml",
)
CONTRACT_VERSION = "0.7.7"

def compute(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(f"AppLab contract {CONTRACT_VERSION}\0".encode())
    files = list(CONTRACT_FILES)
    profiles = root / "watch-profiles"
    if profiles.is_dir():
        files.extend(
            str(path.relative_to(root))
            for path in sorted(profiles.rglob("*"))
            if path.is_file()
        )
    for relative in files:
        path = root / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--short", action="store_true")
    args = parser.parse_args()
    value = compute(Path(args.root))
    print(value[:16] if args.short else value)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
