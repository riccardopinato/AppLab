"""X10-033: synthetic source/CI fixtures, no consumer release or store authority."""
import copy
import unittest

from scripts.x10_release_decision_gate import assess_release_decision, DecisionGateError

SHA = "a" * 40
APK = "b" * 64
RUN = 19393
REPO = "example/demo"
PKG = "com.example.demo"
NAMES = ("AppLab CI", "AppLab CodeQL", "Repository Governance Audit",
         "Canonical Runtime Fixture Build", "Emulator Self Test",
         "AppLab True Autonomous App Review v5.3.5", "Live Emulator Browser E2E")
STAGES = ("SOURCE_BUILD_BOUND", "STATIC_BUILD_ASSURANCE", "TRUSTED_RUNTIME",
          "EVIDENCE_GRAPH", "RISK_BASED_VALIDATION", "CERTIFICATION")


def make():
    ident = {"repository": REPO, "source_sha": SHA, "apk_sha256": APK,
             "package_id": PKG, "version_code": "11",
             "workflow_run_id": RUN, "workflow_repository": "riccardopinato/AppLab"}
    base = {"repository": REPO, "source_sha": SHA, "package_id": PKG}
    # Canonical X10-028 delegate output intentionally omits package_id.
    qa = {"repository": REPO, "source_sha": SHA,
          "record_type": "APP_FACTORY_X10_QA_RECEIPT",
          "analysis_mode": "certification", "independent_provenance_verified": False,
          "certification_granted": False, "store_release_granted": False,
          "state": "RUNNER_REPORTED_ONLY",
          "run_url": "https://github.com/riccardopinato/AppLab/actions/runs/" + str(RUN),
          "gate_results": {"visual_qa": "PASS", "performance_lab": "PASS"}}
    visual = [{**base, "record_type": "X10_VISUAL_BASELINE_DIFF",
               "authority": "REPORT_ONLY", "screen": "home",
               "profile": {"theme": "light", "locale": "en", "form_factor": "phone",
                           "text_scale": 1.0},
               "state": "REFERENCE_MATCH_REPORTED", "certified": False,
               "false_positives_auto_approved": False}]
    perf = {**base, "record_type": "X10_PERF_A11Y_REVIEW_RECEIPT",
            "authority": "REPORT_ONLY", "apk_sha256": APK,
            "workflow_run_id": RUN, "consumer_certified": False,
            "independent_provenance_verified": False,
            "state": "BENCHMARK_MATCH_REPORTED", "baseline": "APPROVED_REFERENCE_REPORTED",
            "accessibility_findings": [], "regression_codes": []}
    signing = {**base, "record_type": "X10_SIGNED_RELEASE_PROVENANCE_CANDIDATE",
               "authority": "SOURCE_BOUND_ONLY", "state": "PENDING_INDEPENDENT_REMOTE_AND_DEVICE_EVIDENCE",
               "version_code": "11", "workflow_run_id": RUN,
               "store_ready": False, "production_released": False,
               "artifacts": [{"kind": "APK", "sha256": APK}]}
    assurance = {"record_type": "AUTONOMOUS_RELEASE_ASSURANCE",
                 "authority": "APPLAB_RELEASE_ASSURANCE", "state": "PASS",
                 "identity": {"repository": REPO, "resolved_sha": SHA,
                              "artifact_sha256": APK, "package_id": PKG,
                              "version_code": "11"},
                 "stages": [{"key": k, "required": True, "state": "PASS"} for k in STAGES]}
    checks = [{"name": n, "source_sha": SHA, "status": "completed",
               "conclusion": "success", "run_id": i + 1} for i, n in enumerate(NAMES)]
    return {"schema_version": 1, "identity": ident, "workflow_checks": checks,
            "qa": qa, "visual": visual, "performance": perf,
            "signing": signing, "release_assurance": assurance}


def valid_provenance(kind, report):
    return {"verified": True, "repository": REPO, "source_sha": SHA,
            "apk_sha256": APK, "workflow_run_id": RUN}


