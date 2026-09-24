#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


BOUNDS_RE = re.compile(r"\[(\-?\d+),(\-?\d+)\]\[(\-?\d+),(\-?\d+)\]")
CRASH_TEXT = (
    "isn't responding",
    "is not responding",
    "keeps stopping",
    "has stopped",
    "close app",
)
WARNING_TEXT = (
    "allow ",
    "while using the app",
    "only this time",
)


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    evidence: dict[str, Any]


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_stats(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Screenshot is not a PNG file.")

    offset = 8
    width = height = color_type = bit_depth = interlace = None
    idat = bytearray()

    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:offset + 8 + length]
        offset += 12 + length

        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", data
            )
        elif kind == b"IDAT":
            idat.extend(data)
        elif kind == b"IEND":
            break

    if not width or not height:
        raise ValueError("PNG IHDR is missing.")
    if bit_depth != 8:
        raise ValueError(f"Unsupported PNG bit depth: {bit_depth}")
    if interlace != 0:
        raise ValueError("Interlaced PNG screenshots are not supported.")

    channels_by_type = {0: 1, 2: 3, 4: 2, 6: 4}
    channels = channels_by_type.get(color_type)
    if channels is None:
        raise ValueError(f"Unsupported PNG color type: {color_type}")

    decoded = zlib.decompress(bytes(idat))
    row_bytes = width * channels
    expected = height * (row_bytes + 1)
    if len(decoded) < expected:
        raise ValueError("PNG pixel payload is truncated.")

    previous = bytearray(row_bytes)
    position = 0
    stride = max(1, int(math.sqrt((width * height) / 25000)))
    lum_values: list[float] = []
    quantized: set[tuple[int, int, int]] = set()
    sampled = 0

    for y in range(height):
        filter_type = decoded[position]
        position += 1
        source = decoded[position:position + row_bytes]
        position += row_bytes
        row = bytearray(row_bytes)

        for i, value in enumerate(source):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0

            if filter_type == 0:
                recon = value
            elif filter_type == 1:
                recon = (value + left) & 0xFF
            elif filter_type == 2:
                recon = (value + up) & 0xFF
            elif filter_type == 3:
                recon = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                recon = (value + paeth(left, up, up_left)) & 0xFF
            else:
                raise ValueError(f"Unsupported PNG filter: {filter_type}")
            row[i] = recon

        if y % stride == 0:
            for x in range(0, width, stride):
                base = x * channels
                if color_type in (0, 4):
                    r = g = b = row[base]
                else:
                    r, g, b = row[base:base + 3]

                lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                lum_values.append(lum)
                quantized.add((r >> 4, g >> 4, b >> 4))
                sampled += 1

        previous = row

    if not lum_values:
        raise ValueError("PNG contains no sampled pixels.")

    mean = sum(lum_values) / len(lum_values)
    variance = sum((value - mean) ** 2 for value in lum_values) / len(lum_values)
    stddev = math.sqrt(variance)

    return {
        "width": width,
        "height": height,
        "sample_stride": stride,
        "sampled_pixels": sampled,
        "luminance_mean": round(mean, 3),
        "luminance_stddev": round(stddev, 3),
        "quantized_color_count": len(quantized),
    }


def parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
    match = BOUNDS_RE.fullmatch(raw.strip())
    if not match:
        return None
    return tuple(int(value) for value in match.groups())


