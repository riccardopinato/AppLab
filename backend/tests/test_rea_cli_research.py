"""Scope/identity/evidence regression suite for Desktop, Android, Flutter REA CLI."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import rea_cli_research as adapter
from rea_cli_bridge import BridgeBlocked
from test_rea_cli_bridge import fixture_pe

SOURCE_SHA = "a" * 40


@pytest.fixture
def rig(tmp_path):
    exe = tmp_path / "fake-rea"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "args=sys.argv[1:]\n"
        "if args[:2]==['--version','--json']:\n"
        " print(json.dumps({'name':'rea-agents','version':os.environ.get('FAKE_VERSION','6.9.0'),"
        "'supported_runtime':{'satisfied':True}}))\n"
        "else:\n"
        " if '--evidence_output' in args:\n"
        "  from pathlib import Path\n"
        "  Path(args[args.index('--evidence_output')+1]).write_text('{}')\n"
        " print(json.dumps({'normalized_result':{'tool':args[0],"
        "'flutter_detected':False},'coverage':'synthetic'}))\n"
        " if os.environ.get('FAKE_FAIL')=='1':sys.exit(3)\n",
        encoding="utf-8")
    exe.chmod(0o755)
    managed = tmp_path / "managed.exe"
    fixture_pe(managed)
    apk = tmp_path / "sample.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00")
        z.writestr("classes.dex", b"dex\n035\x00")
    flutter = tmp_path / "flutter.apk"
    with zipfile.ZipFile(flutter, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00\x08\x00")
        z.writestr("lib/arm64-v8a/libapp.so", b"NO_EXECUTION")
    tree = tmp_path / "desktop-app"
    tree.mkdir()
    (tree / "readme.txt").write_text("Inert desktop fixture", encoding="utf8")
    return exe, managed, apk, flutter, tree, tmp_path / "evidence"


def go(rig, mode, target, operations=None, **kwargs):
    exe, _, _, _, _, out = rig
    return adapter.invoke(exe, None, target, out, mode,
                          operations or list(adapter.OPERATIONS[mode]),
                          "riccardopinato/AppLab", SOURCE_SHA, **kwargs)


def test_desktop_directory_and_hashes(rig):
    receipt = go(rig, "desktop", rig[4])
    assert receipt["status"] == "REA_RESEARCH_OBSERVED"
    assert receipt["artifact"]["files"] == 1
    assert receipt["artifact"]["type"] == "directory"
    assert receipt["trusted_runtime"] is False
    assert receipt["automatic_goldens"] is False
    assert go(rig, "desktop", rig[4])["artifact"]["sha256"] == receipt["artifact"]["sha256"]


def test_managed_pe_is_separate_operation(rig):
    receipt = go(rig, "managed", rig[1], ["inspect-managed-artifact"])
    assert receipt["artifact"]["container"] == "PE"
    assert receipt["operations"][0]["operation"] == "inspect-managed-artifact"
    assert receipt["operations"][0]["evidence"]["bytes"] > 0


def test_android_apk_is_accepted_for_static_engine(rig):
    receipt = go(rig, "android", rig[2])
    assert receipt["artifact"]["zip_entries"] == 2
    assert receipt["operations"][0]["operation"] == "inspect-android-package"
    assert receipt["donor_admission"] == "RESEARCH_ONLY"


def test_flutter_positive_and_nonflutter_negative(rig):
    yes = go(rig, "flutter", rig[3])
    assert [o["status"] for o in yes["operations"]] == ["OBSERVED", "OBSERVED"]
    no = go(rig, "flutter", rig[2])
    assert no["operations"][1]["status"] == "NOT_APPLICABLE_NO_LIBAPP_SO"
    assert no["operations"][0]["status"] == "OBSERVED"


def test_reject_expected_artifact_mismatch_before_launch(rig):
    with pytest.raises(BridgeBlocked, match="SHA-256 mismatch"):
        go(rig, "android", rig[2], expected_sha="0" * 64)
    assert not rig[-1].exists()


def test_reject_symlink_and_zip_path_traversal(rig):
    exe, _, apk, _, tree, _ = rig
    symlink = apk.parent / "fake.apk"
    symlink.symlink_to(apk)
    with pytest.raises(BridgeBlocked, match="regular file"):
        go(rig, "android", symlink)
    suspicious = apk.parent / "unsafe.apk"
    with zipfile.ZipFile(suspicious, "w") as z:
        z.writestr("AndroidManifest.xml", b"foo")
        z.writestr("../escape", b"bad")
    with pytest.raises(BridgeBlocked, match="unsafe"):
        go(rig, "android", suspicious)
    (tree / "unsafe").symlink_to(apk)
    with pytest.raises(BridgeBlocked, match="symlink"):
        go(rig, "desktop", tree)


def test_never_overwrite_divergent_evidence(rig):
    receipt = go(rig, "android", rig[2])
    p = rig[-1] / receipt["operations"][0]["evidence"]["file"]
    assert p.is_file()
    assert hashlib.sha256(p.read_bytes()).hexdigest() == receipt["operations"][0]["evidence"]["sha256"]
    p.write_text('{"changed":true}', encoding="utf8")
    with pytest.raises(BridgeBlocked, match="collision"):
        go(rig, "android", rig[2])


def test_failure_is_recorded_and_version_mismatch_blocks(rig, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "1")
    result = go(rig, "managed", rig[1], ["inspect-managed-artifact"])
    assert result["status"] == "REA_RESEARCH_PARTIAL_OR_FAILED"
    assert result["operations"][0]["status"] == "REA_FAILED"
    monkeypatch.delenv("FAKE_FAIL")
    monkeypatch.setenv("FAKE_VERSION", "9.9.9")
    with pytest.raises(BridgeBlocked, match="version/runtime mismatch"):
        go(rig, "android", rig[2], expected_sha=hashlib.sha256(rig[2].read_bytes()).hexdigest())


def test_reject_cross_mode_and_small_size(rig):
    with pytest.raises(BridgeBlocked, match="Unsupported or duplicate"):
        go(rig, "android", rig[2], ["inspect-managed-artifact"])
    with pytest.raises(ValueError):
        go(rig, "android", rig[2], max_bytes=10)
    with pytest.raises(BridgeBlocked, match="outside the desktop target tree"):
        adapter.invoke(rig[0], None, rig[4], rig[4] / "out",
                       "desktop", ["inspect-desktop-application"],
                       "riccardopinato/AppLab", SOURCE_SHA)
