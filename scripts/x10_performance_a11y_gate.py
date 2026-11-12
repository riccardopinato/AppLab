#!/usr/bin/env python3
"""X10-030: report-only adoption of AppLab Performance Lab and Android UI hierarchy.

No benchmark runner, baseline producer, device attestation or certification authority.
The caller injects AppLab's existing regression_findings as comparator.
"""
from __future__ import annotations

import hashlib
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PACKAGE = re.compile(r"[A-Za-z][\w]*(?:\.[A-Za-z][\w]*)+\Z")
BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]\Z")
TARGET_DP = 48.0


class PerformanceAccessibilityError(ValueError):
    pass


def demand(ok: bool, code: str) -> None:
    if not ok:
        raise PerformanceAccessibilityError(code)


def _metric(sample: dict[str, Any], *keys: str) -> float:
    obj: Any = sample.get("metrics")
    for key in keys:
        obj = obj.get(key) if isinstance(obj, dict) else None
    demand(type(obj) in (float, int) and 0 <= obj < 1_000_000_000,
           "PERFORMANCE_SAMPLE_INCOMPLETE")
    return float(obj)


def _accessibility(xml: bytes, device: dict[str, Any], package: str) -> list[dict[str, Any]]:
    demand(0 < len(xml) <= 4 * 1024 * 1024 and b"<!DOCTYPE" not in xml,
           "INVALID_UI_CAPTURE")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise PerformanceAccessibilityError("INVALID_UI_HIERARCHY") from exc
    density = device["density_dpi"] / 160.0
    issues = []
    in_app = 0
    for node in root.iter("node"):
        attrs = node.attrib
        if attrs.get("package") != package:
            continue
        in_app += 1
        name = attrs.get("class", "")
        interactive = (attrs.get("clickable") == "true" or
                       attrs.get("long-clickable") == "true" or
                       attrs.get("checkable") == "true" or
                       any(t in name for t in ("Button", "EditText", "Switch", "CheckBox", "RadioButton")))
        if not interactive or attrs.get("enabled", "true") != "true":
            continue
        bounds = BOUNDS.fullmatch(attrs.get("bounds", ""))
        if bounds is None:
            issues.append({"code": "BOUNDS_UNAVAILABLE", "class": name})
            continue
        x1, y1, x2, y2 = map(int, bounds.groups())
        if (x2 <= x1 or y2 <= y1 or x1 < 0 or y1 < 0 or
                x2 > device["screen_width_px"] or y2 > device["screen_height_px"]):
            issues.append({"code": "INTERACTIVE_BOUNDS_OUTSIDE", "class": name})
            continue
        width_dp, height_dp = (x2 - x1) / density, (y2 - y1) / density
        if width_dp < TARGET_DP or height_dp < TARGET_DP:
            issues.append({"code": "TOUCH_TARGET_UNDER_48DP", "class": name,
                           "width_dp": round(width_dp, 2), "height_dp": round(height_dp, 2)})
        label = (attrs.get("content-desc", "") or attrs.get("text", "")).strip()
        if not label:
            child_label = any((c.attrib.get("text", "") or c.attrib.get("content-desc", "")).strip()
                              for c in node.iter("node") if c is not node)
            if not child_label:
                issues.append({"code": "UNLABELED_CONTROL_REVIEW", "class": name})
    demand(in_app > 0, "TARGET_APP_NOT_IN_HIERARCHY")
    return issues


