#!/usr/bin/env python3
"""X10-029: source-bound baseline and interaction gate for EXISTING visual_regression.

Does not capture screens, create baselines or certify visual/device results.
The trusted runner injects approved baseline lookup and AppLab visual comparator.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$")
NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
LOCALE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
ACTIONS = frozenset(("tap", "swipe", "scroll", "type"))
THEMES = frozenset(("light", "dark"))
FORM_FACTORS = frozenset(("phone", "tablet"))


class VisualCaseError(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise VisualCaseError(reason)


def sha256_file(path: Path) -> str:
    dig = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            dig.update(chunk)
    return dig.hexdigest()


def verified_capture(root: Path, capture: dict[str, Any]) -> tuple[Path, Path]:
    require(isinstance(root, Path) and root.is_dir() and not root.is_symlink(),
            "INVALID_CAPTURE_ROOT")
    require(isinstance(capture, dict), "INVALID_CAPTURE")
    paths = []
    for key, ext in (("screenshot", ".png"), ("ui", ".xml")):
        field = capture.get(key)
        digest = capture.get(key + "_sha256")
        require(isinstance(field, str) and NAME.fullmatch(field.removesuffix(ext)) is not None
                and field.endswith(ext)
                and isinstance(digest, str) and SHA256.fullmatch(digest) is not None,
                "INVALID_CAPTURE_REFERENCE")
        file = root / field
        require(file.is_file() and not file.is_symlink()
                and file.resolve().parent == root.resolve()
                and 0 < file.stat().st_size <= 25 * 1024 * 1024,
                "CAPTURE_MISSING_OR_UNSAFE")
        require(sha256_file(file) == digest, "CAPTURE_HASH_MISMATCH")
        paths.append(file)
    return (paths[0], paths[1])


def assess_case(
    request: dict[str, Any], *, baseline_root: Path, current_root: Path,
    approved_baseline_lookup: Callable[[str, str, str, dict[str, Any]], dict[str, Any] | None],
    visual_regression_evaluate: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """No PASS authority: identity and comparator results are REPORT_ONLY."""
    require(isinstance(request, dict) and request.get("schema_version") == 1,
            "INVALID_VISUAL_CASE")
    repo, sha, package, screen = (request.get(k) for k in
                                  ("repository", "source_sha", "package_id", "screen"))
    require(isinstance(repo, str) and REPO.fullmatch(repo) is not None
            and isinstance(sha, str) and SHA40.fullmatch(sha) is not None
            and isinstance(package, str) and PACKAGE.fullmatch(package) is not None
            and isinstance(screen, str) and NAME.fullmatch(screen) is not None,
            "INVALID_CASE_IDENTITY")
    profile = request.get("profile")
    require(isinstance(profile, dict) and set(profile) ==
            {"theme", "locale", "form_factor", "text_scale"}
            and profile["theme"] in THEMES and profile["form_factor"] in FORM_FACTORS
            and isinstance(profile["locale"], str)
            and LOCALE.fullmatch(profile["locale"]) is not None
            and type(profile["text_scale"]) in (float, int)
            and 0.8 <= profile["text_scale"] <= 2.0, "INVALID_DISPLAY_PROFILE")
    require(callable(approved_baseline_lookup) and callable(visual_regression_evaluate),
            "TRUSTED_VISUAL_ADAPTERS_REQUIRED")
    baseline = approved_baseline_lookup(repo, package, screen, dict(profile))
    if baseline is None:
        return {"state": "NO_BASELINE", "reason": "APPROVED_REFERENCE_MISSING",
                "repository": repo, "source_sha": sha, "screen": screen,
                "certified": False, "auto_baseline_created": False}
    require(isinstance(baseline, dict) and baseline.get("approved") is True
            and baseline.get("repository") == repo
            and baseline.get("package_id") == package and baseline.get("screen") == screen
            and baseline.get("profile") == profile
            and isinstance(baseline.get("source_sha"), str)
            and SHA40.fullmatch(baseline["source_sha"]) is not None
            and isinstance(baseline.get("review_url"), str)
            and baseline["review_url"].startswith(f"https://github.com/{repo}/pull/"),
            "BASELINE_APPROVAL_OR_IDENTITY_MISMATCH")
    baseline_files=verified_capture(baseline_root, baseline.get("capture"))
    current_files=verified_capture(current_root, request.get("capture"))
    run=request.get("workflow_run_id")
    require(type(run) is int and run > 0, "MISSING_CAPTURE_RUN_ID")
    interactions=request.get("interactions")
    require(isinstance(interactions, list) and 1 <= len(interactions) <= 50
            and all(isinstance(step, dict) and step.get("action") in ACTIONS
                    and step.get("result") == "PASS"
                    and step.get("source_sha") == sha
                    and step.get("workflow_run_id") == run
                    and step.get("capture_sha256") == request["capture"]["screenshot_sha256"]
                    for step in interactions),
            "INTERACTION_EVIDENCE_MISSING_OR_STALE")
    metadata={"resolved_sha": baseline["source_sha"],
              "reference_review_url": baseline["review_url"],
              "workflow_run_id": run, "screen": screen, "profile": profile}
    report=visual_regression_evaluate(
        baseline_files[0], baseline_files[1],
        current_files[0], current_files[1],
        package, metadata, policy=None,
    )
    require(isinstance(report, dict) and report.get("result") in
            {"PASS", "WARN", "FAIL"} and report.get("package_id") == package,
            "UNTRUSTED_VISUAL_COMPARATOR_RESULT")
    image=report.get("image_difference", {})
    require(isinstance(image, dict) and isinstance(image.get("masked_ratio"), (float, int))
            and isinstance(image.get("baseline_size"), list)
            and isinstance(image.get("current_size"), list),
            "INVALID_COMPARATOR_METRICS")
    excess = image["masked_ratio"] >= 0.50
    different_size = image["baseline_size"] != image["current_size"]
    if report["result"] == "FAIL":
        state="REGRESSION_REPORTED"
    elif report["result"] == "WARN" or excess or different_size:
        state="REQUIRES_HUMAN_VISUAL_REVIEW"
    else:
        state="REFERENCE_MATCH_REPORTED"
    return {
        "schema_version": 1, "record_type": "X10_VISUAL_BASELINE_DIFF",
        "authority": "REPORT_ONLY", "state": state, "repository": repo,
        "source_sha": sha, "baseline_source_sha": baseline["source_sha"],
        "package_id": package, "screen": screen, "profile": profile,
        "baseline_review_url": baseline["review_url"],
        "screenshot_sha256": request["capture"]["screenshot_sha256"],
        "interaction_evidence_count": len(interactions),
        "visual_comparator_result": report["result"],
        "masked_ratio": image["masked_ratio"],
        "different_dimensions": different_size,
        "findings": report.get("findings", []),
        "certified": False, "independent_runtime_verified": False,
        "auto_baseline_created": False, "false_positives_auto_approved": False,
    }