def analyze_ui(
    path: Path,
    width: int,
    height: int,
    package_id: str,
) -> tuple[dict[str, Any], list[Finding]]:
    findings: list[Finding] = []
    root = ET.parse(path).getroot()
    nodes = list(root.iter("node"))

    text_nodes = 0
    clickable_nodes = 0
    enabled_clickables = 0
    target_package_nodes = 0
    packages: dict[str, int] = {}
    tiny_targets: list[dict[str, Any]] = []
    outside_targets: list[dict[str, Any]] = []
    partial_targets: list[dict[str, Any]] = []
    screen_text: list[str] = []

    for node in nodes:
        attrs = node.attrib
        text = (attrs.get("text", "") + " " + attrs.get("content-desc", "")).strip()
        if text:
            text_nodes += 1
            screen_text.append(text)

        package = attrs.get("package", "").strip()
        if package:
            packages[package] = packages.get(package, 0) + 1
            if package == package_id:
                target_package_nodes += 1

        clickable = attrs.get("clickable") == "true"
        enabled = attrs.get("enabled", "true") == "true"
        class_name = attrs.get("class", "")
        interactive = clickable or attrs.get("checkable") == "true" or any(
            token in class_name
            for token in ("Button", "EditText", "Switch", "CheckBox", "RadioButton")
        )
        if clickable:
            clickable_nodes += 1
        if interactive and enabled:
            enabled_clickables += 1

        bounds = parse_bounds(attrs.get("bounds", ""))
        if not interactive or not enabled or bounds is None:
            continue

        x1, y1, x2, y2 = bounds
        w = max(0, x2 - x1)
        h = max(0, y2 - y1)
        item = {
            "class": class_name,
            "text": text[:120],
            "bounds": [x1, y1, x2, y2],
            "width": w,
            "height": h,
        }

        fully_outside = x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height
        partially_outside = (
            x1 < 0 or y1 < 0 or x2 > width or y2 > height
        )

        if fully_outside or w == 0 or h == 0:
            outside_targets.append(item)
        elif partially_outside:
            partial_targets.append(item)

        if w < 32 or h < 32:
            tiny_targets.append(item)

    joined_text = " ".join(screen_text).lower()
    crash_matches = [pattern for pattern in CRASH_TEXT if pattern in joined_text]
    warning_matches = [pattern for pattern in WARNING_TEXT if pattern in joined_text]

    if crash_matches:
        findings.append(
            Finding(
                "error",
                "blocking_crash_dialog",
                "Android crash/ANR dialog is visible over the app.",
                {"matched_text": crash_matches},
            )
        )

    if warning_matches and target_package_nodes == 0:
        findings.append(
            Finding(
                "warning",
                "permission_or_system_dialog",
                "A system/permission dialog appears to be blocking the target UI.",
                {"matched_text": warning_matches},
            )
        )

    if package_id and target_package_nodes == 0 and nodes:
        dominant = max(packages.items(), key=lambda item: item[1])[0] if packages else ""
        findings.append(
            Finding(
                "error",
                "target_not_foreground",
                "The UI hierarchy does not contain nodes from the target package.",
                {
                    "package_id": package_id,
                    "dominant_package": dominant,
                    "packages": packages,
                },
            )
        )

    if outside_targets:
        findings.append(
            Finding(
                "error",
                "invalid_interactive_bounds",
                "Enabled interactive controls have zero-size or fully off-screen bounds.",
                {"count": len(outside_targets), "examples": outside_targets[:8]},
            )
        )

    if partial_targets:
        findings.append(
            Finding(
                "warning",
                "partially_offscreen_controls",
                "Some enabled controls extend outside the visible screen.",
                {"count": len(partial_targets), "examples": partial_targets[:8]},
            )
        )

    if tiny_targets:
        findings.append(
            Finding(
                "warning",
                "small_touch_targets",
                "Some enabled controls are smaller than 32 px on at least one axis.",
                {"count": len(tiny_targets), "examples": tiny_targets[:8]},
            )
        )

    stats = {
        "node_count": len(nodes),
        "text_node_count": text_nodes,
        "clickable_node_count": clickable_nodes,
        "enabled_interactive_count": enabled_clickables,
        "target_package_node_count": target_package_nodes,
        "packages": packages,
    }
    return stats, findings