class ReleaseDecisionTests(unittest.TestCase):
    def assess(self, x, resolver=valid_provenance):
        return assess_release_decision(x, trusted_evidence_lookup=resolver)

    def test_synthetic_all_pass_still_requires_human_and_no_release(self):
        out = self.assess(make())
        self.assertEqual(out["state"], "INPUTS_REPORTED_READY_FOR_HUMAN_REVIEW")
        self.assertFalse(out["release_authorized"])
        self.assertFalse(out["auto_store_publish"])
        self.assertFalse(out["certification_granted"])
        self.assertFalse(out["physical_device_verification_granted"])

    def test_missing_review_provenance_blocks_even_if_reports_pass(self):
        def untrusted(kind, report):
            return {**valid_provenance(kind, report), "verified": False}
        self.assertEqual(self.assess(make(), untrusted)["state"], "BLOCKED_OR_UNVERIFIED")

    def test_changed_sha_in_workflow_fails_closed(self):
        x = make()
        x["workflow_checks"][1]["source_sha"] = "c" * 40
        with self.assertRaisesRegex(DecisionGateError, "WORKFLOW_HEAD_OR_CHECKLIST_INVALID"):
            self.assess(x)

    def test_missing_required_workflow_fails(self):
        x = make()
        x["workflow_checks"] = x["workflow_checks"][:-1]
        with self.assertRaisesRegex(DecisionGateError, "REQUIRED_WORKFLOW_CHECKS_MISSING"):
            self.assess(x)

    def test_ci_failure_blocks(self):
        x = make()
        x["workflow_checks"][0]["conclusion"] = "failure"
        self.assertIn("CI_NOT_GREEN:AppLab CI", self.assess(x)["blockers"])

    def test_qa_failure_blocks(self):
        x = make()
        x["qa"]["gate_results"]["visual_qa"] = "WARN"
        self.assertIn("QA_NOT_ALL_REPORTED_PASS", self.assess(x)["blockers"])

    def test_noncertification_route_rejected(self):
        x = make()
        x["qa"]["analysis_mode"] = "fast"
        with self.assertRaisesRegex(DecisionGateError, "QA_RECEIPT_INVALID_OR_NON_CERTIFICATION"):
            self.assess(x)

    def test_canonical_qa_without_package_id_is_accepted(self):
        x = make()
        self.assertNotIn("package_id", x["qa"])
        self.assertEqual(self.assess(x)["state"],
                         "INPUTS_REPORTED_READY_FOR_HUMAN_REVIEW")

    def test_same_screen_light_and_dark_profile_are_both_allowed(self):
        x = make()
        dark = copy.deepcopy(x["visual"][0])
        dark["profile"]["theme"] = "dark"
        x["visual"].append(dark)
        self.assertEqual(self.assess(x)["state"],
                         "INPUTS_REPORTED_READY_FOR_HUMAN_REVIEW")

    def test_duplicate_screen_and_profile_rejected(self):
        x = make()
        x["visual"].append(copy.deepcopy(x["visual"][0]))
        with self.assertRaisesRegex(DecisionGateError, "VISUAL_RECEIPT_INVALID"):
            self.assess(x)

    def test_visual_warning_blocks(self):
        x = make()
        x["visual"][0]["state"] = "REQUIRES_HUMAN_VISUAL_REVIEW"
        self.assertIn("VISUAL_REVIEW_REQUIRED:home:light", self.assess(x)["blockers"])

    def test_tampered_signed_apk_fails(self):
        x = make()
        x["signing"]["artifacts"][0]["sha256"] = "d" * 64
        with self.assertRaisesRegex(DecisionGateError, "SIGNING_SOURCE_OR_ARTIFACT_MISMATCH"):
            self.assess(x)

    def test_performance_baseline_absent_blocks(self):
        x = make()
        x["performance"]["baseline"] = "MISSING"
        self.assertIn("PERFORMANCE_OR_A11Y_REVIEW_REQUIRED", self.assess(x)["blockers"])

    def test_canonical_assurance_blocked(self):
        x = make()
        x["release_assurance"]["state"] = "BLOCKED"
        x["release_assurance"]["stages"][-1]["state"] = "BLOCKED"
        self.assertIn("CANONICAL_ASSURANCE_NOT_PASS", self.assess(x)["blockers"])

    def test_missing_canonical_stage_fails(self):
        x = make()
        x["release_assurance"]["stages"].pop()
        with self.assertRaisesRegex(DecisionGateError, "CANONICAL_REQUIRED_STAGE_MISSING"):
            self.assess(x)

    def test_signing_wrong_source_fails(self):
        x = make()
        x["signing"]["source_sha"] = "d" * 40
        with self.assertRaisesRegex(DecisionGateError, "SIGNING_IDENTITY_MISMATCH"):
            self.assess(x)

    def test_external_verifier_cross_artifact_drift_rejected(self):
        def drift(kind, report):
            return {**valid_provenance(kind, report), "apk_sha256": "d" * 64}
        with self.assertRaisesRegex(DecisionGateError, "EXTERNAL_EVIDENCE_IDENTITY_MISMATCH"):
            self.assess(make(), drift)

    def test_caller_cannot_add_auto_publish(self):
        x = make()
        x["auto_publish"] = True
        with self.assertRaisesRegex(DecisionGateError, "INVALID_DECISION_SCHEMA"):
            self.assess(x)


if __name__ == "__main__":
    unittest.main()
