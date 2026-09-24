#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


BOUNDS_RE = re.compile(r"\[(\-?\d+),(\-?\d+)\]\[(\-?\d+),(\-?\d+)\]")
DYNAMIC_VIEW_TOKENS = (
    "MapView",
    "SurfaceView",
    "TextureView",
    "WebView",
    "PreviewView",
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


def decode_png_rgb(path: Path) -> tuple[int, int, list[bytes]]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG file")

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
        raise ValueError("PNG IHDR is missing")
    if bit_depth != 8 or interlace != 0:
        raise ValueError("Only non-interlaced 8-bit PNG screenshots are supported")

    channels_by_type = {0: 1, 2: 3, 4: 2, 6: 4}
    channels = channels_by_type.get(color_type)
    if channels is None:
        raise ValueError(f"Unsupported PNG color type: {color_type}")

    decoded = zlib.decompress(bytes(idat))
    row_bytes = width * channels
    previous = bytearray(row_bytes)
    position = 0
    rows: list[bytes] = []

    for _ in range(height):
        if position >= len(decoded):
            raise ValueError("PNG pixel payload is truncated")
        filter_type = decoded[position]
        position += 1
        source = decoded[position:position + row_bytes]
        position += row_bytes
        if len(source) != row_bytes:
            raise ValueError("PNG row is truncated")

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

        rgb = bytearray(width * 3)
        for x in range(width):
            source_index = x * channels
            target_index = x * 3
            if color_type in (0, 4):
                value = row[source_index]
                rgb[target_index:target_index + 3] = bytes((value, value, value))
            else:
                rgb[target_index:target_index + 3] = row[source_index:source_index + 3]
        rows.append(bytes(rgb))
        previous = row

    return width, height, rows


def sample_grid(
    width: int,
    height: int,
    rows: list[bytes],
    grid_w: int = 32,
    grid_h: int = 56,
) -> list[tuple[int, int, int]]:
    # Ignore most status/navigation-bar variance and compare app content.
    top = int(height * 0.05)
    bottom = max(top + 1, int(height * 0.95))
    usable_h = max(1, bottom - top)

    result: list[tuple[int, int, int]] = []
    for gy in range(grid_h):
        y = top + min(
            usable_h - 1,
            int((gy + 0.5) * usable_h / grid_h),
        )
        row = rows[y]
        for gx in range(grid_w):
            x = min(width - 1, int((gx + 0.5) * width / grid_w))
            base = x * 3
            result.append((row[base], row[base + 1], row[base + 2]))
    return result


def _masked(x: float, y: float, masks: list[dict[str, float]]) -> bool:
    for mask in masks:
        if (
            mask["x"] <= x <= mask["x"] + mask["width"]
            and mask["y"] <= y <= mask["y"] + mask["height"]
        ):
            return True
    return False


def _write_heatmap(
    path: Path,
    values: list[float | None],
    grid_w: int,
    grid_h: int,
    scale: int = 8,
) -> None:
    width = grid_w * scale
    height = grid_h * scale
    rows: list[bytes] = []
    for gy in range(grid_h):
        source_row = bytearray()
        for gx in range(grid_w):
            value = values[gy * grid_w + gx]
            if value is None:
                pixel = (32, 32, 32)
            else:
                intensity = max(0, min(255, int(value * 4.0)))
                pixel = (intensity, max(0, 180 - intensity // 2), 0)
            source_row.extend(pixel * scale)
        encoded = b"\x00" + bytes(source_row)
        rows.extend(encoded for _ in range(scale))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind)
        crc = zlib.crc32(data, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        signature
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def dynamic_masks_from_ui(
    path: Path,
    width: int,
    height: int,
) -> list[dict[str, float]]:
    if width <= 0 or height <= 0:
        return []
    root = ET.parse(path).getroot()
    masks: list[dict[str, float]] = []
    for node in root.iter("node"):
        class_name = node.attrib.get("class", "")
        if not any(token in class_name for token in DYNAMIC_VIEW_TOKENS):
            continue
        match = BOUNDS_RE.fullmatch(node.attrib.get("bounds", "").strip())
        if not match:
            continue
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        x1 = max(0, min(width, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height, y1))
        y2 = max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        masks.append(
            {
                "x": x1 / width,
                "y": y1 / height,
                "width": (x2 - x1) / width,
                "height": (y2 - y1) / height,
            }
        )
    return masks


def image_difference(
    baseline_path: Path,
    current_path: Path,
    masks: list[dict[str, float]] | None = None,
    heatmap_path: Path | None = None,
) -> dict[str, Any]:
    bw, bh, brows = decode_png_rgb(baseline_path)
    cw, ch, crows = decode_png_rgb(current_path)

    grid_w, grid_h = 32, 56
    baseline = sample_grid(bw, bh, brows, grid_w, grid_h)
    current = sample_grid(cw, ch, crows, grid_w, grid_h)
    if len(baseline) != len(current):
        raise ValueError("Normalized image grids differ in size")

    masks = masks or []
    diffs: list[float] = []
    weighted_diffs: list[float] = []
    heatmap: list[float | None] = []
    changed_20 = 0
    changed_35 = 0
    changed_60 = 0
    masked = 0

    for index, (before, after) in enumerate(zip(baseline, current)):
        gx = index % grid_w
        gy = index // grid_w
        x_norm = (gx + 0.5) / grid_w
        y_norm = 0.05 + ((gy + 0.5) / grid_h) * 0.90
        if _masked(x_norm, y_norm, masks):
            masked += 1
            heatmap.append(None)
            continue

        channel = [abs(a - b) for a, b in zip(before, after)]
        diff = sum(channel) / 3.0
        weighted = (
            0.2126 * channel[0]
            + 0.7152 * channel[1]
            + 0.0722 * channel[2]
        )
        diffs.append(diff)
        weighted_diffs.append(weighted)
        heatmap.append(weighted)
        if diff >= 20:
            changed_20 += 1
        if diff >= 35:
            changed_35 += 1
        if diff >= 60:
            changed_60 += 1

    count = len(diffs)
    if count <= 0:
        mean = rms = weighted_mean = 0.0
    else:
        mean = sum(diffs) / count
        rms = math.sqrt(sum(value * value for value in diffs) / count)
        weighted_mean = sum(weighted_diffs) / count

    if heatmap_path is not None:
        _write_heatmap(heatmap_path, heatmap, grid_w, grid_h)

    denominator = max(1, count)
    total_cells = len(baseline)
    return {
        "baseline_size": [bw, bh],
        "current_size": [cw, ch],
        "grid_cells": total_cells,
        "compared_cells": count,
        "masked_cells": masked,
        "masked_ratio": round(masked / max(1, total_cells), 4),
        "mean_abs_rgb_diff": round(mean, 3),
        "mean_perceptual_diff": round(weighted_mean, 3),
        "rms_rgb_diff": round(rms, 3),
        "changed_ratio_20": round(changed_20 / denominator, 4),
        "changed_ratio_35": round(changed_35 / denominator, 4),
        "changed_ratio_60": round(changed_60 / denominator, 4),
        "heatmap": str(heatmap_path) if heatmap_path is not None else "",
    }

def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def ui_signature(
    path: Path,
    package_id: str,
    ignore_text_regex: list[str] | None = None,
) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    ignored = [re.compile(pattern) for pattern in (ignore_text_regex or [])]
    nodes = list(root.iter("node"))

    target_nodes = []
    texts: set[str] = set()
    interactive = 0
    visible_bounds = 0

    for node in nodes:
        attrs = node.attrib
        package = attrs.get("package", "").strip()
        if package_id and package != package_id:
            continue
        target_nodes.append(node)

        value = normalize_text(
            (attrs.get("text", "") + " " + attrs.get("content-desc", "")).strip()
        )
        if value and not any(pattern.search(value) for pattern in ignored):
            texts.add(value[:160])

        class_name = attrs.get("class", "")
        enabled = attrs.get("enabled", "true") == "true"
        clickable = attrs.get("clickable") == "true"
        if enabled and (
            clickable
            or attrs.get("checkable") == "true"
            or any(
                token in class_name
                for token in ("Button", "EditText", "Switch", "CheckBox", "RadioButton")
            )
        ):
            interactive += 1

        match = BOUNDS_RE.fullmatch(attrs.get("bounds", "").strip())
        if match:
            x1, y1, x2, y2 = (int(v) for v in match.groups())
            if x2 > x1 and y2 > y1:
                visible_bounds += 1

    return {
        "node_count": len(target_nodes),
        "interactive_count": interactive,
        "visible_bounds_count": visible_bounds,
        "texts": sorted(texts),
    }


def ui_difference(
    baseline_path: Path,
    current_path: Path,
    package_id: str,
    ignore_text_regex: list[str] | None = None,
) -> dict[str, Any]:
    before = ui_signature(baseline_path, package_id, ignore_text_regex)
    after = ui_signature(current_path, package_id, ignore_text_regex)

    before_text = set(before["texts"])
    after_text = set(after["texts"])
    union = before_text | after_text
    intersection = before_text & after_text
    similarity = 1.0 if not union else len(intersection) / len(union)

    before_nodes = max(1, int(before["node_count"]))
    node_delta_ratio = abs(
        int(after["node_count"]) - int(before["node_count"])
    ) / before_nodes

    before_interactive = max(1, int(before["interactive_count"]))
    interactive_delta_ratio = abs(
        int(after["interactive_count"]) - int(before["interactive_count"])
    ) / before_interactive

    return {
        "baseline": before,
        "current": after,
        "text_jaccard_similarity": round(similarity, 4),
        "node_delta_ratio": round(node_delta_ratio, 4),
        "interactive_delta_ratio": round(interactive_delta_ratio, 4),
    }


def load_metadata(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def evaluate(
    baseline_screenshot: Path,
    baseline_ui: Path,
    current_screenshot: Path,
    current_ui: Path,
    package_id: str,
    metadata: dict[str, Any],
    policy: dict[str, Any] | None = None,
    heatmap_path: Path | None = None,
) -> dict[str, Any]:
    policy = policy or {
        "profile": "standard",
        "auto_mask_dynamic_views": True,
        "masks": [],
        "ignore_text_regex": [],
        "thresholds": {
            "error_mean": 45.0,
            "error_ratio": 0.55,
            "warn_mean": 20.0,
            "warn_ratio": 0.30,
            "error_text_similarity": 0.45,
            "error_node_delta": 0.60,
            "error_interactive_delta": 0.75,
            "warn_text_similarity": 0.70,
            "warn_node_delta": 0.35,
            "warn_interactive_delta": 0.50,
        },
    }
    masks = list(policy.get("masks", []))
    if policy.get("auto_mask_dynamic_views", True):
        bw, bh, _ = decode_png_rgb(baseline_screenshot)
        cw, ch, _ = decode_png_rgb(current_screenshot)
        masks.extend(dynamic_masks_from_ui(baseline_ui, bw, bh))
        masks.extend(dynamic_masks_from_ui(current_ui, cw, ch))

    image = image_difference(
        baseline_screenshot,
        current_screenshot,
        masks,
        heatmap_path,
    )
    ui = ui_difference(
        baseline_ui,
        current_ui,
        package_id,
        policy.get("ignore_text_regex", []),
    )
    thresholds = policy["thresholds"]
    findings: list[Finding] = []

    severe_image = (
        image["mean_abs_rgb_diff"] >= thresholds["error_mean"]
        and image["changed_ratio_35"] >= thresholds["error_ratio"]
    )
    severe_structure = (
        ui["text_jaccard_similarity"] < thresholds["error_text_similarity"]
        or ui["node_delta_ratio"] >= thresholds["error_node_delta"]
        or ui["interactive_delta_ratio"] >= thresholds["error_interactive_delta"]
    )

    moderate_image = (
        image["mean_abs_rgb_diff"] >= thresholds["warn_mean"]
        or image["changed_ratio_35"] >= thresholds["warn_ratio"]
    )
    moderate_structure = (
        ui["text_jaccard_similarity"] < thresholds["warn_text_similarity"]
        or ui["node_delta_ratio"] >= thresholds["warn_node_delta"]
        or ui["interactive_delta_ratio"] >= thresholds["warn_interactive_delta"]
    )

    if image["masked_ratio"] >= 0.90:
        findings.append(
            Finding(
                "warning",
                "excessive_visual_mask",
                "More than 90% of the normalized screen is excluded from image comparison.",
                {"masked_ratio": image["masked_ratio"]},
            )
        )

    if severe_image and severe_structure:
        findings.append(
            Finding(
                "error",
                "major_visual_regression",
                "The screen changed substantially from the last passing baseline and the UI structure changed with it.",
                {
                    "mean_abs_rgb_diff": image["mean_abs_rgb_diff"],
                    "mean_perceptual_diff": image["mean_perceptual_diff"],
                    "changed_ratio_35": image["changed_ratio_35"],
                    "text_jaccard_similarity": ui["text_jaccard_similarity"],
                    "node_delta_ratio": ui["node_delta_ratio"],
                    "interactive_delta_ratio": ui["interactive_delta_ratio"],
                },
            )
        )
    elif moderate_image and moderate_structure:
        findings.append(
            Finding(
                "warning",
                "possible_visual_regression",
                "The current screen differs materially from the last passing baseline.",
                {
                    "mean_abs_rgb_diff": image["mean_abs_rgb_diff"],
                    "mean_perceptual_diff": image["mean_perceptual_diff"],
                    "changed_ratio_35": image["changed_ratio_35"],
                    "text_jaccard_similarity": ui["text_jaccard_similarity"],
                    "node_delta_ratio": ui["node_delta_ratio"],
                },
            )
        )
    elif moderate_image:
        findings.append(
            Finding(
                "warning",
                "visual_change",
                "The screenshot changed noticeably, but the UI structure remains broadly consistent.",
                {
                    "mean_abs_rgb_diff": image["mean_abs_rgb_diff"],
                    "mean_perceptual_diff": image["mean_perceptual_diff"],
                    "changed_ratio_35": image["changed_ratio_35"],
                },
            )
        )
    elif moderate_structure:
        findings.append(
            Finding(
                "warning",
                "ui_structure_change",
                "The UI hierarchy changed noticeably while the rendered screen stayed broadly similar.",
                {
                    "text_jaccard_similarity": ui["text_jaccard_similarity"],
                    "node_delta_ratio": ui["node_delta_ratio"],
                    "interactive_delta_ratio": ui["interactive_delta_ratio"],
                },
            )
        )

    errors = [item for item in findings if item.severity == "error"]
    warnings = [item for item in findings if item.severity == "warning"]
    result = "FAIL" if errors else ("WARN" if warnings else "PASS")

    return {
        "schema_version": 1,
        "visual_regression_version": "0.6.5",
        "result": result,
        "errors": len(errors),
        "warnings": len(warnings),
        "package_id": package_id,
        "baseline_metadata": metadata,
        "policy": {
            "profile": policy.get("profile", "standard"),
            "auto_mask_dynamic_views": policy.get(
                "auto_mask_dynamic_views", True
            ),
            "manual_mask_count": len(policy.get("masks", [])),
            "effective_mask_count": len(masks),
            "ignore_text_regex": policy.get("ignore_text_regex", []),
            "thresholds": thresholds,
        },
        "image_difference": image,
        "ui_difference": ui,
        "findings": [asdict(item) for item in findings],
    }

def write_markdown(path: Path, report: dict[str, Any]) -> None:
    baseline = report.get("baseline_metadata", {})
    if report.get("result") == "NO_BASELINE":
        path.write_text(
            "# AppLab Visual Regression\n\n"
            "- Result: **NO_BASELINE**\n"
            "- No previous passing checkpoint exists yet.\n"
            "- The current full-PASS run may become the first baseline.\n",
            encoding="utf-8",
        )
        return

    lines = [
        "# AppLab Visual Regression",
        "",
        f"- Result: **{report['result']}**",
        f"- Errors: {report['errors']}",
        f"- Warnings: {report['warnings']}",
        f"- Baseline SHA: `{baseline.get('resolved_sha', 'unknown')}`",
        f"- Baseline run: `{baseline.get('workflow_run_id', 'unknown')}`",
        f"- Profile: `{report.get('policy', {}).get('profile', 'standard')}`",
        "",
        "## Image comparison",
        "",
        f"- Mean RGB difference: {report['image_difference']['mean_abs_rgb_diff']}",
        f"- Mean perceptual difference: {report['image_difference'].get('mean_perceptual_diff', 0)}",
        f"- RMS RGB difference: {report['image_difference']['rms_rgb_diff']}",
        f"- Changed cells >=35: {report['image_difference']['changed_ratio_35']:.1%}",
        f"- Masked cells: {report['image_difference'].get('masked_ratio', 0):.1%}",
        "",
        "## UI comparison",
        "",
        f"- Text similarity: {report['ui_difference']['text_jaccard_similarity']:.1%}",
        f"- Node-count delta: {report['ui_difference']['node_delta_ratio']:.1%}",
        f"- Interactive-count delta: {report['ui_difference']['interactive_delta_ratio']:.1%}",
        "",
        "## Findings",
        "",
    ]

    if report["findings"]:
        for finding in report["findings"]:
            lines.append(
                f"- **{finding['severity'].upper()} — {finding['code']}**: "
                f"{finding['message']}"
            )
    else:
        lines.append("- No visual regression detected.")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    import tempfile

    def png_gradient(path: Path, offset: int = 0) -> None:
        width, height = 96, 160
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
                row.extend(
                    (
                        (x * 2 + offset) % 256,
                        (y + offset) % 256,
                        (x + y + offset) % 256,
                    )
                )
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
        'bounds="[10,10][90,80]"/></hierarchy>'
    )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        before = root / "before.png"
        after = root / "after.png"
        before_xml = root / "before.xml"
        after_xml = root / "after.xml"
        png_gradient(before, 0)
        png_gradient(after, 0)
        before_xml.write_text(xml, encoding="utf-8")
        after_xml.write_text(xml, encoding="utf-8")

        report = evaluate(
            before,
            before_xml,
            after,
            after_xml,
            "com.example.app",
            {},
        )
        assert report["result"] == "PASS"

        png_gradient(after, 140)
        after_xml.write_text(
            '<hierarchy><node package="com.example.app" class="android.widget.TextView" '
            'text="Completely different screen" content-desc="" clickable="false" '
            'enabled="true" bounds="[0,0][96,160]"/></hierarchy>',
            encoding="utf-8",
        )
        report = evaluate(
            before,
            before_xml,
            after,
            after_xml,
            "com.example.app",
            {},
        )
        assert report["result"] in {"WARN", "FAIL"}

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        before = root / "before.png"
        after = root / "after.png"
        heatmap = root / "heatmap.png"
        width, height = 96, 160
        signature = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

        def chunk(kind: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(kind)
            crc = zlib.crc32(data, crc) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

        def write_half_changed(path: Path, changed: bool) -> None:
            rows = []
            for y in range(height):
                row = bytearray()
                for x in range(width):
                    if changed and x < width // 2:
                        row.extend((250, 20, 20))
                    else:
                        row.extend((30 + x % 80, 40 + y % 80, 70))
                rows.append(b"\x00" + bytes(row))
            path.write_bytes(
                signature
                + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(b"".join(rows)))
                + chunk(b"IEND", b"")
            )

        write_half_changed(before, False)
        write_half_changed(after, True)
        raw_diff = image_difference(before, after)
        masked_diff = image_difference(
            before,
            after,
            masks=[{"x": 0.0, "y": 0.0, "width": 0.5, "height": 1.0}],
            heatmap_path=heatmap,
        )
        assert raw_diff["mean_abs_rgb_diff"] > 20
        assert masked_diff["mean_abs_rgb_diff"] < 0.1
        assert masked_diff["masked_ratio"] > 0.45
        assert heatmap.is_file() and heatmap.stat().st_size > 0

        baseline_ui = root / "baseline.xml"
        current_ui = root / "current.xml"
        baseline_ui.write_text(
            '<hierarchy><node package="com.example.app" class="android.widget.TextView" '
            'text="Time 12:34" bounds="[0,0][80,40]"/></hierarchy>',
            encoding="utf-8",
        )
        current_ui.write_text(
            '<hierarchy><node package="com.example.app" class="android.widget.TextView" '
            'text="Time 12:35" bounds="[0,0][80,40]"/></hierarchy>',
            encoding="utf-8",
        )
        ignored = ui_difference(
            baseline_ui,
            current_ui,
            "com.example.app",
            [r"^time \\d{2}:\\d{2}$"],
        )
        assert ignored["text_jaccard_similarity"] == 1.0

    print("AppLab Visual Regression self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-screenshot")
    parser.add_argument("--baseline-ui")
    parser.add_argument("--baseline-metadata")
    parser.add_argument("--current-screenshot")
    parser.add_argument("--current-ui")
    parser.add_argument("--package-id", default="")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    required = (
        args.baseline_screenshot,
        args.baseline_ui,
        args.current_screenshot,
        args.current_ui,
    )
    if not all(required):
        raise SystemExit("Baseline and current screenshot/UI paths are required")

    report = evaluate(
        Path(args.baseline_screenshot),
        Path(args.baseline_ui),
        Path(args.current_screenshot),
        Path(args.current_ui),
        args.package_id.strip(),
        load_metadata(Path(args.baseline_metadata) if args.baseline_metadata else None),
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

    print(f"AppLab Visual Regression: {report['result']}")
    return 2 if report["result"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"AppLab Visual Regression failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
