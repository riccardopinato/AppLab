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
    "scripts/visual_regression.py",
    "scripts/visual_journey.py",
    "scripts/visual_journey_runtime.py",
    "scripts/prepare_visual_baseline.py",
    "scripts/project_autodiscover.py",
    ".github/workflows/external-project-runner.yml",
    ".github/workflows/external-native-android-runner.yml",
    ".github/workflows/universal-project-runner.yml",
)
CONTRACT_VERSION = "0.6.3"

def compute(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(f"AppLab contract {CONTRACT_VERSION}\0".encode())
    for relative in CONTRACT_FILES:
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
