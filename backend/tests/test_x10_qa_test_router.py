"""X10-028: structural QA routing fixtures; no real consumer builds or QA runs."""
import copy
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "qa_test_router_x10.py"
SPEC = importlib.util.spec_from_file_location("qa_test_router_x10", SOURCE)
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)

SHA = "a" * 40
REPO = "example/consumer"


def fixture(mode="fast", lane="FAST_RUNTIME", labs=("network",)):
    consumer = {"schema_version": 1, "repository": REPO, "source_sha": SHA,
                "engine": "flutter", "analysis_mode": mode, "mandatory_labs": []}
    selected = {name: name in labs for name in router.LABS}
    full = mode in ("full", "certification")
    if full:
        selected = {name: True for name in router.LABS}
    plan = {"schema_version": 2, "planner_version": "1.1.0",
            "repository": REPO, "head_sha": SHA, "requested_mode": mode,
            "mode": mode, "lane": ("CERTIFICATION" if mode == "certification" else
                                 "FULL_RUNTIME" if mode == "full" else lane),
            "selected_labs": selected, "run_static": True,
            "run_build": True, "run_runtime": True}
    return consumer, plan


def trusted_stub(plan):
    return plan


def test_fast_selected_plan_only_includes_canonical_keys():
    consumer, plan = fixture()
    result = router.route(consumer, plan, validate_plan=trusted_stub)
    assert result["gates"] == ["build_analyze", "build_unit_tests", "build_build", "network_lab"]
    assert result["test_executed"] is False
    assert result["authority"] == "ROUTE_ONLY"


def test_app_mandatory_labs_add_without_suppressing_planner_labs():
    c, p = fixture()
    c["mandatory_labs"] = ["storage", "background"]
    selected = router.route(c, p, validate_plan=trusted_stub)
    assert {"network_lab", "storage_lab", "background_lab"} <= set(selected["gates"])


def test_certification_includes_every_existing_strict_gate():
    c, p = fixture(mode="certification")
    out = router.route(c, p, validate_plan=trusted_stub)
    assert set(router.GATES) <= set(out["gates"])
    assert out["certification_granted"] is False
    assert out["requested_mode"] == "certification"


def test_full_route_delegates_with_all_canonical_strict_gates():
    c, p = fixture(mode="full")
    request = router.route(c, p, validate_plan=trusted_stub)
    assert set(router.GATES).issubset(request["gates"])
    assert {"maestro", "visual_qa", "visual_regression", "visual_journey"} <= set(
        request["gates"])
    assert request["requested_mode"] == "full"
    assert request["effective_mode"] == "full"
    calls = []
    def runner(route):
        calls.append(tuple(route["gates"]))
        return {"repository": REPO, "source_sha": SHA,
                "analysis_mode": "full",
                "run_url": "https://github.com/riccardopinato/AppLab/actions/runs/12345",
                "gates": dict.fromkeys(route["gates"], "PASS")}
    receipt = router.delegate(request, runner=runner)
    assert len(calls) == 1
    assert receipt["state"] == "RUNNER_REPORTED_ONLY"
    assert receipt["all_reported_pass"] is True
    assert receipt["independent_provenance_verified"] is False
    assert receipt["certification_granted"] is False


def test_planner_escalated_fast_to_full_is_complete_and_not_certified():
    c, p = fixture(mode="fast")
    p["mode"] = "full"
    p["lane"] = "FULL_RUNTIME"
    p["selected_labs"] = {name: True for name in router.LABS}
    request = router.route(c, p, validate_plan=trusted_stub)
    assert request["requested_mode"] == "fast"
    assert request["effective_mode"] == "full"
    assert set(router.GATES).issubset(request["gates"])
    def runner(route):
        return {"repository": REPO, "source_sha": SHA,
                "analysis_mode": "full",
                "run_url": "https://github.com/example/consumer/actions/runs/909",
                "gates": dict.fromkeys(route["gates"], "PASS")}
    receipt = router.delegate(request, runner=runner)
    assert receipt["state"] == "RUNNER_REPORTED_ONLY"
    assert receipt["independent_provenance_verified"] is False
    assert receipt["certification_granted"] is False