def evaluate(
    screenshot: Path,
    ui_hierarchy: Path,
    package_id: str,
) -> dict[str, Any]:
    screenshot_stats = decode_png_stats(screenshot)
    ui_stats, findings = analyze_ui(
        ui_hierarchy,
        screenshot_stats["width"],
        screenshot_stats["height"],
        package_id,
    )

    stddev = float(screenshot_stats["luminance_stddev"])
    colors = int(screenshot_stats["quantized_color_count"])
    mean = float(screenshot_stats["luminance_mean"])
    nearly_uniform = stddev < 2.5 and colors <= 4
    extreme_uniform = stddev < 4.0 and (mean < 4.0 or mean > 251.0)

    if nearly_uniform or extreme_uniform:
        findings.append(
            Finding(
                "error",
                "near_uniform_screenshot",
                "The rendered screen is almost uniform, consistent with a blank/black/white UI.",
                {
                    "luminance_mean": mean,
                    "luminance_stddev": stddev,
                    "quantized_color_count": colors,
                },
            )
        )
    elif (
        ui_stats["node_count"] <= 3
        and ui_stats["text_node_count"] == 0
        and ui_stats["enabled_interactive_count"] == 0
        and stddev < 8.0
    ):
        findings.append(
            Finding(
                "error",
                "empty_visual_tree",
                "The screenshot is low-detail and the UI hierarchy contains almost no visible content.",
                {
                    "node_count": ui_stats["node_count"],
                    "luminance_stddev": stddev,
                },
            )
        )

    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")

    return {
        "schema_version": 1,
        "visual_qa_version": "0.6.0",
        "result": result,
        "errors": len(errors),
        "warnings": len(warnings),
        "screenshot": screenshot.name,
        "ui_hierarchy": ui_hierarchy.name,
        "package_id": package_id,
        "screenshot_stats": screenshot_stats,
        "ui_stats": ui_stats,
        "findings": [asdict(finding) for finding in findings],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# AppLab Smart Visual QA",
        "",
        f"- Result: **{report['result']}**",
        f"- Errors: {report['errors']}",
        f"- Warnings: {report['warnings']}",
        f"- Screenshot: `{report['screenshot']}`",
        f"- UI hierarchy: `{report['ui_hierarchy']}`",
        f"- Package: `{report['package_id']}`",
        "",
        "## Render statistics",
        "",
        f"- Size: {report['screenshot_stats']['width']}x{report['screenshot_stats']['height']}",
        f"- Luminance mean: {report['screenshot_stats']['luminance_mean']}",
        f"- Luminance stddev: {report['screenshot_stats']['luminance_stddev']}",
        f"- Quantized colors: {report['screenshot_stats']['quantized_color_count']}",
        f"- UI nodes: {report['ui_stats']['node_count']}",
        f"- Target-package nodes: {report['ui_stats']['target_package_node_count']}",
        "",
    ]

    if report["findings"]:
        lines.extend(["## Findings", ""])
        for finding in report["findings"]:
            lines.append(
                f"- **{finding['severity'].upper()} — {finding['code']}**: "
                f"{finding['message']}"
            )
    else:
        lines.extend(["## Findings", "", "- No visual QA anomalies detected."])

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    import tempfile

    def png_bytes(width: int, height: int, pixel: tuple[int, int, int]) -> bytes:
        signature = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(kind)
            crc = zlib.crc32(data, crc) & 0xFFFFFFFF
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", crc)
            )

        row = bytes(pixel) * width
        payload = b"".join(b"\x00" + row for _ in range(height))
        return (
            signature
            + chunk(b"IHDR", ihdr_data)
            + chunk(b"IDAT", zlib.compress(payload))
            + chunk(b"IEND", b"")
        )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        shot = root / "screen.png"
        shot.write_bytes(png_bytes(100, 200, (255, 255, 255)))
        xml = root / "window.xml"
        xml.write_text(
            '<hierarchy><node package="com.example.app" class="android.view.View" '
            'text="" content-desc="" clickable="false" enabled="true" '
            'bounds="[0,0][100,200]"/></hierarchy>',
            encoding="utf-8",
        )
        report = evaluate(shot, xml, "com.example.app")
        assert report["result"] == "FAIL"
        assert any(
            item["code"] == "near_uniform_screenshot"
            for item in report["findings"]
        )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        shot = root / "screen.png"
        # Horizontal RGB gradient should never look blank.
        width, height = 128, 128
        signature = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(kind)
            crc = zlib.crc32(data, crc) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

        rows = []
        for _ in range(height):
            row = bytearray()
            for x in range(width):
                row.extend((x * 2 % 256, (255 - x) % 256, (x * 3) % 256))
            rows.append(b"\x00" + bytes(row))
        shot.write_bytes(
            signature
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"".join(rows)))
            + chunk(b"IEND", b"")
        )
        xml = root / "window.xml"
        xml.write_text(
            '<hierarchy><node package="com.example.app" class="android.widget.Button" '
            'text="Continue" content-desc="" clickable="true" enabled="true" '
            'bounds="[10,10][100,80]"/></hierarchy>',
            encoding="utf-8",
        )
        report = evaluate(shot, xml, "com.example.app")
        assert report["result"] == "PASS"

    print("AppLab Smart Visual QA self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot")
    parser.add_argument("--ui-hierarchy")
    parser.add_argument("--package-id", default="")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.screenshot or not args.ui_hierarchy:
        raise SystemExit("--screenshot and --ui-hierarchy are required")

    report = evaluate(
        Path(args.screenshot),
        Path(args.ui_hierarchy),
        args.package_id.strip(),
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

    print(f"AppLab Smart Visual QA: {report['result']}")
    return 2 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"AppLab Smart Visual QA failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
