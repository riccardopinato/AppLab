#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Iterable

CONTRACT_VERSION = "0.9.0"

DOMAIN_FILES: dict[str, tuple[str, ...]] = {
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

CORE_FILES = (
    "scripts/verify_apk.sh",
    "scripts/certification_gate.py",
    "scripts/finalize_certification_matrix.py",
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
    "scripts/preflight_result.py",
    "scripts/shadow_calibration.py",
    "scripts/gradle_execution_plan.py",
    "scripts/install_maestro.sh",
    "scripts/interaction_crawler.py",
    "scripts/smart_test_plan.py",
    "scripts/project_autodiscover.py",
    "scripts/watch_discover.py",
    "scripts/finalize_external_result.py",
    ".github/workflows/repo-watcher.yml",
    ".github/workflows/external-project-runner.yml",
    ".github/workflows/external-native-android-runner.yml",
    ".github/workflows/universal-project-runner.yml",
    ".github/workflows/trusted-apk-verifier.yml",
    ".github/workflows/production-certification.yml",
)

def normalize_labs(labs: Iterable[str] | None) -> tuple[str, ...]:
    if labs is None:
        return tuple(sorted(DOMAIN_FILES))
    clean = tuple(sorted({str(x).strip() for x in labs if str(x).strip()}))
    unknown = set(clean) - set(DOMAIN_FILES)
    if unknown:
        raise ValueError(f"Unknown AppLab contract domains: {sorted(unknown)}")
    return clean

def files_for(labs: Iterable[str] | None = None) -> tuple[str, ...]:
    selected = normalize_labs(labs)
    files = list(CORE_FILES)
    for lab in selected:
        files.extend(DOMAIN_FILES[lab])
    return tuple(dict.fromkeys(files))

def compute(root: Path, labs: Iterable[str] | None = None) -> str:
    digest = hashlib.sha256()
    selected = normalize_labs(labs)
    digest.update(f"AppLab contract {CONTRACT_VERSION}\0".encode())
    digest.update(("domains=" + ",".join(selected) + "\0").encode())
    files = list(files_for(selected))
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
    parser.add_argument(
        "--labs",
        default="*",
        help="Comma-separated selected specialist labs, or * for all.",
    )
    args = parser.parse_args()
    labs = None if args.labs.strip() == "*" else [x for x in args.labs.split(",") if x.strip()]
    value = compute(Path(args.root), labs)
    print(value[:16] if args.short else value)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
