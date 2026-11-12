#!/usr/bin/env python3
"""X10-028: per-consumer QA route into EXISTING AppLab test machinery.

No new QA runner, certification authority, APK builder, or device emulator.
The AppLab smart-test planner and certification gate remain source of truth.
The dispatcher is an injected trusted existing AppLab executor.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

# CI imports this module by absolute file path with only backend/ on sys.path.
# Resolve the adjacent canonical AppLab gate, not a duplicate local gate list.
_spec = spec_from_file_location("_x10_app_lab_certification_gate",
                            Path(__file__).with_name("certification_gate.py"))
if _spec is None or _spec.loader is None:
    raise ImportError("AppLab certification gate is not importable")
_gate_module = module_from_spec(_spec)
_spec.loader.exec_module(_gate_module)
STRICT_GATES = _gate_module.STRICT_GATES

SHA40 = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ENGINES = frozenset({"flutter", "native_android"})
MODES = frozenset({"fast", "full", "certification"})
RUN_STATES = frozenset({"PASS", "FAIL", "ERROR", "BLOCKED", "WARN", "SKIPPED",
                        "NOT_RUN", "NO_BASELINE", "UNKNOWN"})
GATES = tuple(key for key, _ in STRICT_GATES)
LABS = tuple(key.removesuffix("_lab") for key in GATES if key.endswith("_lab"))
ADDITIONAL = ("maestro", "visual_qa", "visual_regression", "visual_journey")
QUALITY = {"flutter": ("build_analyze", "build_unit_tests", "build_build"),
           "native_android": ("build_lint", "build_unit_tests", "build_build")}


class RouterError(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise RouterError(reason)


def route(
    consumer: dict[str, Any], plan: dict[str, Any],
    *, validate_plan: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Prepare exact-source run request, preserving AppLab FAST/FULL/CERT."""
    _require(callable(validate_plan), "TRUSTED_PLANNER_REQUIRED")
    _require(isinstance(consumer, dict) and isinstance(plan, dict), "INVALID_INPUT")
    _require(consumer.get("schema_version") == 1, "UNSUPPORTED_CONSUMER")
    repo, sha = consumer.get("repository"), consumer.get("source_sha")
    engine, mode = consumer.get("engine"), consumer.get("analysis_mode")
    mandatory = consumer.get("mandatory_labs", [])
    _require(isinstance(repo, str) and REPOSITORY.fullmatch(repo) is not None
             and isinstance(sha, str) and SHA40.fullmatch(sha) is not None,
             "INVALID_CONSUMER_IDENTITY")
    _require(engine in ENGINES and mode in MODES, "UNSUPPORTED_ENGINE_OR_MODE")
    _require(isinstance(mandatory, list) and len(mandatory) <= len(LABS)
             and len(mandatory) == len(set(mandatory))
             and all(isinstance(item, str) and item in LABS for item in mandatory),
             "UNKNOWN_CONSUMER_LAB")
    try:
        validated = validate_plan(plan)
    except (ValueError, TypeError, KeyError) as exc:
        raise RouterError("INVALID_APPLAB_PLAN") from exc
    _require(isinstance(validated, dict) and validated.get("schema_version") == 2,
             "UNSUPPORTED_PLANNER_CONTRACT")
    _require(validated.get("repository") == repo and validated.get("head_sha") == sha,
             "PLANNER_SOURCE_IDENTITY_MISMATCH")
    _require(validated.get("requested_mode") == mode, "PLANNER_MODE_MISMATCH")
    effective = validated.get("mode")
    _require(effective in MODES and (mode == "fast" or effective == mode),
             "PLANNER_MODE_DOWNGRADE")
    selected = validated.get("selected_labs")
    _require(isinstance(selected, dict) and set(selected) == set(LABS)
             and all(type(value) is bool for value in selected.values()), "INVALID_LAB_SELECTION")
    lane = validated.get("lane")
    _require(lane in {"NO_RUNTIME_CHANGE", "STATIC_ONLY", "FAST_RUNTIME",
                      "FULL_RUNTIME", "CERTIFICATION"}, "INVALID_QA_LANE")
    run_static, run_build, run_runtime = (validated.get(k) for k in
                                          ("run_static", "run_build", "run_runtime"))
    _require(all(type(x) is bool for x in (run_static, run_build, run_runtime)),
             "INVALID_EXECUTION_FLAGS")
    _require(not (run_build and not run_static) and not (run_runtime and not run_build),
             "INVALID_EXECUTION_DEPENDENCY")
    if effective in {"full", "certification"}:
        _require(all(selected.values()) and all((run_static, run_build, run_runtime)),
                 "COVERAGE_DOWNGRADE_FORBIDDEN")
    if mode == "certification":
        _require(effective == "certification" and lane == "CERTIFICATION",
                 "CERTIFICATION_DOWNGRADE_FORBIDDEN")

    picked = set(mandatory)
    picked.update(name for name, required in selected.items() if required and run_runtime)
    if effective in {"full", "certification"}:
        picked.update(LABS)
    selected_gates = {f"{name}_lab" for name in picked}
    if effective == "certification":
        selected_gates.update(ADDITIONAL)
    quality = list(QUALITY[engine][:2]) if run_static or picked or effective == "certification" else []
    if run_build or picked or effective == "certification":
        quality.append(QUALITY[engine][2])
    gates = [*quality, *(key for key in GATES if key in selected_gates)]
    _require(all(gate in (*GATES, *QUALITY["flutter"], *QUALITY["native_android"])
                 for gate in gates), "ROUTER_GATE_NOT_CANONICAL")
    return {
        "schema_version": 1, "record_type": "APP_FACTORY_X10_QA_ROUTE",
        "authority": "ROUTE_ONLY", "repository": repo, "source_sha": sha,
        "engine": engine, "requested_mode": mode, "effective_mode": effective,
        "lane": lane, "gates": gates, "selected_labs": sorted(picked),
        "planner_version": validated.get("planner_version", ""),
        "plan_source_sha": validated["head_sha"],
        "state": "PENDING_TRUSTED_EXECUTOR", "test_executed": False,
        "certification_granted": False, "store_release_granted": False,
    }


