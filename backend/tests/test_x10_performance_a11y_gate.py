"""X10-030: synthetic reports; no real Android hardware or consumer certification."""
import copy
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2] / "scripts"
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("x10_performance_a11y_gate", ROOT / "x10_performance_a11y_gate.py")
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)
SHA = "a" * 40
APK = "b" * 64
REPO = "example/app"
PACKAGE = "com.example.app"


def baseline_findings(current, baseline):
    # In AppLab checkout, delegate to the actual pre-existing Performance Lab.
    source = ROOT / "performance_lab.py"
    if source.is_file():
        spec2 = importlib.util.spec_from_file_location("_x10_performance_existing_lab", source)
        app = importlib.util.module_from_spec(spec2)
        sys.modules[spec2.name] = app
        spec2.loader.exec_module(app)
        return app.regression_findings(current, baseline)
    v = current["metrics"]["startup"]["cold"]["total_time_ms"]
    old = baseline["metrics"]["startup"]["cold"]["total_time_ms"]
    return [SimpleNamespace(code="startup_regression")] if v >= old * 1.35 and v - old >= 500 else []


def setup(tmp_path, *, width=200, height=200, cold=900, density=160, label="Save"):
    device = {"device_id": "android-fixture", "model": "Synthetic phone", "abi": "arm64-v8a",
              "kind": "emulator", "sdk_int": 35, "ram_mb": 2048, "density_dpi": density,
              "screen_width_px": 1080, "screen_height_px": 2400}
    xml = ('<hierarchy><node package="' + PACKAGE + '" class="android.widget.Button" '
           'clickable="true" enabled="true" text="' + label + '" '
           'bounds="[0,0][' + str(width) + ',' + str(height) + ']"/></hierarchy>').encode()
    ui = tmp_path / "hierarchy.xml"
    ui.write_bytes(xml)
    samples = []
    for i in range(3):
        samples.append({"sample_index": i + 1, "repository": REPO, "source_sha": SHA,
                        "apk_sha256": APK, "package_id": PACKAGE, "workflow_run_id": 987,
                        "device_id": device["device_id"], "result": "PASS",
                        "metrics": {"startup": {"cold": {"total_time_ms": cold}},
                                    "memory": {"pss_kb": 200000},
                                    "gfx": {"janky_percent": 3.0}}})
    req = {"schema_version": 1, "repository": REPO, "source_sha": SHA,
           "package_id": PACKAGE, "apk_sha256": APK, "workflow_run_id": 987,
           "device": device, "samples": samples,
           "hierarchy_sha256": hashlib.sha256(xml).hexdigest()}
    baseline = {"approved": True, "repository": REPO, "package_id": PACKAGE,
                "device": copy.deepcopy(device), "source_sha": "c" * 40,
                "review_url": "https://github.com/example/app/pull/2",
                "metrics": {"startup": {"cold": {"total_time_ms": 800}},
                            "memory": {"pss_kb": 180000}, "gfx": {"janky_percent": 3}}}
    def run(reference=True):
        return gate.assess(req, hierarchy_path=ui,
                           approved_baseline_lookup=lambda *args: baseline if reference else None,
                           applab_regression_findings=baseline_findings)
    return req, baseline, ui, run


def test_real_comparator_fixtures_are_never_certified(tmp_path):
    req, base, ui, run = setup(tmp_path)
    result = run()
    assert result["state"] == "BENCHMARK_MATCH_REPORTED"
    assert result["sample_count"] == 3
    assert result["low_end_profile_candidate"] is True
    assert result["physical_device_verified"] is False
    assert result["consumer_certified"] is False


def test_no_baseline_is_not_a_pass(tmp_path):
    _, _, _, run = setup(tmp_path)
    result = run(reference=False)
    assert result["state"] == "HUMAN_REVIEW_REQUIRED"
    assert result["baseline"] == "MISSING"


def test_density_scales_touch_target_48_dp(tmp_path):
    _, _, _, run = setup(tmp_path, width=80, height=80, density=320)
    issues = run()["accessibility_findings"]
    assert any(x["code"] == "TOUCH_TARGET_UNDER_48DP" for x in issues)
    assert any(x.get("width_dp") == 40 for x in issues)


def test_label_missing_requires_review(tmp_path):
    _, _, _, run = setup(tmp_path, label="")
    assert "UNLABELED_CONTROL_REVIEW" in [x["code"] for x in run()["accessibility_findings"]]


def test_applab_baseline_regression_codes(tmp_path):
    _, _, _, run = setup(tmp_path, cold=2100)
    assert "startup_regression" in run()["regression_codes"]
    assert run()["state"] == "HUMAN_REVIEW_REQUIRED"


def test_stale_source_or_artifact_rejected(tmp_path):
    req, _, _, run = setup(tmp_path)
    req["samples"][0]["source_sha"] = "d" * 40
    with pytest.raises(gate.PerformanceAccessibilityError, match="SAMPLE_SOURCE_OR_SEQUENCE_MISMATCH"):
        run()
    req["samples"][0]["source_sha"] = SHA
    req["samples"][1]["apk_sha256"] = "0" * 64
    with pytest.raises(gate.PerformanceAccessibilityError, match="SAMPLE_SOURCE_OR_SEQUENCE_MISMATCH"):
        run()


def test_no_single_sample_and_no_duplicate_sequence(tmp_path):
    req, _, _, run = setup(tmp_path)
    req["samples"] = req["samples"][:1]
    with pytest.raises(gate.PerformanceAccessibilityError, match="REPEATED_BENCHMARK_REQUIRED"):
        run()
    req, _, _, run = setup(tmp_path)
    req["samples"][1]["sample_index"] = 1
    with pytest.raises(gate.PerformanceAccessibilityError, match="SAMPLE_SOURCE_OR_SEQUENCE_MISMATCH"):
        run()


def test_ui_capture_tamper_rejected(tmp_path):
    _, _, ui, run = setup(tmp_path)
    ui.write_bytes(b"broken capture")
    with pytest.raises(gate.PerformanceAccessibilityError, match="UI_CAPTURE_HASH_MISMATCH"):
        run()


def test_not_same_device_baseline_rejected(tmp_path):
    _, baseline, _, run = setup(tmp_path)
    baseline["device"]["density_dpi"] = 320
    with pytest.raises(gate.PerformanceAccessibilityError, match="BASELINE_NOT_APPROVED_OR_INCOMPARABLE"):
        run()


def test_warn_needs_review_even_when_metrics_look_ok(tmp_path):
    req, _, _, run = setup(tmp_path)
    req["samples"][0]["result"] = "WARN"
    assert run()["state"] == "HUMAN_REVIEW_REQUIRED"


def test_device_profile_rejects_bogus_density(tmp_path):
    req, _, _, run = setup(tmp_path)
    req["device"]["density_dpi"] = 0
    with pytest.raises(gate.PerformanceAccessibilityError, match="DEVICE_PROFILE_INVALID"):
        run()
