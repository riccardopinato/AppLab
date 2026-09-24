#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil
from datetime import datetime, timezone
from pathlib import Path

PASSABLE_REGRESSION = {"PASS", "NO_BASELINE"}

def should_promote(
    payload: dict,
    approve_current: bool = False,
) -> tuple[bool, str]:
    if payload.get("result") != "PASS":
        return False, f"overall result is {payload.get('result', 'UNKNOWN')}"

    if approve_current:
        allowed = {"PASS", "WARN", "NO_BASELINE"}
        for key in ("visual_journey", "visual_qa", "visual_regression"):
            value = str(payload.get(key, "UNKNOWN"))
            if value not in allowed:
                return False, f"{key} cannot be approved: {value}"
        return True, "current visual state explicitly approved"

    if payload.get("visual_journey") != "PASS":
        return False, f"visual_journey is {payload.get('visual_journey', 'UNKNOWN')}"
    if payload.get("visual_qa") != "PASS":
        return False, f"visual_qa is {payload.get('visual_qa', 'UNKNOWN')}"
    if payload.get("visual_regression") not in PASSABLE_REGRESSION:
        return False, f"visual_regression is {payload.get('visual_regression', 'UNKNOWN')}"
    return True, "full visual gate passed"

def prepare(
    report_dir: Path,
    baseline_dir: Path,
    repository: str,
    resolved_sha: str,
    run_id: str,
    version: str,
    approve_current: bool = False,
) -> tuple[bool, str]:
    result_path = report_dir / "result.json"
    if not result_path.is_file():
        return False, "result.json is missing"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    promote, reason = should_promote(payload, approve_current)
    if not promote:
        return False, reason
    journey = report_dir / "visual-journey" / "current"
    if not journey.is_dir():
        return False, "visual journey evidence is missing"
    final_dir, launch_dir = journey / "final", journey / "launch"
    source = final_dir if (final_dir / "screenshot.png").is_file() else launch_dir
    if not (source / "screenshot.png").is_file() or not (source / "window.xml").is_file():
        return False, "baseline source checkpoint is incomplete"
    if baseline_dir.exists():
        shutil.rmtree(baseline_dir)
    baseline_dir.mkdir(parents=True)
    shutil.copy2(source / "screenshot.png", baseline_dir / "screenshot.png")
    shutil.copy2(source / "window.xml", baseline_dir / "window.xml")
    shutil.copytree(journey, baseline_dir / "journey")
    metadata = {
        "schema_version": 2,
        "applab_version": version,
        "repository": repository,
        "resolved_sha": resolved_sha,
        "workflow_run_id": run_id,
        "source_stage": source.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "promotion_policy": (
            "explicit-approval" if approve_current else "pass-only"
        ),
    }
    text = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    (baseline_dir / "metadata.json").write_text(text, encoding="utf-8")
    for checkpoint in (baseline_dir / "journey").iterdir():
        if checkpoint.is_dir():
            (checkpoint / "metadata.json").write_text(text, encoding="utf-8")
    return True, reason

def self_test() -> None:
    assert should_promote({"result":"PASS","visual_journey":"PASS","visual_qa":"PASS","visual_regression":"NO_BASELINE"})[0]
    warning = {
        "result": "PASS",
        "visual_journey": "WARN",
        "visual_qa": "PASS",
        "visual_regression": "WARN",
    }
    assert not should_promote(warning)[0]
    assert should_promote(warning, approve_current=True)[0]
    assert not should_promote(
        {
            "result": "FAIL",
            "visual_journey": "PASS",
            "visual_qa": "PASS",
            "visual_regression": "PASS",
        },
        approve_current=True,
    )[0]
    print("AppLab baseline promotion self-test PASS")

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--report-dir"); p.add_argument("--baseline-dir")
    p.add_argument("--repository",default=""); p.add_argument("--resolved-sha",default="")
    p.add_argument("--run-id",default=""); p.add_argument("--version",default="0.6.5")
    p.add_argument("--github-output",default="")
    p.add_argument("--approve-current", action="store_true")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test: self_test(); return 0
    if not a.report_dir or not a.baseline_dir: raise SystemExit("--report-dir and --baseline-dir are required")
    promote, reason=prepare(
        Path(a.report_dir),
        Path(a.baseline_dir),
        a.repository,
        a.resolved_sha,
        a.run_id,
        a.version,
        approve_current=a.approve_current,
    )
    print(f"AppLab baseline promotion: {'PROMOTE' if promote else 'SKIP'} — {reason}")
    if a.github_output:
        with Path(a.github_output).open("a",encoding="utf-8") as h:
            h.write(f"promote={'true' if promote else 'false'}\nreason={reason}\n")
    return 0
if __name__=="__main__": raise SystemExit(main())