def delegate(
    request: dict[str, Any],
    *, runner: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Invoke *existing trusted AppLab runner* and wrap unverified report.

    A fake runner in a unit test does not count as a real QA invocation.
    Even a PASS-labeled upstream result remains REPORT_ONLY until independent
    provenance validation and AppLab certification gates.
    """
    _require(callable(runner), "TRUSTED_EXECUTOR_REQUIRED")
    _require(isinstance(request, dict)
             and request.get("schema_version") == 1
             and request.get("record_type") == "APP_FACTORY_X10_QA_ROUTE"
             and request.get("authority") == "ROUTE_ONLY"
             and request.get("state") == "PENDING_TRUSTED_EXECUTOR"
             and request.get("certification_granted") is False
             and request.get("store_release_granted") is False
             and request.get("test_executed") is False
             and isinstance(request.get("repository"), str)
             and REPOSITORY.fullmatch(request["repository"]) is not None
             and isinstance(request.get("source_sha"), str)
             and SHA40.fullmatch(request["source_sha"]) is not None
             and request.get("engine") in ENGINES
             and request.get("requested_mode") in MODES
             and request.get("effective_mode") in MODES
             and (request["requested_mode"] == "fast"
                  or request["requested_mode"] == request["effective_mode"]),
             "INVALID_ROUTE")
    expected = request.get("gates")
    _require(isinstance(expected, list) and bool(expected)
             and len(expected) == len(set(expected))
             and all(isinstance(x, str) and x in (*GATES, *QUALITY["flutter"],
             *QUALITY["native_android"]) for x in expected), "INVALID_GATE_SET")
    # A caller-crafted route containing only a few arbitrary canonical names
    # is not a valid exact-mode test plan. Never accept empty/quality-free
    # dispatches as passing QA evidence.
    required_quality = QUALITY[request["engine"]][:2]
    _require(all(gate in expected for gate in required_quality),
             "MISSING_REQUIRED_QUALITY_GATES")
    if request["effective_mode"] in {"full", "certification"}:
        _require(set(GATES).issubset(expected)
                 and QUALITY[request["engine"]][2] in expected,
                 "FULL_QA_COVERAGE_REQUIRED")
    observed = runner(request)
    _require(isinstance(observed, dict)
             and observed.get("repository") == request["repository"]
             and observed.get("source_sha") == request["source_sha"]
             and observed.get("analysis_mode") == request["effective_mode"],
             "EXECUTOR_PROVENANCE_MISMATCH")
    gates = observed.get("gates")
    _require(isinstance(gates, dict) and set(gates) == set(expected)
             and all(type(v) is str and v in RUN_STATES for v in gates.values()),
             "MISSING_OR_INVALID_GATE_RESULT")
    run_url = observed.get("run_url")
    _require(isinstance(run_url, str), "INVALID_RUN_REFERENCE")
    if run_url:
        match = re.fullmatch(
            r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/actions/runs/[1-9][0-9]*"
            r"(?:/attempts/[1-9][0-9]*)?", run_url,
        )
        # AppLab legitimately runs QA against a different consumer repo.
        # Only the pinned AppLab orchestrator or the consumer itself may own
        # a reported GitHub Actions URL; this is a syntax check, NOT proof
        # the run's commit, artifact or tester is trusted.
        allowed_run_repos = {request["repository"].casefold(),
                             "riccardopinato/applab"}
        _require(match is not None
                 and match.group(1).casefold() in allowed_run_repos,
                 "RUN_SOURCE_REPOSITORY_MISMATCH")
    # No URL means the injected runner's statements are NOT usable as
    # executable proof, even if it reports all PASS.
    blocked = sorted(k for k, value in gates.items() if value != "PASS")
    if not run_url:
        blocked.append("TRUSTED_RUN_REFERENCE_MISSING")
    return {"schema_version": 1, "record_type": "APP_FACTORY_X10_QA_RECEIPT",
            "state": "RUNNER_REPORTED_ONLY" if not blocked else "BLOCKED_OR_FAIL_REPORTED",
            "repository": request["repository"], "source_sha": request["source_sha"],
            "engine": request["engine"], "analysis_mode": request["effective_mode"],
            "run_url": run_url, "gate_results": dict(gates),
            "unpassed_gates": blocked, "all_reported_pass": not blocked,
            "independent_provenance_verified": False,
            "certification_granted": False, "store_release_granted": False}
