"""X10-029 offline tests reuse actual AppLab visual_regression comparator."""
import hashlib
import importlib.util
import struct
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "scripts"


def module(name):
    import sys
    import importlib.util
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


gate = module("x10_visual_baseline_gate")
visual = module("visual_regression")
REPO = "example/app"
SHA = "a" * 40
PROFILE = {"theme": "light", "locale": "it-IT", "form_factor": "phone", "text_scale": 1.0}


def png(path, value):
    w, h = 96, 160
    row = bytes([0]) + bytes([value, value, value]) * w
    payload = zlib.compress(row * h)
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body +
                struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" +
                     chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", payload) + chunk(b"IEND", b""))


def capture(root, value=40, text="Home"):
    root.mkdir()
    img = root / "shot.png"
    xml = root / "view.xml"
    png(img, value)
    xml.write_text('<hierarchy><node package="com.example.app" text="' + text +
                   '" class="android.widget.Button" clickable="true" '
                   'bounds="[0,0][80,80]"/></hierarchy>', encoding="utf-8")
    def digest(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    return {"screenshot": "shot.png", "screenshot_sha256": digest(img),
            "ui": "view.xml", "ui_sha256": digest(xml)}


def fixtures(tmp_path, current_value=40, current_text="Home"):
    b, c = tmp_path / "baseline", tmp_path / "current"
    bc = capture(b)
    cc = capture(c, current_value, current_text)
    profile = dict(PROFILE)  # per-test copy: negative tests must not poison later cases
    lookup = {"approved": True, "repository": REPO, "package_id": "com.example.app",
              "screen": "home", "profile": profile, "source_sha": SHA,
              "review_url": f"https://github.com/{REPO}/pull/11", "capture": bc}
    request = {"schema_version": 1, "repository": REPO, "source_sha": SHA,
               "package_id": "com.example.app", "screen": "home",
               "profile": dict(profile), "workflow_run_id": 555,
               "capture": cc,
               "interactions": [{"action": "tap", "result": "PASS", "source_sha": SHA,
                                 "workflow_run_id": 555,
                                 "capture_sha256": cc["screenshot_sha256"]}]}
    def invoke(override_lookup=None):
        return gate.assess_case(
            request, baseline_root=b, current_root=c,
            approved_baseline_lookup=lambda *_: lookup if override_lookup is None else override_lookup,
            visual_regression_evaluate=visual.evaluate)
    return request, lookup, b, c, invoke


def test_actual_engine_identical_screen_is_report_only(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    out = go()
    assert out["state"] == "REFERENCE_MATCH_REPORTED"
    assert out["visual_comparator_result"] == "PASS"
    assert out["certified"] is False


def test_missing_reference_is_no_baseline_not_autoapproved(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    out = gate.assess_case(
        req, baseline_root=b, current_root=c, approved_baseline_lookup=lambda *_: None,
        visual_regression_evaluate=visual.evaluate)
    assert out["state"] == "NO_BASELINE"
    assert out["auto_baseline_created"] is False


def test_real_visual_engine_reports_material_regression(tmp_path):
    req, base, b, c, go = fixtures(tmp_path, 240, "Another screen")
    out = go()
    assert out["state"] in ("REGRESSION_REPORTED", "REQUIRES_HUMAN_VISUAL_REVIEW")
    assert out["certified"] is False


def test_no_interaction_receipt_fails(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    req["interactions"] = []
    with pytest.raises(gate.VisualCaseError, match="INTERACTION_EVIDENCE_MISSING_OR_STALE"):
        go()


def test_wrong_source_or_capture_run_fails(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    req["interactions"][0]["source_sha"] = "f" * 40
    with pytest.raises(gate.VisualCaseError, match="INTERACTION_EVIDENCE_MISSING_OR_STALE"):
        go()


def test_hash_tamper_fails_before_engine(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    (c / "shot.png").write_bytes(b"tampered")
    with pytest.raises(gate.VisualCaseError, match="CAPTURE_HASH_MISMATCH"):
        go()


def test_unapproved_reference_fails(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    base["approved"] = False
    with pytest.raises(gate.VisualCaseError, match="BASELINE_APPROVAL_OR_IDENTITY_MISMATCH"):
        go()


def test_unknown_profile_rejected(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    req["profile"]["locale"] = "unknown"
    with pytest.raises(gate.VisualCaseError, match="INVALID_DISPLAY_PROFILE"):
        go()


def test_warn_requires_human_not_false_positive_autoapproval(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    def reported_warn(*args, **kwargs):
        return {"result":"WARN","package_id":"com.example.app",
                "image_difference":{"masked_ratio":0.0,"baseline_size":[96,160],
                                    "current_size":[96,160]}, "findings":[{"code":"visual_change"}]}
    out = gate.assess_case(
        req, baseline_root=b, current_root=c,
        approved_baseline_lookup=lambda *_: base,
        visual_regression_evaluate=reported_warn)
    assert out["state"] == "REQUIRES_HUMAN_VISUAL_REVIEW"
    assert out["false_positives_auto_approved"] is False


def test_excessive_mask_is_never_clean(tmp_path):
    req, base, b, c, go = fixtures(tmp_path)
    def masked(*a, **kw):
        return {"result":"PASS","package_id":"com.example.app",
                "image_difference":{"masked_ratio":0.95,"baseline_size":[96,160],
                                    "current_size":[96,160]}}
    out = gate.assess_case(
        req, baseline_root=b, current_root=c,
        approved_baseline_lookup=lambda *_: base,
        visual_regression_evaluate=masked)
    assert out["state"] == "REQUIRES_HUMAN_VISUAL_REVIEW"
