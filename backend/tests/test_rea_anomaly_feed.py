"""Native REA anomaly feed: deterministic real artifact signals, no text guessing."""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import rea_anomaly_feed as feed  # noqa: E402
import rea_auto_router as router  # noqa: E402
import rea_build_probe as probe  # noqa: E402


@pytest.fixture
def apk_build(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "pubspec.yaml").write_text("name: fixture\n")
    manifest = root / "build" / "intermediates" / "merged_manifests" / "debug" / "processDebugManifest" / "AndroidManifest.xml"
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


def test_build_runner_discovers_real_anomaly_without_manual_rea_json(apk_build, monkeypatch):
    root, _, manifest, aapt, _ = apk_build
    monkeypatch.setattr(probe.package_build_contract, "android_build_tool", lambda _: str(aapt))
    assert probe.merged_manifest(root, root) == manifest
    monkeypatch.delenv("APPLAB_REA_TRUSTED_BIN")
    args = argparse.Namespace(source_root=root, working_directory=".", stack="flutter",
                              execute_eligible=False)
    plan, gap, owned = probe.build(args)
    assert gap is True and owned is True
    assert plan["status"] == "PROPOSE"
    assert plan["signals"] == ["PERMISSION_DECLARATION_MISMATCH"]
    assert "REA_ENVIRONMENT_NOT_READY" in plan["reason_codes"]


def test_build_runner_skips_ambiguous_manifests(apk_build, monkeypatch):
    root, _, manifest, aapt, _ = apk_build
    other = manifest.parent.parent / "processOtherManifest" / "AndroidManifest.xml"
    other.parent.mkdir()
    other.write_text(manifest.read_text())
    monkeypatch.setattr(probe.package_build_contract, "android_build_tool", lambda _: str(aapt))
    assert probe.merged_manifest(root, root) is None
    args = argparse.Namespace(source_root=root, working_directory=".", stack="native_android",
                              execute_eligible=False)
    plan, gap, owned = probe.build(args)
    assert plan["status"] == "SKIP" and not gap and not owned



def test_manifest_snapshot_survives_clean_and_remains_hash_bound(apk_build, tmp_path, monkeypatch):
    root, _, manifest, aapt, _ = apk_build
    snapshot = tmp_path / "rea-preserved-manifest.xml"
    outputs = tmp_path / "github-output"
    args = argparse.Namespace(source_root=root, working_directory=".", stack="flutter",
                              output=snapshot, github_output=outputs, execute_eligible=False)
    probe.capture(args)
    assert snapshot.is_file()
    assert f"manifest_file={snapshot}\n" in outputs.read_text()
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert f"manifest_sha256={digest}\n" in outputs.read_text()
    # The repository checkout is restored after build and loses ignored/untracked files.
    manifest.unlink()
    monkeypatch.setenv("APPLAB_REA_PRESERVED_MANIFEST", str(snapshot))
    monkeypatch.setenv("APPLAB_REA_PRESERVED_MANIFEST_SHA256", digest)
    monkeypatch.setattr(probe.package_build_contract, "android_build_tool", lambda _: str(aapt))
    decision, gap, owned = probe.build(args)
    assert gap is True and owned is True
    assert decision["signals"] == ["PERMISSION_DECLARATION_MISMATCH"]
    assert decision["status"] == "PROPOSE"
    snapshot.write_text(snapshot.read_text().replace("CAMERA", "BLUETOOTH"))
    decision, gap, owned = probe.build(args)
    assert decision["status"] == "SKIP" and not gap


def test_custom_android_module_is_discovered(apk_build):
    root, _, manifest, _, _ = apk_build
    mobile = root / "mobile" / "build" / "intermediates" / "merged_manifests" / "debug" / "processDebugManifest"
    mobile.mkdir(parents=True)
    custom = mobile / "AndroidManifest.xml"
    shutil.move(str(manifest), str(custom))
    assert probe.merged_manifest(root, root) == custom


def test_build_runners_bind_ownership_and_keep_rea_research_only():
    for name in ("external-project-runner.yml", "external-native-android-runner.yml"):
        source = (ROOT / ".github" / "workflows" / name).read_text()
        assert len(source.splitlines()) <= 900
        assert "Preserve merged manifest for optional REA research" in source
        assert "Execute optional REA research on source-bound APK anomalies" in source
        assert source.count("uses: ./.applab/.github/actions/rea-auto-research") == 2
        assert "phase: capture" in source and "phase: research" in source
        assert "ownership_attested:" in source
        assert "steps.rea_merged.outputs.manifest_sha256" in source
        assert "continue-on-error: true" in source

    action = (ROOT / ".github" / "actions" / "rea-auto-research" / "action.yml").read_text()
    assert "steps.capture.outputs.manifest_sha256" in action
    assert "APPLAB_REA_PRESERVED_MANIFEST_SHA256" in action
    assert "steps.preflight.outputs.binary_gap == 'true'" in action
    assert "steps.node.outcome == 'success'" in action
    assert "rea-agents@6.9.0" in action
    assert "sha256sum --check --status" in action
    assert "--execute-eligible" in action
    assert action.count("continue-on-error: true") >= 3
