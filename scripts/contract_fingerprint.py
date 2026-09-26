#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

CONTRACT_VERSION = "0.9.0"

CORE_FILES = (
    "scripts/verify_apk.sh",
    "scripts/run_external_android_gate.sh",
    "scripts/dismiss_foreign_anr.py",
    "scripts/validate_build_contract.py",
    "scripts/package_build_contract.py",
    "scripts/install_maestro.sh",
    "scripts/interaction_crawler.py",
    "scripts/smart_test_plan.py",
    "scripts/impact_engine.py",
    "scripts/native_task_graph.py",
    "scripts/shadow_calibration.py",
    "scripts/finalize_incremental_result.py",
    "scripts/project_autodiscover.py",
    "scripts/prepare_visual_baseline.py",
    "scripts/visual_qa.py",
    "scripts/visual_policy.py",
    "scripts/visual_regression.py",
    "scripts/visual_journey.py",
    "scripts/visual_journey_runtime.py",
    ".github/workflows/external-project-runner.yml",
    ".github/workflows/external-native-android-runner.yml",
    ".github/workflows/universal-project-runner.yml",
    ".github/workflows/trusted-apk-verifier.yml",
)

DOMAIN_FILES: dict[str, tuple[str, ...]] = {
    "system": ("scripts/system_lab.py",),
    "performance": (
        "scripts/performance_lab.py",
        "scripts/prepare_performance_baseline.py",
    ),
    "network": ("scripts/network_lab.py",),
    "persistence": ("scripts/persistence_lab.py",),
    "configuration": ("scripts/configuration_lab.py",),
    "resource_pressure": ("scripts/resource_pressure_lab.py",),
    "background": ("scripts/background_lab.py",),
    "storage": ("scripts/storage_lab.py",),
    "upgrade": (
        "scripts/upgrade_lab.py",
        "scripts/prepare_upgrade_baseline.py",
    ),
    "certification": (
        "scripts/certification_gate.py",
        "scripts/finalize_certification_matrix.py",
        "scripts/release_artifact.py",
        ".github/workflows/production-certification.yml",
    ),
}
ALL_DOMAINS = tuple(sorted(DOMAIN_FILES))

def _profile_files(root: Path) -> list[str]:
    profiles = root / "watch-profiles"
    if not profiles.is_dir():
        return []
    return [
        str(path.relative_to(root))
        for path in sorted(profiles.rglob("*"))
        if path.is_file()
    ]

def files_for_domains(root: Path, domains: set[str] | None = None) -> list[str]:
    selected = set(ALL_DOMAINS if domains is None else domains)
    unknown = selected - set(ALL_DOMAINS) - {"core"}
    if unknown:
        raise ValueError(f"unknown AppLab contract domains: {sorted(unknown)}")
    files = list(CORE_FILES)
    for domain in sorted(selected):
        if domain == "core":
            continue
        files.extend(DOMAIN_FILES[domain])
    files.extend(_profile_files(root))
    return sorted(set(files))

def compute_selected(root: Path, domains: set[str] | list[str] | tuple[str, ...]) -> str:
    root = root.resolve()
    selected = set(domains) | {"core"}
    digest = hashlib.sha256()
    digest.update(f"AppLab contract {CONTRACT_VERSION}\0".encode())
    digest.update(("domains:" + ",".join(sorted(selected)) + "\0").encode())
    for relative in files_for_domains(root, selected):
        path = root / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()

def compute(root: Path) -> str:
    return compute_selected(root, {"core", *ALL_DOMAINS, "certification"})

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "scripts").mkdir()
        (root / ".github" / "workflows").mkdir(parents=True)
        for relative in set(CORE_FILES) | {x for values in DOMAIN_FILES.values() for x in values}:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative + "\n", encoding="utf-8")
        ui_only = compute_selected(root, {"configuration", "performance"})
        network_before = compute_selected(root, {"network"})
        (root / "scripts" / "network_lab.py").write_text("changed\n", encoding="utf-8")
        ui_after = compute_selected(root, {"configuration", "performance"})
        network_after = compute_selected(root, {"network"})
        assert ui_only == ui_after
        assert network_before != network_after
    print("AppLab domain contract fingerprint self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--domains", default="")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.domains.strip():
        domains = {x.strip() for x in args.domains.split(",") if x.strip()}
        value = compute_selected(Path(args.root), domains)
    else:
        value = compute(Path(args.root))
    print(value[:16] if args.short else value)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
