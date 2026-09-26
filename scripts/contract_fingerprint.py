#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "0.9.0"

CORE_FILES = (
    "scripts/verify_apk.sh",
    "scripts/run_external_android_gate.sh",
    "scripts/dismiss_foreign_anr.py",
    "scripts/finalize_external_result.py",
    "scripts/release_artifact.py",
    "scripts/interaction_crawler.py",
    "scripts/visual_qa.py",
    "scripts/visual_policy.py",
    "scripts/visual_regression.py",
    "scripts/visual_journey.py",
    "scripts/visual_journey_runtime.py",
    "scripts/prepare_visual_baseline.py",
    "scripts/package_build_contract.py",
    "scripts/validate_build_contract.py",
    "scripts/install_maestro.sh",
    "scripts/smart_test_plan.py",
    "scripts/source_only_result.py",
    "scripts/shadow_calibration.py",
    "scripts/telemetry_summary.py",
    "scripts/project_autodiscover.py",
    ".github/workflows/external-project-runner.yml",
    ".github/workflows/external-native-android-runner.yml",
    ".github/workflows/universal-project-runner.yml",
    ".github/workflows/trusted-apk-verifier.yml",
)

DOMAIN_FILES: dict[str, tuple[str, ...]] = {
    "system": ("scripts/system_lab.py", "integration/system/SYSTEM_UI_LAB.md"),
    "performance": (
        "scripts/performance_lab.py",
        "scripts/prepare_performance_baseline.py",
        "integration/performance/FAST_ANALYSIS_ENGINE.md",
    ),
    "network": ("scripts/network_lab.py", "integration/network/NETWORK_OFFLINE_LAB.md"),
    "persistence": (
        "scripts/persistence_lab.py",
        "integration/persistence/PERSISTENCE_RESTART_LAB.md",
    ),
    "configuration": (
        "scripts/configuration_lab.py",
        "integration/configuration/CONFIGURATION_LIFECYCLE_STRESS_LAB.md",
    ),
    "resource_pressure": (
        "scripts/resource_pressure_lab.py",
        "integration/resources/RESOURCE_PRESSURE_PROCESS_DEATH_LAB.md",
    ),
    "background": (
        "scripts/background_lab.py",
        "integration/background/BACKGROUND_DOZE_RECOVERY_LAB.md",
    ),
    "storage": (
        "scripts/storage_lab.py",
        "integration/storage/STORAGE_DATA_INTEGRITY_LAB.md",
    ),
    "upgrade": (
        "scripts/upgrade_lab.py",
        "scripts/prepare_upgrade_baseline.py",
        "integration/upgrade/UPGRADE_MIGRATION_LAB.md",
    ),
    "certification": (
        "scripts/certification_gate.py",
        "scripts/finalize_certification_matrix.py",
        ".github/workflows/production-certification.yml",
        "integration/certification/PRODUCTION_CERTIFICATION_GATE.md",
    ),
}


def _watch_profiles(root: Path) -> tuple[str, ...]:
    profiles = root / "watch-profiles"
    if not profiles.is_dir():
        return ()
    return tuple(
        str(path.relative_to(root))
        for path in sorted(profiles.rglob("*"))
        if path.is_file()
    )


def _digest(root: Path, label: str, files: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(f"AppLab {CONTRACT_VERSION} {label}\0".encode())
    for relative in sorted(set(files)):
        path = root / relative
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def compute_domains(root: Path) -> dict[str, str]:
    root = root.resolve()
    core_files = list(CORE_FILES) + list(_watch_profiles(root))
    result = {"core": _digest(root, "core", core_files)}
    for domain, files in DOMAIN_FILES.items():
        result[domain] = _digest(root, domain, list(files))
    return result


def compute_selected(
    root: Path,
    selected_labs: dict[str, Any] | list[str] | tuple[str, ...] | set[str] | None,
    *,
    certification: bool = False,
) -> str:
    domains = compute_domains(root)
    selected: set[str] = set()
    if isinstance(selected_labs, dict):
        selected = {str(k) for k, enabled in selected_labs.items() if bool(enabled)}
    elif selected_labs:
        selected = {str(item) for item in selected_labs}
    if certification:
        selected.add("certification")

    digest = hashlib.sha256()
    digest.update(f"AppLab selected {CONTRACT_VERSION}\0".encode())
    digest.update(f"core:{domains['core']}\0".encode())
    for domain in sorted(selected):
        if domain in domains:
            digest.update(f"{domain}:{domains[domain]}\0".encode())
    return digest.hexdigest()


def compute(root: Path) -> str:
    """Compatibility: complete contract fingerprint across all domains."""
    return compute_selected(
        root,
        {domain: True for domain in DOMAIN_FILES if domain != "certification"},
        certification=True,
    )


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "scripts").mkdir()
        (root / "scripts/verify_apk.sh").write_text("core\n", encoding="utf-8")
        (root / "scripts/network_lab.py").write_text("network-a\n", encoding="utf-8")
        (root / "scripts/storage_lab.py").write_text("storage-a\n", encoding="utf-8")

        before_network = compute_selected(root, {"network": True})
        before_storage = compute_selected(root, {"storage": True})
        (root / "scripts/network_lab.py").write_text("network-b\n", encoding="utf-8")
        after_network = compute_selected(root, {"network": True})
        after_storage = compute_selected(root, {"storage": True})

        assert before_network != after_network
        assert before_storage == after_storage
    print("AppLab domain contract fingerprint self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--domains-json", default="")
    parser.add_argument("--certification", action="store_true")
    parser.add_argument("--all-domains", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    root = Path(args.root)
    if args.all_domains:
        payload = compute_domains(root)
        if args.short:
            payload = {key: value[:16] for key, value in payload.items()}
        print(json.dumps(payload, sort_keys=True))
        return 0

    if args.domains_json:
        selected = json.loads(args.domains_json)
        value = compute_selected(root, selected, certification=args.certification)
    else:
        value = compute(root)
    print(value[:16] if args.short else value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
