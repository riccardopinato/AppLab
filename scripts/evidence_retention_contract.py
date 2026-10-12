#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_VERSION = "1.0"

# GitHub artifact TTL is the garbage-collection mechanism for bounded CI evidence.
# Release-critical evidence is kept at the repository's current long-retention
# ceiling; transient diagnostics remain bounded so storage cannot grow without limit.
POLICY = (
    (".github/workflows/production-certification.yml", "Upload certified release bundle", "RELEASE_CRITICAL", 90),
    (".github/workflows/production-certification.yml", "Upload final certification evidence", "RELEASE_CRITICAL", 90),
    (".github/workflows/production-certification.yml", "Upload certification history", "RELEASE_CRITICAL", 90),
    (".github/workflows/physical-evidence-hub.yml", "Upload physical evidence attestation", "RELEASE_CRITICAL", 90),
    (".github/workflows/cross-app-verification.yml", "Upload paired verification evidence", "RELEASE_CRITICAL", 90),
    (".github/workflows/autonomous-app-review-v31.yml", "Upload repository-wide longitudinal history", "LONGITUDINAL", 90),
    (".github/workflows/repo-watcher.yml", "Upload central history", "ADVISORY_CALIBRATION", 7),
    (".github/workflows/live-emulator-self-test.yml", "Upload live browser evidence", "INFRA_DIAGNOSTIC", 7),
)

def step_block(text: str, step_name: str) -> str:
    match = re.search(
        rf"^(?P<indent>\s*)- name:\s*{re.escape(step_name)}\s*$",
        text,
        re.MULTILINE,
    )
    if not match:
        raise ValueError(f"missing workflow step: {step_name}")
    indent = match.group("indent")
    rest = text[match.end():]
    next_step = re.search(
        rf"^{re.escape(indent)}- name:\s*",
        rest,
        re.MULTILINE,
    )
    end = match.end() + (next_step.start() if next_step else len(rest))
    return text[match.start():end]

def retention_days(block: str) -> int:
    match = re.search(r"^\s*retention-days:\s*(\d+)\s*$", block, re.MULTILINE)
    if not match:
        raise ValueError("upload step has no numeric retention-days")
    return int(match.group(1))

def validate(root: Path = ROOT) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    cache: dict[str, str] = {}
    for relative, step_name, evidence_class, minimum_days in POLICY:
        text = cache.get(relative)
        if text is None:
            path = root / relative
            if not path.is_file():
                raise ValueError(f"missing policy workflow: {relative}")
            text = path.read_text(encoding="utf-8")
            cache[relative] = text
        block = step_block(text, step_name)
        if "uses: actions/upload-artifact@" not in block:
            raise ValueError(f"{relative} / {step_name} is not an upload-artifact step")
        days = retention_days(block)
        if days < minimum_days:
            raise ValueError(
                f"{relative} / {step_name}: {days}d retention is below "
                f"{evidence_class} minimum {minimum_days}d"
            )
        results.append(
            {
                "workflow": relative,
                "step": step_name,
                "class": evidence_class,
                "retention_days": days,
                "minimum_days": minimum_days,
            }
        )
    return results

def self_test() -> None:
    good = """
      - name: Upload critical
        uses: actions/upload-artifact@deadbeef
        with:
          retention-days: 90
      - name: Next step
        run: true
"""
    assert retention_days(step_block(good, "Upload critical")) == 90
    bad = good.replace("retention-days: 90", "retention-days: 7")
    assert retention_days(step_block(bad, "Upload critical")) == 7
    try:
        step_block(good, "Missing")
    except ValueError:
        pass
    else:
        raise AssertionError("missing step must fail closed")
    print("AppLab evidence retention contract self-test PASS")

def main() -> int:
    results = validate()
    for row in results:
        print(
            f"{row['class']}: {row['workflow']} / {row['step']} "
            f"{row['retention_days']}d >= {row['minimum_days']}d"
        )
    print(f"AppLab evidence retention policy v{POLICY_VERSION} PASS")
    return 0

if __name__ == "__main__":
    if "--self-test" in __import__("sys").argv:
        self_test()
    else:
        raise SystemExit(main())
