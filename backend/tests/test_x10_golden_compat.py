"""X10-018 fixtures: do not use synthetic results to certify real Golden software."""
import copy
import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "scripts" / "golden_compat_harness_x10.py"
SPEC = importlib.util.spec_from_file_location("golden_compat_harness_x10", MODULE)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

SHA = "a" * 40
DONOR = "b" * 40
CONSUMER = "c" * 40
URL = "https://github.com/example/repo/actions/runs/123"


def fixture():
    manifest = {
        "package_name": "factory_theme", "package_state": "CONSUMER_VERIFIED",
        "factory_sha": SHA, "version": "1.2.0",
        "golden": {"registry_sha": SHA},
        "provenance": {"donor_repo": "example/donor", "donor_sha": DONOR,
                       "source_files": ["lib/theme.dart"]},
        "license": "INTERNAL_APPROVED",
        "compatibility": {"tested_pairs": []},
        "tests": {"donor_ci_urls": [URL + "1"], "consumer_ci_urls": [URL + "2"]},
        "consumers": [{"repo": "example/app", "source_sha": CONSUMER,
                       "approved": True, "test_url": URL + "2"}],
        "release": {"publish_authorized": False, "rollback_version": "1.1.0"}
    }
    receipts = [
        {"kind": "DONOR", "repository": "example/donor", "source_sha": DONOR,
         "package_name": "factory_theme", "version": "1.2.0", "result": "PASS",
         "run_url": URL + "1", "dart": "3.6.0", "flutter": "3.27.0"},
        {"kind": "CONSUMER", "repository": "example/app", "source_sha": CONSUMER,
         "package_name": "factory_theme", "version": "1.2.0", "result": "PASS",
         "run_url": URL + "2", "dart": "3.6.0", "flutter": "3.27.0"},
        {"kind": "ROLLBACK", "repository": "example/donor", "source_sha": DONOR,
         "package_name": "factory_theme", "version": "1.2.0", "result": "PASS",
         "run_url": URL + "3", "dart": "3.6.0", "flutter": "3.27.0",
         "from_version": "1.2.0", "to_version": "1.1.0"}
    ]
    manifest["compatibility"]["tested_pairs"] = [
        {"dart": "3.6.0", "flutter": "3.27.0", "test_url": r["run_url"]}
        for r in receipts
    ]
    return manifest, receipts


def test_structural_positive_but_never_certifies():
    manifest, receipts = fixture()
    result = mod.assess(manifest, receipts)
    assert result["state"] == "STRUCTURAL_PASS_REVIEW_REQUIRED"
    assert not result["automatic_promotion"]
    assert not result["receipt_provenance_verified"]
    assert not result["flutter_executed"]


@pytest.mark.parametrize("mutation,needle", [
    ("design", "SOURCE_NOT_EXTRACTED"),
    ("unreviewed_license", "SOURCE_OR_LICENSE_NOT_ADMITTED"),
    ("wrong_donor_sha", "DONOR_MISMATCH"),
    ("wrong_consumer_sha", "CONSUMER_MISMATCH"),
    ("missing_rollback", "ROLLBACK_TEST_MISSING"),
    ("rollback_wrong_target", "ROLLBACK_MISMATCH"),
    ("unknown_sdk", "SDK_PAIR_NOT_RECORDED"),
    ("missing_consumer", "CONSUMER_TEST_MISSING"),
    ("failed_ci", "NO_MATCHING_PASS"),
    ("forged_url", "CONSUMER_MISMATCH"),
    ("duplicate", "DUPLICATE_RECEIPT"),
    ("publish", "PUBLISH_NOT_AUTHORIZED_BY_HARNESS"),
])
def test_fail_closed(mutation, needle):
    m, r = fixture()
    if mutation == "design":
        m["package_state"] = "DESIGN_ONLY"
    elif mutation == "unreviewed_license":
        m["license"] = "NOT_REVIEWED"
    elif mutation == "wrong_donor_sha":
        r[0]["source_sha"] = "f" * 40
    elif mutation == "wrong_consumer_sha":
        r[1]["source_sha"] = "f" * 40
    elif mutation == "missing_rollback":
        r = r[:2]
    elif mutation == "rollback_wrong_target":
        r[2]["to_version"] = "1.3.0"
    elif mutation == "unknown_sdk":
        r[1]["flutter"] = "9.99.0"
    elif mutation == "missing_consumer":
        r = [r[0], r[2]]
    elif mutation == "failed_ci":
        r[1]["result"] = "FAIL"
    elif mutation == "forged_url":
        r[1]["run_url"] = URL + "99"
    elif mutation == "duplicate":
        r.append(copy.deepcopy(r[1]))
    elif mutation == "publish":
        m["release"]["publish_authorized"] = True
    with pytest.raises(ValueError, match=needle):
        mod.assess(m, r)


def test_certified_requires_two_distinct_consumers():
    m, r = fixture()
    m["package_state"] = "CERTIFIED_MULTI_CONSUMER"
    with pytest.raises(ValueError, match="TWO_CONSUMERS_REQUIRED"):
        mod.assess(m, r)


def test_donor_pair_is_not_rollback_and_source_must_be_pinned():
    m, r = fixture()
    m["factory_sha"] = "not-a-sha"
    with pytest.raises(ValueError, match="SOURCE_NOT_PINNED"):
        mod.assess(m, r)
