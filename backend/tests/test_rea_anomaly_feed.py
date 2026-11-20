"""Native REA anomaly feed: deterministic real artifact signals, no text guessing."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import rea_anomaly_feed as feed  # noqa: E402
import rea_auto_router as router  # noqa: E402


@pytest.fixture
def apk_build(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "pubspec.yaml").write_text("name: fixture\n")
    manifest = root / "build" / "merged" / "AndroidManifest.xml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        '<uses-permission android:name="android.permission.CAMERA"/></manifest>')
    subprocess.run(["git", "-C", str(root), "add", "pubspec.yaml"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "source"], check=True)
    sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"PK\x03\x04real-local-bytes-placeholder")
    aapt = tmp_path / "fake-aapt"
    aapt.write_text(
        "#!/usr/bin/env python3\n"
        "print(\"package: name='org.example'\")\n"
        "print(\"uses-permission: name='android.permission.INTERNET'\")\n")
    aapt.chmod(0o755)
    engine = tmp_path / "rea"
    engine.write_text("#!/usr/bin/env python3\n")
    engine.chmod(0o755)
    env = {
        "APPLAB_REA_AUTHORIZED_ARTIFACT": str(apk),
        "APPLAB_REA_AUTHORIZED_REPOSITORY": "owner/demo",
        "APPLAB_REA_AUTHORIZED_SOURCE_SHA": sha,
        "APPLAB_REA_TRUSTED_BIN": str(engine),
        "APPLAB_REA_PRIVATE_OUTPUT_ROOT": str(tmp_path / "private"),
        "APPLAB_REA_MERGED_MANIFEST": str(manifest),
        "APPLAB_REA_TRUSTED_AAPT_BIN": str(aapt),
        "APPLAB_REA_OWNERSHIP_ATTESTED": "true",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return root, apk, manifest, aapt, sha


def test_machine_detects_real_permission_delta(apk_build):
    root, apk, _, _, sha = apk_build
    context = feed.from_trusted_apk(root, "flutter")
    assert context["signals"] == ["PERMISSION_DECLARATION_MISMATCH"]
    assert context["artifact_sha256"] == hashlib.sha256(apk.read_bytes()).hexdigest()
    assert context["source_sha"] == sha
    plan = router.decide(context)
    assert plan["mode"] == "android"
    assert plan["status"] == "PROPOSE"  # missing pinned JADX, never download
    assert "PINNED_JADX_ENGINE_NOT_READY" in plan["reason_codes"]


def test_normal_apk_is_skipped(apk_build):
    root, _, manifest, _, _ = apk_build
    manifest.write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        '<uses-permission android:name="android.permission.INTERNET"/></manifest>')
    context = feed.from_trusted_apk(root, "native_android")
    assert context["signals"] == []
    assert router.decide(context)["status"] == "SKIP"


def test_missing_or_stale_runner_attestation_cannot_invent_signal(apk_build, monkeypatch):
    root, _, manifest, _, _ = apk_build
    monkeypatch.delenv("APPLAB_REA_TRUSTED_AAPT_BIN")
    assert feed.from_trusted_apk(root, "flutter") is None
    monkeypatch.setenv("APPLAB_REA_TRUSTED_AAPT_BIN", str(apk_build[3]))
    monkeypatch.setenv("APPLAB_REA_AUTHORIZED_SOURCE_SHA", "f" * 40)
    assert feed.from_trusted_apk(root, "flutter") is None
    monkeypatch.setenv("APPLAB_REA_AUTHORIZED_SOURCE_SHA", apk_build[4])
    manifest.unlink()
    manifest.symlink_to(apk_build[1])
    assert feed.from_trusted_apk(root, "flutter") is None


def test_unattested_ownership_cannot_start_rea(apk_build, monkeypatch):
    root, _, _, _, _ = apk_build
    monkeypatch.delenv("APPLAB_REA_OWNERSHIP_ATTESTED")
    context = feed.from_trusted_apk(root, "flutter")
    assert context["authorization"] == "EXTERNAL_AUTHORIZED"
    plan = router.decide(context)
    assert plan["status"] == "PROPOSE"
    assert "EXTERNAL_SOURCE_REQUIRES_EXPLICIT_REVIEW" in plan["reason_codes"]


def test_non_android_and_bad_aapt_output_does_not_trigger(apk_build):
    root, _, _, aapt, _ = apk_build
    assert feed.from_trusted_apk(root, "web_or_hybrid") is None
    aapt.write_text("#!/usr/bin/env python3\nprint('unrecognized output')\n")
    assert feed.from_trusted_apk(root, "flutter") is None


def test_derived_signal_does_not_replace_mandatory_labs(apk_build):
    from audit_orchestrator import build_plan
    root, _, _, _, _ = apk_build
    report = {"scan": {"confidence": "HIGH"},
              "product": {"stack": {"engine": "flutter"}, "feature_signals": []}}
    basic = build_plan(report)
    routed = build_plan(report, rea_context=feed.from_trusted_apk(root, "flutter"))
    assert routed["rea_research"]["status"] == "PROPOSE"
    assert routed["selected_labs"] == basic["selected_labs"]
