"""Read-only NSIS/extracted desktop package manifest validation."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from rea_desktop_manifest_verify import compare


def test_real_hashes_pass_without_execution(tmp_path):
    tree = tmp_path / "installer-output"
    tree.mkdir()
    nested = tree / "host"
    nested.mkdir()
    exe = nested / "Deskland.exe"
    exe.write_bytes(b"synthetic-not-executable")
    manifest = tmp_path / "official-manifest.json"
    manifest.write_text(json.dumps([{
        "path": "host/Deskland.exe",
        "sha256": hashlib.sha256(exe.read_bytes()).hexdigest()
    }]), encoding="utf8")
    result = compare(tree, manifest)
    assert result["status"] == "PASS"
    assert result["matched"] == 1
    assert result["no_execution"]
    exe.write_bytes(b"changed")
    failure = compare(tree, manifest)
    assert failure["status"] == "FAIL"
    assert failure["mismatched"] == ["host/Deskland.exe"]


def test_manifest_rejects_path_traversal_duplicate_symlink(tmp_path):
    tree = tmp_path / "target"
    tree.mkdir()
    (tree / "file.txt").write_text("abc")
    manifest = tmp_path / "manifest.json"
    for rows in (
        [{"path": "../secret", "sha256": "0" * 64}],
        [{"path": "file.txt", "sha256": "0" * 64},
         {"path": "FILE.txt", "sha256": "0" * 64}],
        [{"path": "file.txt", "sha256": "oops"}],
    ):
        manifest.write_text(json.dumps(rows))
        with pytest.raises(ValueError):
            compare(tree, manifest)
    target = tmp_path / "other"
    target.write_bytes(b"xyz")
    (tree / "link").symlink_to(target)
    manifest.write_text(json.dumps([{"path": "link", "sha256": hashlib.sha256(b"xyz").hexdigest()}]))
    with pytest.raises(ValueError, match="unsafe"):
        compare(tree, manifest)
