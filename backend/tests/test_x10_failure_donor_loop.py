"""X10-045: source-bound recurrent failure fixtures only, no actual QA run."""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = load("x10_failure_donor_loop")
p3 = load("pattern3_discovery_v57c")
packager = load("factory_feedback_packager_v58d")
SHA = "a" * 40


def rows(*, count=3, code="CRASH", test="qa/runtime"):
    return [{"repository": "example/app", "source_sha": SHA,
             "workflow_run_id": 800 + i, "test_key": test,
             "failure_code": code, "category": "RUNTIME",
             "evidence_sha256": format(i + 100, "064x"),
             "run_url": f"https://github.com/example/app/actions/runs/{800+i}",
             "result": "FAIL"} for i in range(count)]


def verify(row):
    return {**{k: row[k] for k in ("repository", "source_sha", "workflow_run_id",
                                   "evidence_sha256", "result", "test_key",
                                   "category", "failure_code")}, "verified": True}


def run(receipts, verifier=verify, pattern=p3.build_report, package=packager.build_packages):
    return gate.analyze(receipts, trusted_failure_verifier=verifier,
                        existing_pattern_observations=p3.queue_observations,
                        existing_pattern3_builder=pattern,
                        existing_feedback_packager=package,
                        read_only_reuse_catalog={"repositories": []})


def test_three_independent_failures_generate_proposal_not_promotion():
    result = run(rows())
    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["occurrences"] == 3
    assert candidate["replay_plan"]["state"] == "NOT_EXECUTED"
    assert all(r["source_sha"] == SHA for r in candidate["source_references"])
    assert result["donor_promoted"] is False
    assert result["golden_promoted"] is False
    assert result["runtime_failure_reproduced"] is False


def test_distinct_failures_with_no_repeated_pattern_do_not_promote():
    data = rows()
    for i, row in enumerate(data):
        row["failure_code"] = f"ERR_{i}"
    result = run(data)
    assert result["candidate_count"] == 0


def test_duplicate_workflow_test_cannot_inflate_counts():
    data = rows()
    data[2]["workflow_run_id"] = data[1]["workflow_run_id"]
    data[2]["run_url"] = data[1]["run_url"]
    with pytest.raises(gate.FailureDonorLoopError, match="REPLAY_OR_DUPLICATE_FAILURE"):
        run(data)


def test_same_run_different_tests_cannot_count_three_occurrences():
    data = rows()
    for i, row in enumerate(data):
        row["workflow_run_id"] = 800
        row["run_url"] = "https://github.com/example/app/actions/runs/800"
        row["test_key"] = f"qa/runtime{i}"
    with pytest.raises(gate.FailureDonorLoopError, match="REPLAY_OR_DUPLICATE_FAILURE"):
        run(data)


def test_same_evidence_hash_reused_across_runs_is_rejected():
    data = rows()
    data[2]["evidence_sha256"] = data[1]["evidence_sha256"]
    with pytest.raises(gate.FailureDonorLoopError, match="REPLAY_OR_DUPLICATE_FAILURE"):
        run(data)


def test_external_proof_must_bind_failure_code_category_and_test_key():
    def wrong_test(row):
        return {**verify(row), "test_key": "qa/different"}
    with pytest.raises(gate.FailureDonorLoopError,
                       match="FAILURE_PROVENANCE_NOT_INDEPENDENTLY_VERIFIED"):
        run(rows(), verifier=wrong_test)
    def wrong_code(row):
        return {**verify(row), "failure_code": "OTHER"}
    with pytest.raises(gate.FailureDonorLoopError,
                       match="FAILURE_PROVENANCE_NOT_INDEPENDENTLY_VERIFIED"):
        run(rows(), verifier=wrong_code)


def test_repo_capitalization_does_not_inflate_distinct_repos():
    data = rows()
    data[0]["repository"] = "Example/App"
    data[0]["run_url"] = "https://github.com/Example/App/actions/runs/800"
    data[1]["repository"] = "EXAMPLE/APP"
    data[1]["run_url"] = "https://github.com/EXAMPLE/APP/actions/runs/801"
    outcome = run(data)
    assert outcome["candidates"][0]["suggested_classification"] == "DONOR"
    assert {r["repository"] for r in outcome["candidates"][0]["source_references"]} == {"example/app"}


def test_injected_untrusted_evidence_rejected():
    with pytest.raises(gate.FailureDonorLoopError,
                       match="FAILURE_PROVENANCE_NOT_INDEPENDENTLY_VERIFIED"):
        run(rows(), verifier=lambda row: {**verify(row), "verified": False})


def test_source_sha_drift_rejected_by_external_verifier():
    with pytest.raises(gate.FailureDonorLoopError,
                       match="FAILURE_PROVENANCE_NOT_INDEPENDENTLY_VERIFIED"):
        run(rows(), verifier=lambda row: {**verify(row), "source_sha": "b" * 40})


def test_out_of_scope_url_rejected():
    data = rows()
    data[0]["run_url"] = "https://evil.example/actions/runs/800"
    with pytest.raises(gate.FailureDonorLoopError, match="FAILURE_SOURCE_OR_TAXONOMY_INVALID"):
        run(data)


def test_failure_text_cannot_contain_credentials_or_freeform():
    data = rows()
    data[0]["test_key"] = "password=123"
    with pytest.raises(gate.FailureDonorLoopError, match="FAILURE_SOURCE_OR_TAXONOMY_INVALID"):
        run(data)


def test_pass_is_not_a_failure_occurrence():
    data = rows()
    data[0]["result"] = "PASS"
    with pytest.raises(gate.FailureDonorLoopError, match="FAILURE_SOURCE_OR_TAXONOMY_INVALID"):
        run(data)


def test_fake_pattern_threshold_rejected():
    def poison(q):
        r = p3.build_report(q)
        r["candidates"][0]["occurrences"] = 8
        return r
    with pytest.raises(gate.FailureDonorLoopError, match="PATTERN3_THRESHOLD_OR_PROVENANCE_DRIFT"):
        run(rows(), pattern=poison)


def test_package_auto_promotion_rejected():
    def poison(pattern, catalog):
        value = packager.build_packages(pattern, catalog)
        value["packages"][0]["promotion_evidence"]["auto_promote"] = True
        return value
    with pytest.raises(gate.FailureDonorLoopError, match="FEEDBACK_PACKAGE_DUPLICATE_OR_UNSAFE"):
        run(rows(), package=poison)


def test_mixed_repositories_propose_factory_process_not_auto_certify():
    data = rows()
    data[2]["repository"] = "example/second"
    data[2]["run_url"] = "https://github.com/example/second/actions/runs/802"
    res = run(data)
    assert res["candidates"][0]["suggested_classification"] == "FACTORY PROCESS"
    assert res["candidates"][0]["golden_admission"] == "NOT_GRANTED"


def test_two_failures_are_insufficient_for_proposal():
    with pytest.raises(gate.FailureDonorLoopError,
                       match="INSUFFICIENT_REPEATED_FAILURE_EVIDENCE"):
        run(rows(count=2))
