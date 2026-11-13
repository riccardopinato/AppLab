#!/usr/bin/env python3
"""X10-026 real immutable package-version rollback helper (never a Golden admission)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

OLD = "1d1a8628e25f58b788b013cf6955763d00363cdc"
NEW = "710e83261bcadc1cfd5eda3e28d77bed8b8bc576"
PACKAGE = "factory_profile_kit"
SRC = "19-APP-FACTORY-10X/flutter_kits/profile"
FACTORY = "c5adc147046beb7024629466d10eeb799c3c2619"
ANNA = "984a34462ba527b2ea98dbc3a337bdd8614b88d4"
TASTE = "61a83aa638654f4e885d503e024408d2dcddebc2"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def version_at(directory: Path, expected_version: str) -> None:
    pubspec = (directory / "pubspec.yaml").read_text()
    require(re.search(rf"(?m)^version: {re.escape(expected_version)}$", pubspec) is not None,
            f"PACKAGE_VERSION_MISMATCH:{directory}")


def check_consumer(root: Path, ref: str, version: str) -> None:
    pubspec = (root / "pubspec.yaml").read_text()
    lock = (root / "pubspec.lock").read_text()
    require(pubspec.count("factory_profile_kit:") == 1, "PACKAGE_DECLARATION_DUPLICATE")
    require(f"ref: {ref}" in pubspec, f"PUBSPEC_REF_MISMATCH:{root}")
    package = re.search(r"(?ms)^  factory_profile_kit:\n(.*?)(?=^  [a-zA-Z]|\Z)", lock)
    require(package is not None, f"LOCK_MISSING_PACKAGE:{root}")
    block = package.group(1)
    require(f'ref: "{ref}"' in block and f'resolved-ref: "{ref}"' in block,
            f"LOCK_REF_MISMATCH:{root}")
    require("source: git" in block and f'version: "{version}"' in block,
            f"LOCK_VERSION_MISMATCH:{root}")


def switch_consumer(root: Path, old: str, new: str) -> None:
    path = root / "pubspec.yaml"
    original = path.read_text()
    require(original.count(f"ref: {old}") == 1, f"EXPECTED_IMMUTABLE_REF_NOT_FOUND:{root}")
    require(f"ref: {new}" not in original, "REF_ALREADY_PRESENT")
    path.write_text(original.replace(f"ref: {old}", f"ref: {new}", 1))


def receipt_files(out: Path, expected_run_id: str) -> None:
    from golden_compat_harness_x10 import assess

    run_id = os.environ.get("GITHUB_RUN_ID")
    require(run_id == expected_run_id and run_id.isdigit(), "GITHUB_RUN_PROVENANCE_MISSING")
    require(os.environ.get("GITHUB_REPOSITORY") == "riccardopinato/AppLab",
            "UNEXPECTED_RUN_REPOSITORY")
    dart_version = subprocess.run(["dart", "--version"], capture_output=True,
                                  text=True, check=True)
    sdk_text = dart_version.stdout + dart_version.stderr
    dart_match = re.search(r"Dart SDK version: (\d+\.\d+\.\d+)", sdk_text)
    flutter_info = subprocess.run(["flutter", "--version", "--machine"],
                                  capture_output=True, text=True, check=True)
    flutter_version = json.loads(flutter_info.stdout)["frameworkVersion"]
    require(dart_match is not None and re.fullmatch(r"\d+\.\d+\.\d+", flutter_version),
            "SDK_VERSION_UNKNOWN")
    run_url = f"https://github.com/riccardopinato/AppLab/actions/runs/{run_id}"
    manifest = {
        "schema_version": 1, "package_name": PACKAGE, "package_state": "PACKAGE_TESTED",
        "version": "0.1.1", "factory_sha": FACTORY,
        "golden": {"registry_sha": FACTORY, "id": "profile_standard",
                   "admission_requested": False},
        "provenance": {"donor_repo": "riccardopinato/Idee-app-Archivi-riferimenti",
                       "donor_sha": NEW,
                       "source_files": [f"{SRC}/lib/factory_profile_kit.dart",
                                        f"{SRC}/pubspec.yaml"]},
        "license": "INTERNAL_APPROVED",
        "compatibility": {"tested_pairs": [
            {"dart": dart_match.group(1), "flutter": flutter_version, "test_url": run_url}
        ]},
        "tests": {"donor_ci_urls": [run_url], "consumer_ci_urls": [run_url]},
        "consumers": [
            {"repo": "riccardopinato/Agenda-per-Anna", "source_sha": ANNA,
             "approved": True, "test_url": run_url},
            {"repo": "riccardopinato/TasteAI", "source_sha": TASTE,
             "approved": True, "test_url": run_url},
        ],
        "release": {"publish_authorized": False, "rollback_version": "0.1.0"}
    }
    def entry(kind: str, repo: str, sha: str) -> dict[str, str]:
        return {"kind": kind, "repository": repo, "source_sha": sha,
                "package_name": PACKAGE, "version": "0.1.1", "result": "PASS",
                "run_url": run_url, "dart": dart_match.group(1),
                "flutter": flutter_version}
    receipts = [
        entry("DONOR", "riccardopinato/Idee-app-Archivi-riferimenti", NEW),
        entry("CONSUMER", "riccardopinato/Agenda-per-Anna", ANNA),
        entry("CONSUMER", "riccardopinato/TasteAI", TASTE),
        {**entry("ROLLBACK", "riccardopinato/Idee-app-Archivi-riferimenti", NEW),
         "from_version": "0.1.1", "to_version": "0.1.0"},
    ]
    result = assess(manifest, receipts)
    require(result["state"] == "STRUCTURAL_PASS_REVIEW_REQUIRED"
            and result["counts"] == {"DONOR": 1, "CONSUMER": 2, "ROLLBACK": 1}
            and result["automatic_promotion"] is False, "UNEXPECTED_HARNESS_RESULT")
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    (out / "harness_result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": result, "run_url": run_url,
                      "scope": "CI WORKTREE PACKAGE SEMVER, NOT DEVICE/GOLDEN"},
                     sort_keys=True))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["version", "check", "switch", "receipt"])
    p.add_argument("--root", type=Path)
    p.add_argument("--ref", choices=[OLD, NEW])
    p.add_argument("--from-ref", choices=[OLD, NEW])
    p.add_argument("--to-ref", choices=[OLD, NEW])
    p.add_argument("--version")
    p.add_argument("--out", type=Path)
    p.add_argument("--run-id")
    args = p.parse_args()
    if args.action == "version":
        require(args.root is not None and args.version is not None, "ARGS")
        version_at(args.root, args.version)
    elif args.action == "check":
        require(args.root is not None and args.ref is not None and args.version is not None, "ARGS")
        check_consumer(args.root, args.ref, args.version)
    elif args.action == "switch":
        require(args.root is not None and args.from_ref and args.to_ref, "ARGS")
        switch_consumer(args.root, args.from_ref, args.to_ref)
    else:
        require(args.out is not None and args.run_id is not None, "ARGS")
        receipt_files(args.out, args.run_id)


if __name__ == "__main__":
    main()
