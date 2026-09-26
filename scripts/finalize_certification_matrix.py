#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

APPLAB_VERSION = "0.9.0"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_certification_markdown(certification: dict[str, Any]) -> str:
    lines = [
        "# AppLab Production Certification",
        "",
        f"- Status: **{certification.get('status', 'BLOCKED')}**",
        f"- AppLab: {certification.get('applab_version', APPLAB_VERSION)}",
        "",
        "## Runtime matrix",
        "",
        "| Lane | API | Profile | Target | Arch | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for lane in certification.get("matrix", []):
        if not isinstance(lane, dict):
            continue
        lines.append(
            f"| {lane.get('lane', 'unknown')} | {lane.get('api_level', '—')} | "
            f"{lane.get('emulator_profile', '—')} | {lane.get('target', '—')} | "
            f"{lane.get('arch', '—')} | **{lane.get('status', 'UNKNOWN')}** |"
        )

    source = certification.get("source", {})
    apk = certification.get("apk", {})
    real_device = certification.get("real_device", {})
    lines.extend(
        [
            "",
            "## Artifact identity",
            "",
            f"- Repository: {source.get('repository', 'unknown') if isinstance(source, dict) else 'unknown'}",
            f"- Commit: {source.get('resolved_sha', 'unknown') if isinstance(source, dict) else 'unknown'}",
            f"- Package: {apk.get('package_id', 'unknown') if isinstance(apk, dict) else 'unknown'}",
            f"- Version: {apk.get('version_name', '?') if isinstance(apk, dict) else '?'} "
            f"({apk.get('version_code', '?') if isinstance(apk, dict) else '?'})",
            f"- Build variant: {apk.get('build_variant', 'unknown') if isinstance(apk, dict) else 'unknown'}",
            f"- APK SHA-256: {apk.get('sha256', 'unavailable') if isinstance(apk, dict) else 'unavailable'}",
            f"- Signing certificate SHA-256: {apk.get('signing_cert_sha256', 'unavailable') if isinstance(apk, dict) else 'unavailable'}",
            f"- Real device: {real_device.get('status', 'UNKNOWN') if isinstance(real_device, dict) else 'UNKNOWN'}",
            "",
        ]
    )

    failures = certification.get("failures", [])
    blockers = certification.get("blockers", [])
    if failures:
        lines.extend(["## Failures", ""])
        for item in failures:
            if isinstance(item, dict):
                lines.append(
                    f"- **{item.get('label', item.get('gate', 'failure'))}**: "
                    f"{item.get('observed', 'UNKNOWN')}"
                )
        lines.append("")
    if blockers:
        lines.extend(["## Blockers", ""])
        for item in blockers:
            if isinstance(item, dict):
                lines.append(
                    f"- **{item.get('label', item.get('gate', 'blocker'))}**: "
                    f"{item.get('observed', 'UNKNOWN')}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def missing_primary(repository: str, ref: str) -> dict[str, Any]:
    certification = {
        "schema_version": 1,
        "applab_version": APPLAB_VERSION,
        "status": "BLOCKED",
        "certified": False,
        "analysis_mode": "certification",
        "failures": [],
        "blockers": [
            {
                "gate": "primary_lane",
                "label": "Primary production certification lane",
                "observed": "MISSING",
            }
        ],
        "matrix": [],
    }
    return {
        "schema_version": 1,
        "applab_version": APPLAB_VERSION,
        "repository": repository,
        "ref": ref,
        "resolved_sha": "",
        "analysis_mode": "certification",
        "result": "FAIL",
        "certification_status": "BLOCKED",
        "certification": certification,
        "evidence": {},
    }


def finalize(
    primary_dir: Path,
    compatibility_dir: Path,
    *,
    repository: str,
    ref: str,
    primary_api: str,
    compatibility_api: str,
    emulator_profile: str,
) -> dict[str, Any]:
    primary_result_path = primary_dir / "result.json"
    compatibility_result_path = compatibility_dir / "result.json"

    if primary_result_path.is_file():
        primary = load_json(primary_result_path)
    else:
        primary_dir.mkdir(parents=True, exist_ok=True)
        primary = missing_primary(repository, ref)

    certification = primary.get("certification")
    if not isinstance(certification, dict):
        certification = missing_primary(repository, ref)["certification"]
        primary["certification"] = certification

    primary_status = str(certification.get("status", "")).strip().upper() or "BLOCKED"
    if compatibility_result_path.is_file():
        compatibility = load_json(compatibility_result_path)
        compatibility_status = str(compatibility.get("result", "")).strip().upper() or "MISSING"
    else:
        compatibility = {}
        compatibility_status = "MISSING"

    blockers = list(certification.get("blockers") or [])
    failures = list(certification.get("failures") or [])

    if primary_status != "CERTIFIED":
        final_status = primary_status
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
                "observed": compatibility_status,
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
                "status": "PASS" if primary_status == "CERTIFIED" else primary_status,
            }
        )
    matrix = [
        item
        for item in matrix
        if isinstance(item, dict) and item.get("lane") != "compatibility"
    ]
    matrix.append(
        {
            "lane": "compatibility",
            "api_level": str(compatibility_api),
            "emulator_profile": emulator_profile,
            "target": "google_apis",
            "arch": "x86_64",
            "status": "PASS" if compatibility_status == "PASS" else compatibility_status,
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
    primary["repository"] = primary.get("repository") or repository
    primary["ref"] = primary.get("ref") or ref
    primary["certification_status"] = final_status
    primary["certification"] = certification

    evidence = primary.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    evidence["certification_matrix"] = "certification-matrix.md"
    primary["evidence"] = evidence

    write_json(primary_result_path, primary)
    write_json(primary_dir / "certification.json", certification)
    write_json(primary_dir / "evidence-bundle.json", certification)
    final_markdown = render_certification_markdown(certification)
    (primary_dir / "certification.md").write_text(final_markdown, encoding="utf-8")
    (primary_dir / "evidence-bundle.md").write_text(final_markdown, encoding="utf-8")

    summary = primary_dir / "certification-matrix.md"
    summary.write_text(
        "# AppLab Certification Matrix\n\n"
        f"- Final status: **{final_status}**\n"
        f"- Primary API {primary_api}: **{primary_status}**\n"
        f"- Compatibility API {compatibility_api}: **{compatibility_status}**\n"
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
                "repository": "owner/repo",
                "resolved_sha": "a" * 40,
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
            repository="owner/repo",
            ref="main",
            primary_api="35",
            compatibility_api="29",
            emulator_profile="pixel_7_pro",
        )
        assert result["certification_status"] == "CERTIFIED"
        assert len(result["certification"]["matrix"]) == 2
        assert "| compatibility |" in (primary / "certification.md").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        primary = root / "primary"
        compat = root / "compat"
        result = finalize(
            primary,
            compat,
            repository="owner/repo",
            ref="main",
            primary_api="35",
            compatibility_api="29",
            emulator_profile="pixel_7_pro",
        )
        assert result["certification_status"] == "BLOCKED"
        assert (primary / "result.json").is_file()

    print("AppLab certification matrix self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-dir")
    parser.add_argument("--compatibility-dir")
    parser.add_argument("--repository", default="")
    parser.add_argument("--ref", default="")
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
        repository=args.repository,
        ref=args.ref,
        primary_api=args.primary_api,
        compatibility_api=args.compatibility_api,
        emulator_profile=args.emulator_profile,
    )
    print(f"AppLab certification matrix: {result.get('certification_status', 'BLOCKED')}")
    return 0 if result.get("certification_status") == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
