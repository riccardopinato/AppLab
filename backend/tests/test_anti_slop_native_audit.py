"""Conservative Unslop native source auditor; regression tests."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "anti_slop_native_audit.py"
SPEC = importlib.util.spec_from_file_location("anti_slop_native_audit", MODULE_PATH)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_surface_opt_in_and_cross_stack_patterns(tmp_path):
    dart = tmp_path / "lib" / "today.dart"
    dart.parent.mkdir()
    dart.write_text(
        'Text("One. Big. Thing.");\n'
        'Text("Synced · Live · Now");\n'
        'Text("Bar chart of monthly results");\n'
        'FontWeight.w900;\n'
        'LinearGradient(colors: []);\n'
        'rememberInfiniteTransition();\n'
        'Text("🧽");\n', encoding="utf-8",
    )
    kotlin = tmp_path / "app" / "src" / "main" / "Sample.kt"
    kotlin.parent.mkdir(parents=True)
    kotlin.write_text(
        'Text(text = eyebrow.uppercase());\n'
        'Text(text = subtitle);\n'
        'Badge(label = Text("LIVE"));\n'
        'Text("01 // Features");\n', encoding="utf-8",
    )
    plain = audit.audit([tmp_path])
    assert {"U1", "U2", "U3", "U6", "U8", "U9", "U11", "U12"} <= set(plain["counts"])
    assert "U17" not in plain["counts"]
    assert "U19" not in plain["counts"]
    assert "U20" not in plain["counts"]
    styled = audit.audit([tmp_path], surface=True, source_sha="f" * 40)
    assert {"U17", "U19", "U20"} <= set(styled["counts"])
    assert styled["source_sha"] == "f" * 40
    assert styled["visual_review"] == "NOT_VERIFIED"
    assert styled["physical_review"] == "NOT_VERIFIED"
    assert all(row["confidence"] == "REVIEW_REQUIRED" for row in styled["findings"])


def test_excludes_generated_tests_and_non_native_files(tmp_path):
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "fake.dart").write_text('Text("🧽");')
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "fake.kt").write_text('FontWeight.Black')
    (tmp_path / "index.html").write_text('<b>LIVE</b>')
    (tmp_path / "clean.dart").write_text('Text("Hello");')
    result = audit.audit([tmp_path], surface=True)
    assert result["files_scanned"] == 1
    assert result["total_candidates"] == 0


def test_cli_json_and_threshold_are_explicit(tmp_path):
    native = tmp_path / "home.kt"
    native.write_text('Text(text = eyebrow.uppercase())\n', encoding="utf-8")
    cmd = [sys.executable, str(MODULE_PATH), str(native)]
    ordinary = subprocess.run(cmd, capture_output=True, text=True, check=True)
    payload = json.loads(ordinary.stdout)
    assert payload["counts"]["U1"] == 1
    assert payload["status"] == "ADVISORY_NOT_CERTIFICATION"
    blocked = subprocess.run(cmd + ["--max", "0"], capture_output=True, text=True)
    assert blocked.returncode == 1
    assert "U1" in blocked.stdout


def test_scanning_external_repo_keeps_target_relative_paths(tmp_path):
    repo = tmp_path / "external_checkout"
    (repo / "lib" / "feature_a").mkdir(parents=True)
    (repo / "lib" / "feature_b").mkdir(parents=True)
    (repo / "lib" / "feature_a" / "home.dart").write_text('Text("One. Big. Thing.");')
    (repo / "lib" / "feature_b" / "home.dart").write_text('Text("One. Big. Thing.");')
    report = audit.audit([repo])
    paths = {row["path"] for row in report["findings"]}
    assert paths == {"lib/feature_a/home.dart", "lib/feature_b/home.dart"}


def test_large_locale_is_scanned_with_correct_offsets(tmp_path):
    path = tmp_path / "localizations.arb"
    path.write_text('\n'.join(f'\"message{i}\": \"🧽\"' for i in range(2000)), encoding="utf-8")
    report = audit.audit([path])
    assert report["files_scanned"] == 1
    assert report["counts"]["U11"] == 2000
    assert report["findings"][-1]["line"] == 2000
