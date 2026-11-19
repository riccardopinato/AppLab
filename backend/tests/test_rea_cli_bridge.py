"""REA CLI bridge: allowlisted, version-bound, read-only research evidence."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[2] / "scripts/rea_cli_bridge.py"
SOURCE_SHA = "a" * 40


def fixture_pe(path: Path) -> None:
    """Minimal synthetic PE wrapper, never intended for execution."""
    b = bytearray(1024)
    b[:2] = b"MZ"
    b[0x3C:0x40] = (0x80).to_bytes(4, "little")
    b[0x80:0x84] = b"PE\x00\x00"
    b[0x84:0x86] = (0x8664).to_bytes(2, "little")
    b[0x86:0x88] = (1).to_bytes(2, "little")
    b[0x94:0x96] = (240).to_bytes(2, "little")
    b[0x96:0x98] = (0x2022).to_bytes(2, "little")
    opt = 0x98
    b[opt:opt+2] = (0x20B).to_bytes(2, "little")
    b[opt+16:opt+20] = (0x1000).to_bytes(4, "little")
    b[opt+20:opt+24] = (0x1000).to_bytes(4, "little")
    b[opt+24:opt+32] = (0x140000000).to_bytes(8, "little")
    b[opt+32:opt+36] = (0x1000).to_bytes(4, "little")
    b[opt+36:opt+40] = (0x200).to_bytes(4, "little")
    b[opt+56:opt+60] = (0x2000).to_bytes(4, "little")
    b[opt+60:opt+64] = (0x200).to_bytes(4, "little")
    b[opt+68:opt+70] = (3).to_bytes(2, "little")
    b[opt+70:opt+72] = (0x8160).to_bytes(2, "little")
    b[opt+108:opt+112] = (16).to_bytes(4, "little")
    sec = 0x188
    b[sec:sec+5] = b".text"
    b[sec+8:sec+12] = (16).to_bytes(4, "little")
    b[sec+12:sec+16] = (0x1000).to_bytes(4, "little")
    b[sec+16:sec+20] = (0x200).to_bytes(4, "little")
    b[sec+20:sec+24] = (0x200).to_bytes(4, "little")
    b[sec+36:sec+40] = (0x60000020).to_bytes(4, "little")
    path.write_bytes(bytes(b))


@pytest.fixture
def rei(tmp_path):
    artifact = tmp_path / "synthetic.exe"
    fixture_pe(artifact)
    exe = tmp_path / "fake-rea"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "x=sys.argv[1:]\n"
        "if x[:2]==['--version','--json']:\n"
        " print(json.dumps({'name':'rea-agents','version':"
        "os.environ.get('REA_TEST_VERSION','6.9.0'),"
        "'supported_runtime':{'satisfied':True}}))\n"
        "elif x and x[0] in ('inspect-pe-imports','inspect-pe-certificates'):\n"
        " print(json.dumps({'operation':x[0],'input':x[1],"
        "'observations':[]}))\n"
        " if os.environ.get('REA_TEST_FAIL')=='1':sys.exit(1)\n"
        "else:sys.exit(3)\n",
        encoding="utf-8",
    )
    exe.chmod(0o755)
    return artifact, exe, tmp_path / "private-evidence"


def run_cli(rei, *extra, env=None):
    artifact, exe, out = rei
    command = [sys.executable, str(BRIDGE), "--rea-bin", str(exe),
               "--artifact", str(artifact), "--output-dir", str(out),
               "--repository", "BLEZZ0102/Deskland",
               "--source-sha", SOURCE_SHA, *extra]
    return subprocess.run(command, capture_output=True, text=True, check=False,
                          env=env)


def test_two_allowlisted_commands_and_persisted_hashes(rei):
    result = run_cli(rei)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["mode"] == "CLI_ONLY_NO_MCP"
    assert receipt["donor_admission"] == "RESEARCH_ONLY"
    assert receipt["status"] == "REA_CLI_STATIC_OBSERVED"
    assert len(receipt["operations"]) == 2
    assert {x["operation"] for x in receipt["operations"]} == {"imports", "certificates"}
    assert all((rei[2] / x["evidence_file"]).is_file() for x in receipt["operations"])
    assert run_cli(rei).returncode == 0  # immutable evidence, identical bytes


def test_explicit_single_operation(rei):
    result = run_cli(rei, "--operation", "imports")
    assert result.returncode == 0
    assert [x["operation"] for x in json.loads(result.stdout)["operations"]] == ["imports"]


def test_refuse_wrong_version_before_binary_inspection(rei):
    env = {**os.environ, "REA_TEST_VERSION": "6.8.9"}
    result = run_cli(rei, env=env)
    assert result.returncode == 2
    assert "version/runtime mismatch" in result.stderr
    assert not rei[2].exists()


def test_external_failure_is_recorded_but_never_certified(rei):
    env = {**os.environ, "REA_TEST_FAIL": "1"}
    result = run_cli(rei, "--operation", "imports", env=env)
    assert result.returncode == 1
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "REA_CLI_PARTIAL_OR_FAILED"
    assert receipt["operations"][0]["rea_success"] is False


def test_reject_symlink_bad_artifact_and_bad_paths(rei):
    artifact, exe, out = rei
    link = artifact.parent / "link.exe"
    link.symlink_to(artifact)
    other = run_cli((link, exe, out))
    assert other.returncode == 2
    assert "regular file" in other.stderr
    artifact.write_text("not a PE", encoding="utf-8")
    assert run_cli(rei).returncode == 2
    assert not out.exists()
    assert run_cli(rei, "--source-sha", "bad").returncode != 0


def test_evidence_collision_does_not_overwrite(rei):
    first = run_cli(rei, "--operation", "imports")
    assert first.returncode == 0
    receipt = json.loads(first.stdout)
    evidence = rei[2] / receipt["operations"][0]["evidence_file"]
    evidence.write_text('{"tampered":true}', encoding="utf-8")
    blocked = run_cli(rei, "--operation", "imports")
    assert blocked.returncode == 2
    assert "collision" in blocked.stderr
    assert evidence.read_text(encoding="utf-8") == '{"tampered":true}'
