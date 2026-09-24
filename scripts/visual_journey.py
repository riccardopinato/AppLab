#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import visual_qa
import visual_regression
import visual_policy


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def aggregate(values: list[str], no_baseline: str = "NO_BASELINE") -> str:
    if not values:
        return no_baseline
    if "FAIL" in values or "ERROR" in values:
        return "FAIL"
    if "WARN" in values:
        return "WARN"
    comparable = [value for value in values if value != no_baseline]
    if comparable and all(value == "PASS" for value in comparable):
        return "PASS"
    if all(value == no_baseline for value in values):
        return no_baseline
    return "PASS"


def checkpoint_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    result = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or not SAFE_NAME.fullmatch(path.name):
            continue
        if (path / "screenshot.png").is_file() and (path / "window.xml").is_file():
            result.append(path)
    return result


def evaluate(
    current_root: Path,
    baseline_root: Path | None,
    package_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or visual_policy.validate_config(None)
    screens = []
    qa_results: list[str] = []
    regression_results: list[str] = []

    for current in checkpoint_dirs(current_root):
        name = current.name
        qa = visual_qa.evaluate(
            current / "screenshot.png",
            current / "window.xml",
            package_id,
        )
        qa_results.append(str(qa["result"]))
        policy = visual_policy.policy_for(config, name)

        regression: dict[str, Any]
        baseline = baseline_root / name if baseline_root else None
        if (
            baseline is not None
            and (baseline / "screenshot.png").is_file()
            and (baseline / "window.xml").is_file()
        ):
            regression = visual_regression.evaluate(
                baseline / "screenshot.png",
                baseline / "window.xml",
                current / "screenshot.png",
                current / "window.xml",
                package_id,
                visual_regression.load_metadata(
                    baseline / "metadata.json"
                    if (baseline / "metadata.json").is_file()
                    else None
                ),
                policy=policy,
                heatmap_path=current / "visual-diff-heatmap.png",
            )
        else:
            regression = {
                "schema_version": 1,
                "visual_regression_version": "0.6.5",
                "result": "NO_BASELINE",
                "errors": 0,
                "warnings": 0,
                "package_id": package_id,
                "baseline_metadata": {},
                "policy": {
                    "profile": policy["profile"],
                    "auto_mask_dynamic_views": policy["auto_mask_dynamic_views"],
                    "manual_mask_count": len(policy["masks"]),
                    "ignore_text_regex": policy["ignore_text_regex"],
                    "thresholds": policy["thresholds"],
                },
                "image_difference": {},
                "ui_difference": {},
                "findings": [],
            }

        regression_results.append(str(regression["result"]))
        screens.append(
            {
                "name": name,
                "visual_qa": qa,
                "visual_regression": regression,
            }
        )

    if not screens:
        raise ValueError("No visual journey checkpoints were captured")

    qa_result = aggregate(qa_results, no_baseline="SKIPPED")
    regression_result = aggregate(regression_results)
    overall = "FAIL" if "FAIL" in {qa_result, regression_result} else (
        "WARN" if "WARN" in {qa_result, regression_result} else "PASS"
    )

    return {
        "schema_version": 1,
        "visual_journey_version": "0.6.5",
        "result": overall,
        "visual_qa": qa_result,
        "visual_regression": regression_result,
        "checkpoint_count": len(screens),
        "checkpoints": screens,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# AppLab Multi-Screen Visual Journey",
        "",
        f"- Result: **{report['result']}**",
        f"- Smart Visual QA: **{report['visual_qa']}**",
        f"- Visual Regression: **{report['visual_regression']}**",
        f"- Checkpoints: {report['checkpoint_count']}",
        "",
        "| Checkpoint | Profile | Visual QA | Regression |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["checkpoints"]:
        lines.append(
            f"| {item['name']} | "
            f"{item['visual_regression'].get('policy', {}).get('profile', 'standard')} | "
            f"{item['visual_qa']['result']} | "
            f"{item['visual_regression']['result']} |"
        )

    for item in report["checkpoints"]:
        findings = (
            item["visual_qa"].get("findings", [])
            + item["visual_regression"].get("findings", [])
        )
        if not findings:
            continue
        lines.extend(["", f"## {item['name']}", ""])
        for finding in findings:
            lines.append(
                f"- **{finding.get('severity', 'info').upper()} — "
                f"{finding.get('code', 'finding')}**: "
                f"{finding.get('message', '')}"
            )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_compat_reports(report_dir: Path, report: dict[str, Any]) -> None:
    checkpoints = report.get("checkpoints", [])
    if not checkpoints:
        return
    selected = next(
        (item for item in checkpoints if item.get("name") == "final"),
        checkpoints[-1],
    )
    qa = selected["visual_qa"]
    regression = selected["visual_regression"]
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "visual-qa.json").write_text(
        json.dumps(qa, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    visual_qa.write_markdown(report_dir / "visual-qa.md", qa)
    (report_dir / "visual-regression.json").write_text(
        json.dumps(regression, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    visual_regression.write_markdown(
        report_dir / "visual-regression.md",
        regression,
    )


def validate_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Journey manifest must be a JSON object")
    raw = payload.get("checkpoints", [])
    if not isinstance(raw, list):
        raise ValueError("Journey checkpoints must be an array")

    seen: set[str] = set()
    checkpoints = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Checkpoint {index} must be an object")
        name = str(item.get("name", "")).strip()
        flow = str(item.get("flow", "")).strip()
        if not SAFE_NAME.fullmatch(name):
            raise ValueError(f"Invalid checkpoint name: {name!r}")
        if name in {"launch", "final"}:
            raise ValueError(f"Reserved checkpoint name: {name}")
        if name in seen:
            raise ValueError(f"Duplicate checkpoint name: {name}")
        if not flow:
            raise ValueError(f"Checkpoint {name} requires a flow")
        flow_path = Path(flow)
        if flow_path.is_absolute() or ".." in flow_path.parts:
            raise ValueError(f"Checkpoint {name} has unsafe flow path")
        seen.add(name)
        checkpoints.append({"name": name, "flow": flow})

    return {"schema_version": 1, "checkpoints": checkpoints}


def self_test() -> None:
    import tempfile
    import struct
    import zlib

    def png(path: Path, seed: int) -> None:
        width, height = 64, 96
        signature = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(kind)
            crc = zlib.crc32(data, crc) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

        rows = []
        for y in range(height):
            row = bytearray()
            for x in range(width):
                row.extend(((x + seed) % 256, (y + seed) % 256, (x + y + seed) % 256))
            rows.append(b"\x00" + bytes(row))
        path.write_bytes(
            signature
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows)))
            + chunk(b"IEND", b"")
        )

    xml = (
        '<hierarchy><node package="com.example.app" class="android.widget.Button" '
        'text="Continue" content-desc="" clickable="true" enabled="true" '
        'bounds="[10,10][60,70]"/></hierarchy>'
    )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        current = root / "current"
        baseline = root / "baseline"
        for parent in (current, baseline):
            for name in ("launch", "final"):
                d = parent / name
                d.mkdir(parents=True)
                png(d / "screenshot.png", 10)
                (d / "window.xml").write_text(xml, encoding="utf-8")

        config = visual_policy.validate_config(
            {
                "defaults": {"profile": "strict"},
                "checkpoints": {"final": {"profile": "dynamic"}},
            }
        )
        report = evaluate(current, baseline, "com.example.app", config)
        assert report["result"] == "PASS"
        assert report["checkpoint_count"] == 2
        final = next(x for x in report["checkpoints"] if x["name"] == "final")
        assert final["visual_regression"]["policy"]["profile"] == "dynamic"
        assert (current / "final" / "visual-diff-heatmap.png").is_file()

        first_run = evaluate(current, None, "com.example.app")
        compat = root / "compat-first-run"
        write_compat_reports(compat, first_run)
        assert (compat / "visual-qa.json").is_file()
        assert "NO_BASELINE" in (compat / "visual-regression.md").read_text(
            encoding="utf-8"
        )

        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "checkpoints": [
                        {"name": "settings", "flow": ".maestro/settings.yaml"},
                        {"name": "dialog", "flow": ".maestro/dialog.yaml"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        parsed = validate_manifest(manifest)
        assert len(parsed["checkpoints"]) == 2

    print("AppLab Multi-Screen Visual Journey self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-root")
    parser.add_argument("--baseline-root")
    parser.add_argument("--package-id", default="")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--compat-report-dir")
    parser.add_argument("--visual-config")
    parser.add_argument("--validate-manifest")
    parser.add_argument("--normalized-manifest")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.validate_manifest:
        payload = validate_manifest(Path(args.validate_manifest))
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.normalized_manifest:
            Path(args.normalized_manifest).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0

    if not args.current_root:
        raise SystemExit("--current-root is required")

    config = visual_policy.load_config(
        Path(args.visual_config) if args.visual_config else None
    )
    report = evaluate(
        Path(args.current_root),
        Path(args.baseline_root) if args.baseline_root else None,
        args.package_id.strip(),
        config,
    )

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    else:
        print(json.dumps(report, indent=2, sort_keys=True))

    if args.output_md:
        write_markdown(Path(args.output_md), report)
    if args.compat_report_dir:
        write_compat_reports(Path(args.compat_report_dir), report)

    print(f"AppLab Multi-Screen Visual Journey: {report['result']}")
    return 2 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"AppLab Multi-Screen Visual Journey failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