def assess(request: dict[str, Any], *, hierarchy_path: Path,
           approved_baseline_lookup: Callable[[str, str, dict[str, Any]], dict[str, Any] | None],
           applab_regression_findings: Callable[[dict[str, Any], dict[str, Any] | None], list[Any]]) -> dict[str, Any]:
    demand(isinstance(request, dict) and request.get("schema_version") == 1,
           "INVALID_REQUEST")
    repo, sha, package, apk_hash = (request.get(key) for key in
                                    ("repository", "source_sha", "package_id", "apk_sha256"))
    demand(isinstance(repo, str) and re.fullmatch(r"[A-Za-z\w.-]+/[A-Za-z\w.-]+", repo) is not None
           and isinstance(sha, str) and SHA40.fullmatch(sha) is not None
           and isinstance(package, str) and PACKAGE.fullmatch(package) is not None
           and isinstance(apk_hash, str) and SHA256.fullmatch(apk_hash) is not None,
           "SOURCE_OR_ARTIFACT_IDENTITY_INVALID")
    run, device = request.get("workflow_run_id"), request.get("device")
    demand(type(run) is int and run > 0 and isinstance(device, dict) and
           isinstance(device.get("device_id"), str) and 1 <= len(device["device_id"]) <= 100
           and isinstance(device.get("model"), str) and bool(device["model"])
           and device.get("abi") in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")
           and device.get("kind") in ("emulator", "physical")
           and all(type(device.get(k)) is int and lo <= device[k] <= hi for k, lo, hi in (
               ("sdk_int", 23, 40), ("ram_mb", 256, 131072), ("density_dpi", 120, 1000),
               ("screen_width_px", 240, 8192), ("screen_height_px", 240, 8192))),
           "DEVICE_PROFILE_INVALID")
    demand(callable(approved_baseline_lookup) and callable(applab_regression_findings),
           "APP_LAB_ADAPTERS_REQUIRED")
    samples = request.get("samples")
    demand(isinstance(samples, list) and 3 <= len(samples) <= 20,
           "REPEATED_BENCHMARK_REQUIRED")
    for index, sample in enumerate(samples):
        demand(isinstance(sample, dict) and sample.get("sample_index") == index + 1
               and sample.get("repository") == repo and sample.get("source_sha") == sha
               and sample.get("apk_sha256") == apk_hash and sample.get("package_id") == package
               and sample.get("workflow_run_id") == run
               and sample.get("device_id") == device["device_id"]
               and sample.get("result") in ("PASS", "WARN"),
               "SAMPLE_SOURCE_OR_SEQUENCE_MISMATCH")
    cold = [_metric(s, "startup", "cold", "total_time_ms") for s in samples]
    memory = [_metric(s, "memory", "pss_kb") for s in samples]
    jank = [_metric(s, "gfx", "janky_percent") for s in samples]
    demand(all(0 < n <= 180_000 for n in cold)
           and all(0 < n <= 131072 * 1024 for n in memory)
           and all(0 <= n <= 100 for n in jank), "SAMPLE_VALUE_OUT_OF_RANGE")
    demand(isinstance(hierarchy_path, Path) and hierarchy_path.is_file()
           and not hierarchy_path.is_symlink(), "UI_CAPTURE_MISSING")
    raw = hierarchy_path.read_bytes()
    capture_sha = request.get("hierarchy_sha256")
    demand(isinstance(capture_sha, str) and SHA256.fullmatch(capture_sha) is not None
           and hashlib.sha256(raw).hexdigest() == capture_sha,
           "UI_CAPTURE_HASH_MISMATCH")
    issues = _accessibility(raw, device, package)
    summary = {"metrics": {"startup": {"cold": {"total_time_ms": statistics.median(cold)}},
                           "memory": {"pss_kb": statistics.median(memory)},
                           "gfx": {"janky_percent": statistics.median(jank)}}}
    baseline = approved_baseline_lookup(repo, package, device)
    regressions = []
    if baseline is not None:
        demand(isinstance(baseline, dict) and baseline.get("approved") is True
               and baseline.get("repository") == repo and baseline.get("package_id") == package
               and baseline.get("device") == device
               and isinstance(baseline.get("source_sha"), str)
               and SHA40.fullmatch(baseline["source_sha"]) is not None
               and isinstance(baseline.get("review_url"), str)
               and baseline["review_url"].startswith(f"https://github.com/{repo}/pull/")
               and isinstance(baseline.get("metrics"), dict),
               "BASELINE_NOT_APPROVED_OR_INCOMPARABLE")
        # AppLab Performance Lab skips missing baseline values; these must
        # never be silently interpreted as "no regressions".
        base_metrics = {"metrics": baseline["metrics"]}
        base_cold = _metric(base_metrics, "startup", "cold", "total_time_ms")
        base_pss = _metric(base_metrics, "memory", "pss_kb")
        base_jank = _metric(base_metrics, "gfx", "janky_percent")
        demand(0 < base_cold <= 180_000
               and 0 < base_pss <= 131072 * 1024
               and 0 <= base_jank <= 100,
               "BASELINE_MEASUREMENTS_MISSING_OR_INVALID")
        compared = applab_regression_findings(summary, baseline)
        demand(isinstance(compared, list), "COMPARATOR_RESULT_INVALID")
        regressions = [r.code for r in compared if isinstance(getattr(r, "code", None), str)]
        demand(len(regressions) == len(compared), "COMPARATOR_FINDING_MALFORMED")
    needs_review = bool(issues or regressions or baseline is None or
                        any(s["result"] != "PASS" for s in samples))
    return {
        "schema_version": 1, "record_type": "X10_PERF_A11Y_REVIEW_RECEIPT",
        "authority": "REPORT_ONLY", "state": ("HUMAN_REVIEW_REQUIRED" if needs_review
                                                else "BENCHMARK_MATCH_REPORTED"),
        "repository": repo, "source_sha": sha, "apk_sha256": apk_hash,
        "workflow_run_id": run, "package_id": package, "device": device,
        "sample_count": len(samples), "summary": summary["metrics"],
        "baseline": "MISSING" if baseline is None else "APPROVED_REFERENCE_REPORTED",
        "regression_codes": regressions, "accessibility_findings": issues,
        "low_end_profile_candidate": device["ram_mb"] <= 4096,
        "device_attested": False, "trusted_runtime_verified": False,
        "physical_device_verified": False, "consumer_certified": False,
        "independent_provenance_verified": False,
    }
