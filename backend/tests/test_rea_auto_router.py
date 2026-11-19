"""REA auto router: source-first decisions, independent SHA and safe CLI dispatch."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import rea_auto_router as router  # noqa: E402
import rea_cli_research as research  # noqa: E402

SHA = "a" * 40
REPO = "riccardopinato/OwnApp"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    apk = tmp_path / "own.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", b"manifest")
        z.writestr("lib/arm64-v8a/libapp.so", b"static-fixture-aot")
    engine = tmp_path / "fake-rea"
    engine.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys,os\n"
        "a=sys.argv[1:]\n"
        "if a[:2] == ['--version','--json']:\n"
        " print(json.dumps({'name':'rea-agents','version':os.getenv('REA_TEST_VERSION','6.9.0'),"
        "'supported_runtime':{'satisfied':True}}))\n"
        "elif a[0] in ('identify-flutter-build','inspect-dart-aot'):\n"
        " print(json.dumps({'normalized_result':{'fixture':True},'version':1}))\n"
        "else: sys.exit(3)\n", encoding="utf-8")
    engine.chmod(0o755)
    for name, value in {
        "APPLAB_REA_TRUSTED_BIN": str(engine),
        "APPLAB_REA_AUTHORIZED_ARTIFACT": str(apk),
        "APPLAB_REA_AUTHORIZED_REPOSITORY": REPO,
        "APPLAB_REA_AUTHORIZED_SOURCE_SHA": SHA,
        "APPLAB_REA_PRIVATE_OUTPUT_ROOT": str(tmp_path / "evidence"),
    }.items():
        monkeypatch.setenv(name, value)
    ctx = {"repository": REPO, "source_sha": SHA, "authorization": "OWNED",
           "artifact_path": str(apk), "artifact_kind": "APK",
           "artifact_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
           "stack": "flutter", "source_complete": False,
           "signals": ["AOT_BINARY_QUESTION"],
           "rea_bin": str(engine), "output_dir": str(tmp_path / "evidence")}
    return ctx, apk, engine


def test_routine_audit_never_invokes_rea(harness, monkeypatch):
    ctx, _, _ = harness
    ctx["signals"] = []
    assert router.decide(ctx)["reason_codes"] == ["SOURCE_FIRST_NO_BINARY_GAP"]
    monkeypatch.setattr(router.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("REA must not start"))
    assert router.execute(ctx, router.decide(ctx))["execution"] == "NOT_STARTED"


def test_owned_binary_gap_auto_routes_and_rea_cli_executes(harness):
    ctx, apk, _ = harness
    decision = router.decide(ctx)
    assert decision["status"] == "AUTO_RUN"
    assert decision["mode"] == "flutter"
    assert decision["operations"] == ["identify-flutter-build", "inspect-dart-aot"]
    result = router.execute(ctx, decision)
    assert result["execution"] == "SUCCESS"
    assert result["research_only"] is True
    assert result["certification"] == "NONE"
    assert len(list(Path(ctx["output_dir"]).glob("*.json"))) == 2
    # The input artifact is never executed or mutated.
    assert hashlib.sha256(apk.read_bytes()).hexdigest() == ctx["artifact_sha256"]


def test_source_sufficient_no_bin_question(harness):
    ctx, _, _ = harness
    ctx.update(source_complete=True, signals=["MISSING_SOURCE"])
    assert router.decide(ctx)["status"] == "SKIP"


def test_unknown_ownership_and_external_need_review(harness):
    ctx, _, _ = harness
    ctx["authorization"] = "UNKNOWN"
    assert router.decide(ctx)["status"] == "BLOCKED"
    ctx["authorization"] = "EXTERNAL_AUTHORIZED"
    result = router.decide(ctx)
    assert result["status"] == "PROPOSE"
    assert "EXTERNAL_SOURCE_REQUIRES_EXPLICIT_REVIEW" in result["reason_codes"]


def test_missing_environment_and_duplicate_evidence_are_skips(harness):
    ctx, _, _ = harness
    ctx.pop("rea_bin")
    assert router.decide(ctx)["status"] == "PROPOSE"
    ctx["rea_bin"] = str(harness[2])
    decision = router.decide(ctx)
    ctx["previous_success"] = {"source_sha": ctx["source_sha"],
                               "artifact_sha256": ctx["artifact_sha256"],
                               "mode": decision["mode"], "operations": decision["operations"]}
    assert router.decide(ctx)["reason_codes"] == ["EXACT_ARTIFACT_ALREADY_INSPECTED"]


def test_invalid_sha_or_mutated_artifact_blocks(harness):
    ctx, apk, _ = harness
    ctx["artifact_sha256"] = "b" * 64
    assert router.decide(ctx)["status"] == "BLOCKED"
    ctx["artifact_sha256"] = "not a sha"
    assert router.decide(ctx)["status"] == "PROPOSE"
    ctx["artifact_sha256"] = hashlib.sha256(apk.read_bytes()).hexdigest()
    ctx["source_sha"] = "short"
    assert router.decide(ctx)["status"] == "BLOCKED"


def test_unsupported_signals_and_artifact_gates(harness):
    ctx, _, _ = harness
    ctx["signals"] = ["CAN_SCAN_ALL_APPS"]
    with pytest.raises(ValueError, match="Unknown REA trigger"):
        router.decide(ctx)
    ctx["signals"] = ["PERMISSION_DECLARATION_MISMATCH"]
    assert router.decide(ctx)["operations"] == ["inspect-android-package"]
    ctx["artifact_kind"] = "AAB"
    assert router.decide(ctx)["status"] == "BLOCKED"


def test_executable_cannot_be_artifact(harness):
    ctx, apk, engine = harness
    ctx.update(artifact_kind="PE", artifact_path=str(engine),
               artifact_sha256=hashlib.sha256(engine.read_bytes()).hexdigest(),
               signals=["MANAGED_METADATA_QUESTION"])
    plan = router.decide(ctx)
    assert plan["status"] == "BLOCKED"
    assert plan["reason_codes"][-1] == "REA_EXECUTABLE_EQUALS_TARGET"


def test_pe_bridge_is_invoked_without_unknown_expected_sha_flag(harness, monkeypatch):
    ctx, apk, engine = harness
    pe = apk.parent / "program.exe"
    # A synthetic target only tests command assembly; PE parsing remains in existing tests.
    pe.write_bytes(b"MZ" + b"\x00" * 300)
    monkeypatch.setenv("APPLAB_REA_AUTHORIZED_ARTIFACT", str(pe))
    ctx.update(artifact_kind="PE", artifact_path=str(pe),
               artifact_sha256=hashlib.sha256(pe.read_bytes()).hexdigest(),
               signals=["MANAGED_METADATA_QUESTION"])
    called = {}
    def fake(command, **kwargs):
        called["argv"] = command
        return subprocess.CompletedProcess(command, 0,
            stdout=json.dumps({"artifact":{"sha256":ctx["artifact_sha256"]}}), stderr="")
    monkeypatch.setattr(router.subprocess, "run", fake)
    plan = router.decide(ctx)
    assert plan["status"] == "AUTO_RUN"
    assert router.execute(ctx, plan)["execution"] == "SUCCESS"
    assert "rea_cli_research.py" in " ".join(called["argv"])
    ctx["signals"] = ["SOURCE_BINARY_MISMATCH"]
    plan = router.decide(ctx)
    assert plan["mode"] == "pe"
    assert router.execute(ctx, plan)["execution"] == "SUCCESS"
    assert "--expected-sha256" not in called["argv"]
    assert "rea_cli_bridge.py" in " ".join(called["argv"])


def test_desktop_hashed_inventory_and_safe_output(harness, tmp_path, monkeypatch):
    ctx, _, _ = harness
    folder = tmp_path / "desktop"
    folder.mkdir()
    (folder / "host.dll").write_bytes(b"MZmanaged-fixture")
    monkeypatch.setenv("APPLAB_REA_AUTHORIZED_ARTIFACT", str(folder))
    ctx.update(artifact_kind="DESKTOP_DIR", artifact_path=str(folder),
               signals=["DESKTOP_PACKAGING_QUESTION"],
               artifact_sha256=research.inspect_tree(folder)["sha256"])
    assert router.decide(ctx)["status"] == "AUTO_RUN"
    (folder / "linked").symlink_to(harness[1])
    assert router.decide(ctx)["status"] == "BLOCKED"


def test_cli_outputs_only_decision_when_no_execution_requested(harness, tmp_path):
    ctx, _, _ = harness
    source = tmp_path / "context.json"
    source.write_text(json.dumps(ctx))
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/rea_auto_router.py"),
                           "--context", str(source)], text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "AUTO_RUN"
    assert "execution" not in result


def test_unstructured_app_symptom_selects_rea_without_manual_operation(harness):
    ctx, _, _ = harness
    ctx["signals"] = []
    ctx["symptoms"] = ["aot_snapshot_unexplained"]
    assert router.decide(ctx)["status"] == "AUTO_RUN"
    ctx.update(source_complete=True, symptoms=["source_vs_artifact_diff"])
    assert router.decide(ctx)["status"] == "AUTO_RUN"


def test_missing_jadx_prerequisite_is_not_automatically_installed(harness):
    ctx, _, _ = harness
    ctx["signals"] = []
    ctx["symptoms"] = ["manifest_permissions_diverge"]
    result = router.decide(ctx)
    assert result["mode"] == "android"
    assert result["status"] == "PROPOSE"
    assert "PINNED_JADX_ENGINE_NOT_READY" in result["reason_codes"]


def test_audit_plan_includes_routed_rea_without_replacing_runtime_checks(harness):
    from audit_orchestrator import build_plan
    ctx, _, _ = harness
    app = {"scan": {"confidence": "HIGH"},
           "product": {"stack": {"engine": "flutter"}, "feature_signals": []}}
    normal = build_plan(app)
    assert normal["rea_research"]["status"] == "SKIP"
    assert any(x["lab"] == "core-runtime" for x in normal["selected_labs"])
    escalated = build_plan(app, rea_context=ctx)
    assert escalated["rea_research"]["status"] == "AUTO_RUN"
    assert escalated["selected_lab_count"] == normal["selected_lab_count"]


def test_untrusted_context_cannot_self_authorize_execution(harness, monkeypatch):
    ctx, apk, _ = harness
    monkeypatch.delenv("APPLAB_REA_AUTHORIZED_ARTIFACT")
    result = router.decide(ctx)
    assert result["status"] == "PROPOSE"
    assert result["reason_codes"][-1] == "TRUSTED_RUNNER_BINDING_REQUIRED"
    monkeypatch.setenv("APPLAB_REA_AUTHORIZED_ARTIFACT", "/private/another-app.apk")
    result = router.decide(ctx)
    assert result["status"] == "BLOCKED"
    assert result["reason_codes"][-1] == "TRUSTED_RUNNER_SCOPE_MISMATCH"


def test_output_directory_must_be_bound_to_private_runner_root(harness, monkeypatch):
    ctx, apk, _ = harness
    ctx["output_dir"] = str(apk.parent / "outside-private")
    result = router.decide(ctx)
    assert result["status"] == "BLOCKED"
    assert result["reason_codes"][-1] == "TRUSTED_RUNNER_SCOPE_MISMATCH"
