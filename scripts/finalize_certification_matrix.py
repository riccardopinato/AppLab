#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

APPLAB_VERSION = "0.8.1"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def finalize(
    primary_dir: Path,
    compatibility_dir: Path,
    *,
    primary_api: str,
    compatibility_api: str,
    emulator_profile: str,
) -> dict[str, Any]:
    primary_result_path = primary_dir / "result.json"
    compatibility_result_path = compatibility_dir / "result.json"

    primary = load_json(primary_result_path)
    compatibility = load_json(compatibility_result_path)
    certification = primary.get("certification")
    if not isinstance(certification, dict):
        raise ValueError("Primary production certification evidence is missing")

    primary_status = str(certification.get("status", "")).strip().upper()
    compatibility_status = str(compatibility.get("result", "")).strip().upper()

    blockers = certification.get("blockers")
    failures = certification.get("failures")
    if not isinstance(blockers, list):
        blockers = []
    if not isinstance(failures, list):
        failures = []

    if primary_status != "CERTIFIED":
        final_status = primary_status or "BLOCKED"
    elif compatibility_status == "PASS":
        final_status = "CERTIFIED"
    elif compatibility_status in {"FAIL", "ERROR"}:
        failures.append(
            {
                "gate": "compatibility_lane",
                "label": "Compatibility Android lane",
                "observed": compatibility_status,
            }
        )
        final_status = "NOT_CERTIFIED"
    else:
        blockers.append(
            {
                "gate": "compatibility_lane",
                "label": "Compatibility Android lane",
                "observed": compatibility_status or "MISSING",
            }
        )
        final_status = "BLOCKED"

    matrix = certification.get("matrix")
    if not isinstance(matrix, list):
        matrix = []
    if not matrix:
        matrix.append(
            {
                "lane": "primary",
                "api_level": str(primary_api),
                "emulator_profile": emulator_profile,
                "target": "google_apis",
                "arch": "x86_64",
                "status": "PASS" if primary_status == "CERTIFIED" else primary_status or "BLOCKED",
            }
        )
    matrix = [item for item in matrix if isinstance(item, dict) and item.get("lane") != "compatibility"]
    matrix.append(
        {
            "lane": "compatibility",
            "api_level": str(compatibility_api),
            "emulator_profile": emulator_profile,
            "target": "google_apis",
            "arch": "x86_64",
            "status": "PASS" if compatibility_status == "PASS" else compatibility_status or "BLOCKED",
            "scope": "release-profile compatibility smoke",
        }
    )

    certification["matrix"] = matrix
    certification["failures"] = failures
    certification["blockers"] = blockers
    certification["status"] = final_status
    certification["certified"] = final_status == "CERTIFIED"
    certification["applab_version"] = APPLAB_VERSION

    primary["applab_version"] = APPLAB_VERSION
    primary["certification_status"] = final_status
    primary["certification"] = certification
    write_json(primary_result_path, primary)

    for name in ("certification.json", "evidence-bundle.json"):
        path = primary_dir / name
        if path.exists():
            write_json(path, certification)

    summary = primary_dir / "certification-matrix.md"
    summary.write_text(
        "# AppLab Certification Matrix\n\n"
        f"- Final status: **{final_status}**\n"
        f"- Primary API {primary_api}: **{primary_status or 'MISSING'}**\n"
        f"- Compatibility API {compatibility_api}: **{compatibility_status or 'MISSING'}**\n"
        f"- Profile: {emulator_profile}\n",
        encoding="utf-8",
    )
    return primary


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        primary = root / "primary"
        compat = root / "compat"
        primary.mkdir()
        compat.mkdir()
        write_json(
            primary / "result.json",
            {
                "certification_status": "CERTIFIED",
                "certification": {
                    "status": "CERTIFIED",
                    "certified": True,
                    "failures": [],
                    "blockers": [],
                    "matrix": [{"lane": "primary", "api_level": "35", "status": "PASS"}],
                },
            },
        )
        write_json(compat / "result.json", {"result": "PASS"})
        result = finalize(
            primary,
            compat,
            primary_api="35",
            compatibility_api="29",
            emulator_profile="pixel_7_pro",
        )
        assert result["certification_status"] == "CERTIFIED"
        assert len(result["certification"]["matrix"]) == 2

        write_json(compat / "result.json", {"result": "FAIL"})
        result = finalize(
            primary,
            compat,
            primary_api="35",
            compatibility_api="29",
            emulator_profile="pixel_7_pro",
        )
        assert result["certification_status"] == "NOT_CERTIFIED"

    print("AppLab certification matrix self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-dir")
    parser.add_argument("--compatibility-dir")
    parser.add_argument("--primary-api", default="35")
    parser.add_argument("--compatibility-api", default="29")
    parser.add_argument("--emulator-profile", default="pixel_7_pro")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.primary_dir or not args.compatibility_dir:
        raise SystemExit("--primary-dir and --compatibility-dir are required")

    result = finalize(
        Path(args.primary_dir),
        Path(args.compatibility_dir),
        primary_api=args.primary_api,
        compatibility_api=args.compatibility_api,
        emulator_profile=args.emulator_profile,
    )
    print(f"AppLab certification matrix: {result.get('certification_status', 'BLOCKED')}")
    return 0 if result.get("certification_status") == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