def test_full_mode_not_reduced_by_proposed_selector():
    c, p = fixture(mode="full")
    p["selected_labs"]["network"] = False
    with pytest.raises(router.RouterError, match="COVERAGE_DOWNGRADE_FORBIDDEN"):
        router.route(c, p, validate_plan=trusted_stub)


def test_certification_downgrade_denied():
    c, p = fixture(mode="certification")
    p["mode"] = "fast"
    with pytest.raises(router.RouterError, match="PLANNER_MODE_DOWNGRADE"):
        router.route(c, p, validate_plan=trusted_stub)


@pytest.mark.parametrize("mutate,reason", [
    ("wrong_sha", "PLANNER_SOURCE_IDENTITY_MISMATCH"),
    ("wrong_repo", "PLANNER_SOURCE_IDENTITY_MISMATCH"),
    ("unknown_lab", "UNKNOWN_CONSUMER_LAB"),
    ("non_boolean", "INVALID_LAB_SELECTION"),
    ("mode_mismatch", "PLANNER_MODE_MISMATCH"),
    ("missing_flag", "INVALID_EXECUTION_FLAGS"),
    ("no_validator", "TRUSTED_PLANNER_REQUIRED"),
])
def test_source_and_policy_fail_closed(mutate, reason):
    c, p = fixture()
    validator = trusted_stub
    if mutate == "wrong_sha":
        p["head_sha"] = "b" * 40
    elif mutate == "wrong_repo":
        p["repository"] = "other/app"
    elif mutate == "unknown_lab":
        c["mandatory_labs"] = ["not_a_lab"]
    elif mutate == "non_boolean":
        p["selected_labs"]["network"] = 1
    elif mutate == "mode_mismatch":
        p["requested_mode"] = "full"
    elif mutate == "missing_flag":
        p.pop("run_build")
    elif mutate == "no_validator":
        validator = None
    with pytest.raises(router.RouterError, match=reason):
        router.route(c, p, validate_plan=validator)


def test_delegates_to_trusted_runner_but_does_not_mint_pass():
    c, p = fixture()
    route = router.route(c, p, validate_plan=trusted_stub)
    calls = []
    def runner(request):
        calls.append(request["source_sha"])
        return {"repository": REPO, "source_sha": SHA,
                "analysis_mode": "fast",
                "run_url": "https://github.com/example/consumer/actions/runs/42",
                "gates": dict.fromkeys(request["gates"], "PASS")}
    reported = router.delegate(route, runner=runner)
    assert calls == [SHA]
    assert reported["all_reported_pass"] is True
    assert reported["state"] == "RUNNER_REPORTED_ONLY"
    assert reported["independent_provenance_verified"] is False
    assert reported["certification_granted"] is False


def test_missing_gate_does_not_become_pass():
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    def runner(route):
        return {"repository": REPO, "source_sha": SHA, "analysis_mode": "fast",
                "run_url": "", "gates": {"network_lab": "PASS"}}
    with pytest.raises(router.RouterError, match="MISSING_OR_INVALID_GATE_RESULT"):
        router.delegate(request, runner=runner)


def test_reported_skip_is_blocker_not_success():
    c, p = fixture(mode="certification")
    request = router.route(c, p, validate_plan=trusted_stub)
    def runner(route):
        results = dict.fromkeys(route["gates"], "PASS")
        results["visual_regression"] = "NO_BASELINE"
        return {"repository": REPO, "source_sha": SHA,
                "analysis_mode": "certification", "run_url": "",
                "gates": results}
    reported = router.delegate(request, runner=runner)
    assert "visual_regression" in reported["unpassed_gates"]
    assert reported["state"] == "BLOCKED_OR_FAIL_REPORTED"


@pytest.mark.parametrize("state", ["WARN", "SKIPPED"])
def test_app_lab_existing_nonpassing_states_are_preserved_as_blockers(state):
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    def runner(route):
        gates = dict.fromkeys(route["gates"], "PASS")
        gates["network_lab"] = state
        return {"repository": REPO, "source_sha": SHA, "analysis_mode": "fast",
                "run_url": "https://github.com/example/consumer/actions/runs/44", "gates": gates}
    result = router.delegate(request, runner=runner)
    assert result["gate_results"]["network_lab"] == state
    assert result["unpassed_gates"] == ["network_lab"]
    assert result["state"] == "BLOCKED_OR_FAIL_REPORTED"
    assert result["certification_granted"] is False


