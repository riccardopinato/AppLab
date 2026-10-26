#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENGINE_VERSION = "5.9D"
TRUSTED_HOOK = re.compile(
    r'^bash "\$GITHUB_WORKSPACE/\.applab/watch-profiles/([A-Za-z0-9_.-]+\.sh)"$'
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def assess(entry: dict[str, Any], trusted_root: Path) -> dict[str, Any]:
    repository = str(entry.get("repository", "")).strip()
    reasons: list[str] = []

    if entry.get("build_once_pilot") is not True:
        reasons.append("BUILD_ONCE_PILOT_NOT_ENABLED")
    if entry.get("reuse_pilot") is not True:
        reasons.append("EXACT_ARTIFACT_REUSE_NOT_ENABLED")
    if str(entry.get("engine", "")).strip() != "flutter":
        reasons.append("ENGINE_NOT_EXPLICIT_FLUTTER")
    if not str(entry.get("flutter_version", "")).strip():
        reasons.append("FLUTTER_VERSION_NOT_PINNED")

    material: list[str] = []
    for field in ("prepare_command", "post_pub_get_command"):
        raw = str(entry.get(field, "")).strip()
        match = TRUSTED_HOOK.fullmatch(raw)
        if not match:
            reasons.append(f"{field.upper()}_NOT_TRUSTED")
            continue
        relative = f"watch-profiles/{match.group(1)}"
        path = trusted_root / relative
        if not path.is_file() or path.is_symlink():
            reasons.append(f"{field.upper()}_MATERIAL_MISSING")
            continue
        material.append(relative)

    build_command = str(entry.get("build_command", "")).strip()
    apk_path = str(entry.get("apk_path", "")).strip()
    if not build_command.startswith("flutter build apk "):
        reasons.append("RUNTIME_BUILD_COMMAND_NOT_FLUTTER_APK")
    if "--split-per-abi" in build_command:
        reasons.append("RUNTIME_BUILD_STILL_SPLIT_PER_ABI")
    if "--target-platform android-x64" not in build_command:
        reasons.append("RUNTIME_BUILD_NOT_X64_SCOPED")
    if apk_path != "build/app/outputs/flutter-apk/app-release.apk":
        reasons.append("RUNTIME_APK_PATH_NOT_SINGLE_ARTIFACT")

    ready = not reasons
    return {
        "repository": repository,
        "state": "READY" if ready else "HOLD",
        "production_build_once_ready": ready,
        "exact_artifact_reuse_required": True,
        "runtime_artifact_policy": "SINGLE_ANDROID_X64_APK",
        "runtime_apk_path": apk_path,
        "unnecessary_split_abi_builds_removed": (
            "--split-per-abi" not in build_command
            and "--target-platform android-x64" in build_command
        ),
        "trusted_hook_material": sorted(material),
        "reasons": reasons,
    }


def build_report(watchlist: dict[str, Any], trusted_root: Path) -> dict[str, Any]:
    entries = [
        item
        for item in watchlist.get("repositories", [])
        if isinstance(item, dict) and item.get("build_once_pilot") is True
    ]
    rows = [assess(item, trusted_root) for item in entries]
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "record_type": "BUILD_ONCE_PROMOTION_V59D",
        "authority": "EXECUTION_ADMISSION_ONLY",
        "coverage_reduction_enabled": False,
        "certification_authority_unchanged": True,
        "size_audit_artifact_identity_remains_separate": True,
        "pilot_count": len(rows),
        "ready_count": sum(
            1 for row in rows if row.get("production_build_once_ready") is True
        ),
        "status": (
            "PASS"
            if rows and all(row.get("production_build_once_ready") is True for row in rows)
            else "HOLD"
        ),
        "repositories": rows,
    }


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        profiles = root / "watch-profiles"
        profiles.mkdir()
        for name in ("prepare.sh", "post.sh"):
            (profiles / name).write_text(
                "#!/usr/bin/env bash\nset -Eeuo pipefail\n",
                encoding="utf-8",
            )

        good = {
            "repository": "owner/app",
            "engine": "flutter",
            "flutter_version": "3.47.5",
            "prepare_command": 'bash "$GITHUB_WORKSPACE/.applab/watch-profiles/prepare.sh"',
            "post_pub_get_command": 'bash "$GITHUB_WORKSPACE/.applab/watch-profiles/post.sh"',
            "build_command": "flutter build apk --release --target-platform android-x64",
            "apk_path": "build/app/outputs/flutter-apk/app-release.apk",
            "reuse_pilot": True,
            "build_once_pilot": True,
        }
        ready = assess(good, root)
        assert ready["production_build_once_ready"] is True
        assert ready["unnecessary_split_abi_builds_removed"] is True

        split = dict(good)
        split["build_command"] += " --split-per-abi"
        blocked = assess(split, root)
        assert blocked["production_build_once_ready"] is False
        assert "RUNTIME_BUILD_STILL_SPLIT_PER_ABI" in blocked["reasons"]

        mutable = dict(good)
        mutable["prepare_command"] = "bash tool/setup.sh"
        blocked = assess(mutable, root)
        assert blocked["production_build_once_ready"] is False
        assert "PREPARE_COMMAND_NOT_TRUSTED" in blocked["reasons"]

        report = build_report({"repositories": [good]}, root)
        assert report["status"] == "PASS"
        assert report["ready_count"] == 1
        assert report["coverage_reduction_enabled"] is False

    print("AppLab v5.9D build-once promotion self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist", default="watchlist.json")
    parser.add_argument("--trusted-root", default=".")
    parser.add_argument("--output", default="")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    report = build_report(
        read_json(Path(args.watchlist)),
        Path(args.trusted_root).resolve(),
    )
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.require_ready and report["status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
