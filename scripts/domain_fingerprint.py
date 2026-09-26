#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from contract_fingerprint import CONTRACT_FILES


SPECIALIST_DOMAINS: dict[str, tuple[str, ...]] = {
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
        "scripts/visual_qa.py",
        "scripts/visual_policy.py",
        "scripts/visual_regression.py",
        "scripts/visual_journey.py",
        "scripts/visual_journey_runtime.py",
        "scripts/prepare_visual_baseline.py",
        "scripts/interaction_crawler.py",
    ),
}

_SPECIALIST_FILES = {
    relative
    for files in SPECIALIST_DOMAINS.values()
    for relative in files
}

# Any contract-affecting input that is not owned by one specialist domain is
# core by definition. This makes domain-scoped caching safe-by-default when a
# new workflow/security/planner input is added to CONTRACT_FILES.
CORE_FILES = tuple(
    relative for relative in CONTRACT_FILES
    if relative not in _SPECIALIST_FILES
)

DOMAINS: dict[str, tuple[str, ...]] = {
    "core": CORE_FILES,
    **SPECIALIST_DOMAINS,
}


def digest(root: Path, files: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for rel in files:
        p = root / rel
        h.update(rel.encode())
        h.update(b"\0")
        h.update(p.read_bytes() if p.is_file() else b"<missing>")
        h.update(b"\0")
    return h.hexdigest()[:16]


def watch_profile_files(root: Path) -> tuple[str, ...]:
    profiles = root / "watch-profiles"
    if not profiles.is_dir():
        return ()
    return tuple(
        str(path.relative_to(root))
        for path in sorted(profiles.rglob("*"))
        if path.is_file()
    )


def compute(root: Path) -> dict[str, str]:
    profiles = watch_profile_files(root)
    values: dict[str, str] = {}
    for name, files in DOMAINS.items():
        scoped = files + profiles if name == "core" else files
        values[name] = digest(root, scoped)
    return values


def adaptive_digest(root: Path, selected_labs: dict[str, object] | None) -> str:
    domains = compute(root)
    if isinstance(selected_labs, dict) and selected_labs:
        names = {"core", "visual"}
        names.update(
            lab for lab, enabled in selected_labs.items()
            if bool(enabled) and lab in domains
        )
    else:
        names = set(domains)
    h = hashlib.sha256()
    for name in sorted(names):
        h.update(name.encode())
        h.update(b"\0")
        h.update(domains.get(name, "").encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def self_test(root: Path) -> None:
    values = compute(root)
    assert "core" in values
    required_core = {
        "scripts/certification_gate.py",
        "scripts/install_maestro.sh",
        "scripts/project_autodiscover.py",
        ".github/workflows/trusted-apk-verifier.yml",
        ".github/workflows/external-project-runner.yml",
        ".github/workflows/external-native-android-runner.yml",
        ".github/workflows/universal-project-runner.yml",
        ".github/workflows/production-certification.yml",
    }
    assert required_core.issubset(set(CORE_FILES))
    covered = set(CORE_FILES) | _SPECIALIST_FILES
    assert set(CONTRACT_FILES).issubset(covered)
    profiles = watch_profile_files(root)
    if profiles:
        original = compute(root)["core"]
        first = root / profiles[0]
        before = first.read_bytes()
        try:
            first.write_bytes(before + b"\n# AppLab fingerprint self-test\n")
            assert compute(root)["core"] != original
        finally:
            first.write_bytes(before)
    sample = adaptive_digest(root, {"network": True, "storage": False})
    assert len(sample) == 16
    print("AppLab domain fingerprint self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    root = Path(args.root)
    if args.self_test:
        self_test(root)
        return 0
    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        selected = plan.get("selected_labs", {}) if isinstance(plan, dict) else {}
        value = adaptive_digest(root, selected if isinstance(selected, dict) else {})
        if args.github_output:
            with Path(args.github_output).open("a", encoding="utf-8") as handle:
                handle.write(f"fingerprint={value}\n")
        if args.output:
            Path(args.output).write_text(value + "\n", encoding="utf-8")
        else:
            print(value)
        return 0

    values = compute(root)
    payload = json.dumps(values, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
