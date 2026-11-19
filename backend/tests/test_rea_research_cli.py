"""Bounded REA static research adapter: CLI positive/negative and evidence tests."""
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/rea_research_cli.py"
SHA = "a" * 40


@pytest.fixture
def sandbox(tmp_path):
    engine = tmp_path / "fake-rea"
    engine.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "argv=sys.argv[1:]\n"
        "if argv[:2]==['--version','--json']:\n"
        " print(json.dumps({'name':'rea-agents','version':os.getenv('REA_FAKE_VERSION','6.9.0'),"
        "'supported_runtime':{'satisfied':True}}))\n"
        "elif argv and argv[0] in ('inspect-desktop-application','inspect-managed-artifact',"
        "'identify-flutter-build','inspect-dart-aot','inspect-android-package'):\n"
        " print(json.dumps({'meta':{'command':argv[0]},'normalized_result':"
        "{'classification':'static_fixture'}}))\n"
        " if os.getenv('REA_FAKE_FAIL')=='1':sys.exit(4)\n"
        "else:sys.exit(3)\n", encoding="utf-8")
    engine.chmod(0o755)
    managed = tmp_path / "managed.exe"
    managed.write_bytes(b"MZ" + b"\x00" * 1022)
    flutter = tmp_path / "flutter.apk"
    with zipfile.ZipFile(flutter, "w") as z:
        z.writestr("AndroidManifest.xml", b"fixture")
        z.writestr("lib/arm64-v8a/libapp.so", b"not-a-real-lib")
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "sample.dll").write_bytes(b"MZfixture")
    return engine, managed, flutter, desktop, tmp_path / "output"


def invoke(sandbox, family, artifact, *more, env=None):
    exe, _, _, _, out = sandbox
    cmd = [sys.executable, str(SCRIPT), "--rea-bin", str(exe),
           "--artifact", str(artifact), "--output-dir", str(out),
           "--repository", "riccardopinato/Sample", "--source-sha", SHA,
           "--family", family, *more]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)


@pytest.mark.parametrize("family,idx,operations", [
    ("managed", 1, ["metadata"]),
    ("flutter", 2, ["build", "aot"]),
    ("desktop", 3, ["inventory"]),
])
def test_all_safe_local_families_and_idempotent_evidence(sandbox, family, idx, operations):
    result = invoke(sandbox, family, sandbox[idx])
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["mode"] == "CLI_ONLY_NO_MCP"
    assert record["status"] == "REA_CLI_STATIC_OBSERVED"
    assert record["independent_runtime_certified"] is False
    assert [v["operation"] for v in record["operations"]] == operations
    for item in record["operations"]:
        file = sandbox[-1] / item["json_file"]
        assert file.is_file()
        assert item["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
        assert item["review"] == "UNVALIDATED_EXTERNAL_OUTPUT"
    assert invoke(sandbox, family, sandbox[idx]).returncode == 0


def test_scoped_single_operation_does_not_run_all(sandbox):
    result = invoke(sandbox, "flutter", sandbox[2], "--operation", "build")
    assert result.returncode == 0
    assert len(json.loads(result.stdout)["operations"]) == 1


def test_no_implicit_jadx_and_unpinned_jar_blocked(sandbox, tmp_path):
    missing = invoke(sandbox, "android", sandbox[2])
    assert missing.returncode == 2
    assert "JADX" in missing.stderr
    jar = tmp_path / "random.jar"
    jar.write_bytes(b"untrusted")
    wrong = invoke(sandbox, "android", sandbox[2], "--jadx-jar", str(jar))
    assert wrong.returncode == 2
    assert "checksum mismatch" in wrong.stderr
    assert not sandbox[-1].exists()


def test_version_and_unsupported_operation_rejected(sandbox):
    env = {**os.environ, "REA_FAKE_VERSION": "6.9.1"}
    version = invoke(sandbox, "managed", sandbox[1], env=env)
    assert version.returncode == 2
    assert "Wrong REA version" in version.stderr
    badop = invoke(sandbox, "managed", sandbox[1], "--operation", "aot")
    assert badop.returncode == 2
    assert "not allowlisted" in badop.stderr


def test_expected_checksum_and_file_budget_are_fail_closed(sandbox):
    bad = invoke(sandbox, "managed", sandbox[1], "--expected-sha256", "0" * 64)
    assert bad.returncode == 2
    assert "hash mismatch" in bad.stderr
    small = invoke(sandbox, "managed", sandbox[1], "--max-bytes", "20")
    assert small.returncode == 2
    assert "size outside" in small.stderr


def test_symlinks_and_directory_escape_rejected(sandbox, tmp_path):
    link = tmp_path / "linked.exe"
    link.symlink_to(sandbox[1])
    assert "regular file" in invoke(sandbox, "managed", link).stderr
    nested = sandbox[3] / "linked"
    nested.symlink_to(sandbox[1])
    bad = invoke(sandbox, "desktop", sandbox[3])
    assert bad.returncode == 2
    assert "symlink" in bad.stderr
    nested.unlink()
    out = sandbox[3] / "evidence"
    bad2 = invoke((sandbox[0], sandbox[1], sandbox[2], sandbox[3], out),
                  "desktop", sandbox[3])
    assert bad2.returncode == 2
    assert "outside inspected tree" in bad2.stderr


def test_evidence_collision_and_tool_failure_do_not_certify(sandbox):
    first = invoke(sandbox, "managed", sandbox[1])
    assert first.returncode == 0
    evidence = sandbox[-1] / json.loads(first.stdout)["operations"][0]["json_file"]
    evidence.write_text('{"changed":true}')
    assert "collision" in invoke(sandbox, "managed", sandbox[1]).stderr

    another = sandbox[-1].parent / "other"
    another_case = (sandbox[0], sandbox[1], sandbox[2], sandbox[3], another)
    env = {**os.environ, "REA_FAKE_FAIL": "1"}
    failed = invoke(another_case, "flutter", sandbox[2], env=env)
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["status"] == "REA_CLI_PARTIAL_OR_FAILED"
