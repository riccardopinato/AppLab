#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CORE_FILES = (
    "scripts/verify_apk.sh",
    "scripts/certification_gate.py",
    "scripts/finalize_certification_matrix.py",
    "scripts/run_external_android_gate.sh",
    "scripts/dismiss_foreign_anr.py",
    "scripts/smart_test_plan.py",
    "scripts/non_runtime_result.py",
    "scripts/shadow_calibration.py",
    "scripts/attach_shadow_results.py",
    "scripts/analysis_telemetry.py",
    "scripts/package_build_contract.py",
    "scripts/validate_build_contract.py",
    "scripts/project_autodiscover.py",
    "scripts/install_maestro.sh",
    ".github/workflows/external-project-runner.yml",
    ".github/workflows/external-native-android-runner.yml",
    ".github/workflows/universal-project-runner.yml",
    ".github/workflows/trusted-apk-verifier.yml",
    ".github/workflows/production-certification.yml",
)

DOMAIN_FILES: dict[str, tuple[str, ...]] = {
    "visual": (
        "scripts/visual_qa.py",
        "scripts/visual_policy.py",
        "scripts/visual_regression.py",
        "scripts/visual_journey.py",
        "scripts/visual_journey_runtime.py",
        "scripts/prepare_visual_baseline.py",
        "scripts/interaction_crawler.py",
    ),
    "system": ("scripts/system_lab.py",),
    "performance": ("scripts/performance_lab.py", "scripts/prepare_performance_baseline.py"),
    "network": ("scripts/network_lab.py",),
    "persistence": ("scripts/persistence_lab.py",),
    "configuration": ("scripts/configuration_lab.py",),
    "resource_pressure": ("scripts/resource_pressure_lab.py",),
    "background": ("scripts/background_lab.py",),
    "storage": ("scripts/storage_lab.py",),
    "upgrade": ("scripts/upgrade_lab.py", "scripts/prepare_upgrade_baseline.py"),
}

CONTRACT_VERSION = "0.9.0"

def digest_files(root: Path, label: str, files: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(f"AppLab {CONTRACT_VERSION} {label}\0".encode())
    for relative in files:
        path = root / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()

def profile_files(root: Path) -> list[str]:
    profiles = root / "watch-profiles"
    if not profiles.is_dir():
        return []
    return [
        str(path.relative_to(root))
        for path in sorted(profiles.rglob("*"))
        if path.is_file()
    ]

def compute_core(root: Path) -> str:
    return digest_files(root, "core", list(CORE_FILES) + profile_files(root))

def compute_domain(root: Path, domain: str) -> str:
    if domain not in DOMAIN_FILES:
        raise ValueError(f"Unknown AppLab contract domain: {domain}")
    return digest_files(root, f"domain:{domain}", list(DOMAIN_FILES[domain]))

def manifest(root: Path) -> dict[str, object]:
    domains = {name: compute_domain(root, name) for name in sorted(DOMAIN_FILES)}
    all_files = list(CORE_FILES) + profile_files(root)
    for files in DOMAIN_FILES.values():
        all_files.extend(files)
    return {
        "schema_version": 1,
        "version": CONTRACT_VERSION,
        "core": compute_core(root),
        "domains": domains,
        "full": digest_files(root, "full", sorted(set(all_files))),
    }

def compute(root: Path) -> str:
    return str(manifest(root)["full"])

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--domain", default="")
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)
    if args.manifest:
        print(json.dumps(manifest(root), indent=2, sort_keys=True))
        return 0
    value = compute_domain(root, args.domain) if args.domain else compute(root)
    print(value[:16] if args.short else value)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