def test_wrong_executor_sha_denied():
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    def runner(route):
        return {"repository": REPO, "source_sha": "b" * 40,
                "analysis_mode": "fast", "run_url": "",
                "gates": dict.fromkeys(route["gates"], "PASS")}
    with pytest.raises(router.RouterError, match="EXECUTOR_PROVENANCE_MISMATCH"):
        router.delegate(request, runner=runner)



def test_empty_gates_cannot_report_a_fake_pass():
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    request["gates"] = []
    called = []
    with pytest.raises(router.RouterError, match="INVALID_GATE_SET"):
        router.delegate(request, runner=lambda _: called.append(1) or {})
    assert called == []


def test_quality_free_and_full_coverage_missing_routes_rejected():
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    request["gates"] = ["network_lab"]
    with pytest.raises(router.RouterError, match="MISSING_REQUIRED_QUALITY_GATES"):
        router.delegate(request, runner=lambda _: {})
    c, p = fixture(mode="certification")
    request = router.route(c, p, validate_plan=trusted_stub)
    request["gates"].remove("network_lab")
    with pytest.raises(router.RouterError, match="FULL_QA_COVERAGE_REQUIRED"):
        router.delegate(request, runner=lambda _: {})


@pytest.mark.parametrize("untrusted_url", [
    "https://github.com/other/app/actions/runs/42",
    "https://github.com/example/consumer/actions/runs/42?fake=1",
    "https://github.com/example/consumer/actions/runs/not_a_number",
    "https://github.com/example/consumer.evil/actions/runs/42",
])
def test_foreign_or_forged_ci_run_url_never_attested(untrusted_url):
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    def runner(route):
        return {"repository": REPO, "source_sha": SHA, "analysis_mode": "fast",
                "run_url": untrusted_url, "gates": dict.fromkeys(route["gates"], "PASS")}
    with pytest.raises(router.RouterError, match="RUN_SOURCE_REPOSITORY_MISMATCH"):
        router.delegate(request, runner=runner)


def test_app_lab_hosted_runner_link_is_valid_but_never_certifies():
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    def runner(route):
        return {"repository": REPO, "source_sha": SHA, "analysis_mode": "fast",
                "run_url": "https://github.com/riccardopinato/AppLab/actions/runs/42",
                "gates": dict.fromkeys(route["gates"], "PASS")}
    result = router.delegate(request, runner=runner)
    assert result["state"] == "RUNNER_REPORTED_ONLY"
    assert result["all_reported_pass"] is True
    assert result["independent_provenance_verified"] is False
    assert result["certification_granted"] is False


def test_empty_runner_url_never_counts_as_complete_pass_even_with_pass_labels():
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    def runner(route):
        return {"repository": REPO, "source_sha": SHA, "analysis_mode": "fast",
                "run_url": "", "gates": dict.fromkeys(route["gates"], "PASS")}
    receipt = router.delegate(request, runner=runner)
    assert receipt["all_reported_pass"] is False
    assert receipt["state"] == "BLOCKED_OR_FAIL_REPORTED"
    assert receipt["unpassed_gates"] == ["TRUSTED_RUN_REFERENCE_MISSING"]
    assert receipt["certification_granted"] is False


def test_forged_pre_authorized_route_is_rejected_before_runner():
    c, p = fixture()
    request = router.route(c, p, validate_plan=trusted_stub)
    request["test_executed"] = True
    with pytest.raises(router.RouterError, match="INVALID_ROUTE"):
        router.delegate(request, runner=lambda _: {})


def test_native_android_uses_lint_not_flutter_analyze():
    c, p = fixture()
    c["engine"] = "native_android"
    request = router.route(c, p, validate_plan=trusted_stub)
    assert "build_lint" in request["gates"]
    assert "build_analyze" not in request["gates"]
