"""Tests for safe, non-executing REA artifact intake."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/rea_artifact_intake.py"
SPEC = importlib.util.spec_from_file_location("rea_artifact_intake", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
SHA = "a" * 40
REA = "4491c84c82140a43fa12390b727840a433875ba8"


def pe_bytes(machine: int = 0x8664) -> bytes:
    payload = bytearray(128)
    payload[:2] = b"MZ"
    payload[0x3C:0x40] = (0x40).to_bytes(4, "little")
    payload[0x40:0x44] = b"PE\x00\x00"
    payload[0x44:0x46] = machine.to_bytes(2, "little")
    return bytes(payload)


def test_static_pe_identity_no_runtime_claim(tmp_path):
    f = tmp_path / "Deskland-Setup.exe"
    f.write_bytes(pe_bytes())
    output = module.intake(f, "BLEZZ0102/Deskland", SHA, REA)
    assert output["artifact"]["container"] == "PE"
    assert output["artifact"]["pe_machine"] == "x86_64"
    assert output["artifact"]["bytes"] == 128
    assert len(output["artifact"]["sha256"]) == 64
    assert output["execution"] == "NONE"
    assert output["donor_admission"] == "RESEARCH_ONLY"
    assert output["observed_functional_behavior"] == "NOT_VERIFIED"


def test_reject_symlink_oversize_and_invalid_identity(tmp_path):
    f = tmp_path / "payload.exe"
    f.write_bytes(pe_bytes())
    link = tmp_path / "link.exe"
    link.symlink_to(f)
    with pytest.raises(ValueError, match="regular"):
        module.intake(link, "BLEZZ0102/Deskland", SHA, REA)
    with pytest.raises(ValueError, match="exceeds"):
        module.intake(f, "BLEZZ0102/Deskland", SHA, REA, max_bytes=8)
    with pytest.raises(ValueError, match="source SHA"):
        module.intake(f, "BLEZZ0102/Deskland", "main", REA)


def test_missing_target_fails_closed(tmp_path):
    missing = tmp_path / "missing.exe"
    cmd = [sys.executable, str(SCRIPT), "--artifact", str(missing),
           "--repository", "BLEZZ0102/Deskland", "--source-sha", SHA,
           "--rea-commit", REA]
    process = subprocess.run(cmd, text=True, capture_output=True, check=False)
    assert process.returncode == 2
    assert "BLOCKED" in process.stderr
    assert not process.stdout


def test_external_report_is_hashed_not_certified(tmp_path):
    f = tmp_path / "binary.exe"
    f.write_bytes(pe_bytes(0x14C))
    report = tmp_path / "rea.json"
    report.write_text('{"claim": "this file is safe"}', encoding="utf-8")
    result = module.intake(f, "BLEZZ0102/Deskland", SHA, REA, report)
    assert result["artifact"]["pe_machine"] == "x86"
    assert result["rea_report_reference"]["trust"] == "UNVALIDATED_EXTERNAL_OUTPUT"
    assert result["architecture_inferred_from_binary"] == "NOT_VERIFIED"
    with pytest.raises(ValueError, match="distinct"):
        module.intake(f, "BLEZZ0102/Deskland", SHA, REA, f)


def test_non_pe_does_not_invent_architecture(tmp_path):
    f = tmp_path / "install.bin"
    f.write_bytes(b"MZ" + b"\x00" * 10)
    result = module.intake(f, "BLEZZ0102/Deskland", SHA, REA)
    assert result["artifact"]["container"] == "MZ_UNCONFIRMED"
    assert result["artifact"]["pe_machine"] is None
