#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "5.3.2"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_version_alignment() -> None:
    backend = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    require(
        f'APP_VERSION = "{EXPECTED_VERSION}"' in backend,
        "backend APP_VERSION is not aligned with AppLab release",
    )
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    require(package.get("version") == EXPECTED_VERSION, "frontend package version drift")
    require(lock.get("version") == EXPECTED_VERSION, "frontend lock version drift")
    require(
        (lock.get("packages") or {}).get("", {}).get("version") == EXPECTED_VERSION,
        "frontend root lock package version drift",
    )
    package_contract = (ROOT / "scripts/package_build_contract.py").read_text(encoding="utf-8")
    require(
        f'"applab_version": "{EXPECTED_VERSION}"' in package_contract,
        "packaged build contract version drift",
    )
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    studio_graph = (ROOT / "scripts/studio_evidence_graph.py").read_text(encoding="utf-8")
    require(
        f'STUDIO_VERSION = "{EXPECTED_VERSION}"' in studio,
        "Studio snapshot version drift",
    )
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    require(
        f'"version":"{EXPECTED_VERSION}"' in ci,
        "CI backend health assertion version drift",
    )
    emulator = (ROOT / ".github/workflows/emulator-self-test.yml").read_text(
        encoding="utf-8"
    )
    require(
        f'APPLAB_VERSION="{EXPECTED_VERSION}"' in emulator
        and 'APPLAB_VERSION="4.1.0"' not in emulator,
        "Emulator self-test report identity is stale",
    )


def check_local_controller_boundary() -> None:
    live = (ROOT / "docker-compose.live.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    require(
        "APPLAB_BIND_HOST: ${APPLAB_BIND_HOST:-127.0.0.1}" in live,
        "Live controller must bind to loopback by default",
    )
    require("APPLAB_BIND_HOST" in dockerfile, "backend bind host must be configurable")
    require(
        "get.maestro.mobile.dev" not in dockerfile,
        "remote curl|bash style Maestro installer is forbidden",
    )
    require("MAESTRO_SHA256" in dockerfile, "Maestro release bytes must be hash-pinned")


def check_actions_pinned() -> None:
    problems: list[str] = []
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"\buses:\s*([^\s#]+)", line)
            if not match:
                continue
            target = match.group(1)
            if target.startswith("./") or target.startswith("docker://"):
                continue
            if "@" not in target:
                problems.append(f"{path.relative_to(ROOT)}:{number}: missing ref: {target}")
                continue
            ref = target.rsplit("@", 1)[1]
            if not SHA40.fullmatch(ref):
                problems.append(
                    f"{path.relative_to(ROOT)}:{number}: external action is not SHA-pinned: {target}"
                )
    require(not problems, "\n".join(problems))


def check_trusted_review_contract() -> None:
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )
    for needle in (
        "lineage_ref:",
        "base_sha:",
        "--lineage-ref",
        "--base-sha",
        "Build Studio snapshot",
        "scripts/studio_snapshot.py",
        "studio.json",
        "Build Evidence Graph",
        "scripts/evidence_graph.py",
        "evidence-graph.md",
    ):
        require(needle in workflow, f"trusted review missing audit-hardening contract: {needle}")


def check_schema_forwarding() -> None:
    control = (ROOT / "backend/app/control_center.py").read_text(encoding="utf-8")
    studio = (ROOT / "backend/app/studio.py").read_text(encoding="utf-8")
    require(
        "normalized_summary = dict(summary)" in control,
        "Control Center backend must preserve forward-compatible summary fields",
    )
    require(
        "normalized_summary = dict(summary)" in studio,
        "Studio backend must preserve forward-compatible summary fields",
    )


def check_no_floating_self_reference() -> None:
    wrapper = (ROOT / ".github/workflows/verify-flutter.yml").read_text(encoding="utf-8")
    require("@main" not in wrapper, "reusable AppLab wrapper must not float on @main")
    require(
        "uses: ./.github/workflows/external-project-runner.yml" in wrapper,
        "Flutter wrapper must bind to the same AppLab revision",
    )



def check_residual_hardening_contract() -> None:
    trusted = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    app = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    control = (ROOT / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")
    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))

    require(
        'cron: "17 3 1 * *"' in trusted,
        "trusted review must refresh longitudinal history before artifact expiry",
    )
    require(
        "github.event.pull_request.head.sha" not in trusted.split("concurrency:", 1)[1].split("jobs:", 1)[0]
        and "github.event.pull_request.number" in trusted.split("concurrency:", 1)[1].split("jobs:", 1)[0]
        and "cancel-in-progress: true" in trusted.split("concurrency:", 1)[1].split("jobs:", 1)[0],
        "trusted review concurrency must cancel stale commits using stable PR identity",
    )
    require(
        "tests/intelligence/intelligence_corpus_test.py" in ci,
        "independent intelligence regression corpus must run in CI",
    )
    require(
        "pip-audit==2.10.1" in ci and "npm audit --audit-level=high" in ci,
        "Python and npm dependency security audits must remain blocking CI checks",
    )
    require(
        "scripts/maintainability_budget.py" in ci,
        "maintainability growth budget must remain a CI invariant",
    )
    require(
        'VITE_APPLAB_READ_ONLY === "true"' in app
        and "staticBase" in control
        and "VITE_APPLAB_READ_ONLY=true" in str(vercel.get("buildCommand", "")),
        "public Web Preview must remain read-only and detached from the privileged controller",
    )
    require(
        (ROOT / ".github/workflows/repository-governance-audit.yml").is_file(),
        "repository governance audit workflow is required",
    )
    require(
        (ROOT / ".github/workflows/codeql.yml").is_file(),
        "CodeQL SAST workflow is required",
    )
    require(
        (ROOT / ".github/workflows/web-preview.yml").is_file(),
        "read-only Web Preview deployment workflow is required",
    )
    require(
        (ROOT / "integration/CANONICAL_WORKFLOWS.md").is_file(),
        "canonical/compatibility workflow registry is required",
    )


def check_evidence_graph_contract() -> None:
    graph = (ROOT / "scripts/evidence_graph.py").read_text(encoding="utf-8")
    longitudinal = (ROOT / "scripts/longitudinal_product_intelligence.py").read_text(
        encoding="utf-8"
    )
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    studio_graph = (ROOT / "scripts/studio_evidence_graph.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )
    flutter_runner = (ROOT / ".github/workflows/external-project-runner.yml").read_text(
        encoding="utf-8"
    )
    native_runner = (
        ROOT / ".github/workflows/external-native-android-runner.yml"
    ).read_text(encoding="utf-8")
    for node_type in (
        "Project",
        "Revision",
        "BuildArtifact",
        "File",
        "Component",
        "Capability",
        "Surface",
        "Journey",
        "Finding",
        "Claim",
        "Evidence",
        "Experiment",
        "Result",
    ):
        require(f'"{node_type}"' in graph, f"Evidence Graph missing node type {node_type}")
    for query in (
        "unverified-capabilities",
        "recurring-findings",
        "regressions",
        "impact",
        "stale-evidence",
        "lifecycle",
        "history",
        "evidence",
        "subject",
    ):
        require(query in graph, f"Evidence Graph missing query contract {query}")
    require(
        'first_observed_sha_is_not_proof_of_introducing_commit' in graph,
        "Evidence Graph must not convert first observation into causal blame",
    )
    require(
        'impact_path_is_not_root_cause_proof' in graph
        and 'resolution_observation_is_not_fix_causality' in graph
        and 'current_evidence_is_not_invalidated_only_because_its_source_file_changed' in graph,
        "Evidence Graph 2 must keep impact, resolution and freshness non-causal",
    )
    for relation in (
        "FILE_IN_COMPONENT",
        "COMPONENT_SUPPORTS_CAPABILITY",
        "CAPABILITY_OBSERVED_ON_SURFACE",
        "SURFACE_IN_JOURNEY",
        "CHANGE_INVALIDATES_EVIDENCE",
    ):
        require(relation in graph, f"Evidence Graph 2 missing impact relation {relation}")
    require(
        '"freshness"' in graph
        and '"INVALIDATED"' in graph
        and "affected_by_current_change" in graph,
        "Evidence Graph 2 must expose selective freshness invalidation",
    )
    require(
        '"STALE", "HISTORICAL", "INVALIDATED"' in graph
        and "results.append(row)" in graph,
        "stale-evidence query must return every inspectable non-current evidence node",
    )
    require(
        "repository_path_prevalidated" in graph
        and "file_node = file_nodes.get(path_value)" in graph,
        "generated report/runtime paths must not manufacture repository File nodes",
    )
    require(
        'or bool(node["attributes"].get("dependency_impacted"))' in graph
        and '"origin_kind"' in graph,
        "dependency-impacted files must participate as explicit impact roots",
    )
    require(
        '"resolved_history"' in longitudinal
        and '"resolved_tombstones"' in longitudinal
        and "resolved_tombstones=report" in longitudinal
        and '"REVISION_CONFIRMS_RESOLVED_FINDING"' in graph,
        "resolved findings must persist as longitudinal tombstones and remain queryable",
    )
    require(
        "Build Evidence Graph" in workflow and "evidence-graph.md" in workflow,
        "trusted review must build and publish Evidence Graph",
    )
    require(
        'baseline_sha: ${{ needs.resolve.outputs.base_sha }}' in workflow,
        "Autonomous Review must provide the trusted PR base SHA to change planning",
    )
    for runner in (flutter_runner, native_runner):
        require(
            "Fetch change baseline commit" in runner
            and "if: inputs.baseline_sha != ''" in runner,
            "FULL/FAST runners must fetch an explicitly supplied change baseline",
        )
    require(
        'evidence-graph.json' in studio,
        "Studio must ingest Evidence Graph summary evidence",
    )
    require(
        "invalidated_evidence" in studio_graph
        and "top_impact_paths" in studio_graph
        and "finding_lifecycle" in studio_graph,
        "Studio Evidence Graph projection must expose v4.6 freshness/impact/lifecycle",
    )


def check_project_adapter_contract() -> None:
    adapter = (ROOT / "scripts/project_adapter.py").read_text(encoding="utf-8")
    universal = (ROOT / ".github/workflows/universal-project-runner.yml").read_text(
        encoding="utf-8"
    )
    packager = (ROOT / "scripts/package_build_contract.py").read_text(encoding="utf-8")
    validator = (ROOT / "scripts/validate_build_contract.py").read_text(encoding="utf-8")
    integration = (ROOT / ".github/workflows/project-adapter-integration.yml").read_text(
        encoding="utf-8"
    )
    for needle in (
        'ADAPTER_VERSION = "4.3.0"',
        '"release_artifact_pattern"',
        '"journeys"',
        '"physical_validation"',
        '"profile_fingerprint"',
        "resolved_sha",
    ):
        require(needle in adapter, f"v4.3 project adapter missing contract: {needle}")
    require(
        "scripts/project_adapter.py" in universal
        and "project-profile.json" in universal
        and "needs.discover.outputs.resolved_sha" in universal
        and "profile_fingerprint" in universal,
        "Universal Runner must freeze and route the v4.3 canonical project profile",
    )
    require(
        "Target-authored adapter metadata may only make certification stricter" in packager
        and "applab.project.json" in packager,
        "target adapter metadata must not weaken certification policy",
    )
    require(
        "confined_repo_path" in adapter
        and "TOOLCHAIN_PATTERNS" in adapter
        and "unsafe or unsupported format" in adapter,
        "adapter paths and toolchain metadata must remain declarative and repository-confined",
    )
    require(
        "confined_repo_source" in packager
        and "traverses a symlink" in packager,
        "target evidence packaging must reject symlink traversal",
    )
    require(
        "Declared package id does not match APK package id" in validator
        and 'for field in ("package_id", "version_name", "version_code")' in validator
        and 'raise ValueError(f"APK {field} is missing")' in validator,
        "trusted contract validation must bind configured package and exact APK version identity",
    )
    require(
        "riccardopinato/CamperBoss" in integration
        and "riccardopinato/Battery_Guard" in integration,
        "v4.3 adapter must keep real App Factory integration coverage",
    )


def check_release_reality_contract() -> None:
    reality = (ROOT / "scripts/release_reality.py").read_text(encoding="utf-8")
    finalizer = (ROOT / "scripts/finalize_external_result.py").read_text(
        encoding="utf-8"
    )
    trusted = (ROOT / ".github/workflows/trusted-apk-verifier.yml").read_text(
        encoding="utf-8"
    )
    autonomous = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )
    contract = (ROOT / "scripts/contract_fingerprint.py").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    for level in (
        "IMPLEMENTED",
        "STATICALLY_CHECKED",
        "TESTED",
        "CI_GREEN",
        "ARTIFACT_BUILT",
        "TRUSTED_RUNTIME_VERIFIED",
        "PHYSICAL_DEVICE_VERIFIED",
        "DISTRIBUTION_VERIFIED",
        "STORE_READY",
        "PRODUCTION_RELEASED",
    ):
        require(level in reality, f"Release Reality missing ladder level {level}")
    for state in ("PASS", "FAIL", "BLOCKED", "NOT_VERIFIED"):
        require(state in reality, f"Release Reality missing state {state}")
    require(
        "same_bytes_verified" in reality
        and "rebuilt_bytes_require_new_evidence" in reality
        and "sha256_file" in reality,
        "Release Reality must enforce same-artifact semantics",
    )
    require(
        '"signing_identity_state"' in reality
        and "Release signing identity is not yet verified" in reality
        and "required_build_identity" in reality,
        "ARTIFACT_BUILT must remain distinct from later release-signing proof",
    )
    require(
        '"runtime_result"' in finalizer
        and 'payload["runtime_result"]' in finalizer
        and 'result.get("runtime_result") or result.get("result")' in reality,
        "Release Reality must preserve runtime truth across downstream gate failures",
    )
    require(
        "Release Reality repository binding mismatch" in reality
        and "Release Reality source SHA binding mismatch" in reality
        and "Release Reality workflow run binding mismatch" in reality
        and "Release Reality trusted AppLab SHA binding mismatch" in reality,
        "Release Reality must fail closed on provenance binding mismatches",
    )
    require(
        "Build Release Reality record" in trusted
        and "scripts/release_reality.py" in trusted
        and "release-reality.md" in trusted,
        "trusted verifier must generate and publish Release Reality",
    )
    require(
        trusted.index("Build Release Reality record")
        < trusted.index("Bind trusted runtime evidence"),
        "Release Reality must be generated before Trusted Evidence Manifest hashing",
    )
    require(
        'cp "$GITHUB_WORKSPACE/trusted-runtime/release-reality.json" "$PROJECT_DIR/"'
        in autonomous,
        "Autonomous Review must preserve Release Reality for downstream Studio evidence",
    )
    require(
        '"scripts/release_reality.py"' in contract,
        "Release Reality must participate in verification contract fingerprints",
    )
    require(
        "python scripts/release_reality.py --self-test" in ci,
        "CI must gate Release Reality self-test",
    )


def check_physical_evidence_contract() -> None:
    physical = (ROOT / "scripts/physical_evidence.py").read_text(encoding="utf-8")
    hub = (ROOT / ".github/workflows/physical-evidence-hub.yml").read_text(
        encoding="utf-8"
    )
    trusted = (ROOT / ".github/workflows/trusted-apk-verifier.yml").read_text(
        encoding="utf-8"
    )
    certification = (ROOT / "scripts/certification_gate.py").read_text(
        encoding="utf-8"
    )
    reality = (ROOT / "scripts/release_reality.py").read_text(encoding="utf-8")
    universal = (ROOT / ".github/workflows/universal-project-runner.yml").read_text(
        encoding="utf-8"
    )
    contract = (ROOT / "scripts/contract_fingerprint.py").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    require(
        'AUTHORITY = "APPLAB_PHYSICAL_EVIDENCE_HUB"' in physical
        and 'WORKFLOW_PATH = ".github/workflows/physical-evidence-hub.yml"' in physical
        and "verify_hub_run" in physical
        and 'head_branch != "main"' in physical,
        "physical evidence must originate from the trusted AppLab main workflow",
    )
    require(
        "exact_artifact_match" in physical
        and '"artifact_sha256": (' in physical
        and "Physical evidence exact APK bytes do not match build contract" in physical
        and "Physical evidence hub run attempt binding mismatch" in physical
        and 'artifact_name": f"applab-physical-evidence-{run_id}-{run_attempt}"' in physical
        and "record digest mismatch" in physical,
        "physical evidence must be byte-bound, rerun-bound and tamper-evident",
    )
    require(
        "operator_attested_hashes" in physical
        and "reference_bytes_verified_by_hub" in physical
        and "evidence_reference_bytes_verified" in physical,
        "physical evidence must disclose reference-byte verification limits",
    )
    require(
        "Require trusted main" in hub
        and "refs/heads/main" in hub
        and "applab-physical-evidence-" in hub
        and "github.run_attempt" in hub,
        "Physical Evidence Hub workflow must only attest from main and publish a rerun-safe artifact",
    )
    require(
        "Verify physical evidence hub run provenance" in trusted
        and "Download trusted physical evidence attestation" in trusted
        and "Bind physical evidence to exact APK" in trusted
        and "physical_evidence_run_id" in trusted
        and "--expected-hub-run-attempt" in trusted
        and "if: always() && steps.verify.outcome == 'success'" in trusted,
        "Trusted APK Verifier must independently retrieve physical evidence, bind the exact rerun attempt and preserve negative evidence manifests",
    )
    require(
        "physical_evidence=physical_evidence" in certification
        and '"real_device": {' in certification
        and '"record_id": physical_record_id' in certification,
        "certification must consume bound physical-device evidence",
    )
    require(
        "physical_evidence_summary" in reality
        and '"physical_evidence": {' in reality
        and '"required_capabilities": sorted(required_physical_capabilities)' in reality,
        "Release Reality must surface trusted physical evidence",
    )
    require(
        "physical_evidence_run_id" in universal,
        "Universal Runner must expose the physical evidence run id",
    )
    require(
        '"scripts/physical_evidence.py"' in contract,
        "Physical Evidence Hub must participate in verification fingerprints",
    )
    require(
        "python scripts/physical_evidence.py --self-test" in ci,
        "CI must gate Physical Evidence Hub self-test",
    )


def check_execution_acceleration_contract() -> None:
    fixture = (ROOT / ".github/workflows/runtime-fixture-build.yml").read_text(
        encoding="utf-8"
    )
    live = (ROOT / ".github/workflows/live-emulator-self-test.yml").read_text(
        encoding="utf-8"
    )
    emulator = (ROOT / ".github/workflows/emulator-self-test.yml").read_text(
        encoding="utf-8"
    )
    autonomous = (
        ROOT / ".github/workflows/autonomous-app-review-v31.yml"
    ).read_text(encoding="utf-8")
    flutter_runner = (ROOT / ".github/workflows/external-project-runner.yml").read_text(
        encoding="utf-8"
    )
    native_runner = (
        ROOT / ".github/workflows/external-native-android-runner.yml"
    ).read_text(encoding="utf-8")
    trusted = (ROOT / ".github/workflows/trusted-apk-verifier.yml").read_text(
        encoding="utf-8"
    )
    metrics = (ROOT / "scripts/pipeline_metrics.py").read_text(encoding="utf-8")
    restore_fixture = (ROOT / "scripts/restore_runtime_fixture.sh").read_text(
        encoding="utf-8"
    )
    restore_build = (ROOT / "scripts/restore_build_contract.sh").read_text(
        encoding="utf-8"
    )
    doctor = (ROOT / "scripts/applab_doctor.py").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    canonical_build = "gradle -p selftest :app:assembleDebug --stacktrace"
    require(
        canonical_build in fixture,
        "canonical runtime fixture workflow must own the self-test APK build",
    )
    require(
        "retention-days: 30" in fixture,
        "canonical runtime fixture must survive the GitHub workflow rerun window",
    )
    require(
        'APPLAB_FIXTURE_WAIT_SECONDS:-1320' in restore_fixture,
        "runtime consumers must wait beyond the canonical producer timeout",
    )
    require(
        canonical_build not in live and canonical_build not in emulator,
        "runtime consumers must not rebuild the canonical self-test APK",
    )
    for consumer in (live, emulator):
        require(
            "scripts/restore_runtime_fixture.sh" in consumer,
            "runtime gate must restore and validate the canonical fixture",
        )
        require(
            "scripts/build_runtime_fixture_fallback.sh" in consumer
            and "github.event_name == 'workflow_dispatch'" in consumer,
            "runtime gate must provide a workflow_dispatch fixture fallback",
        )
    for required_workflow in (live, emulator, autonomous):
        require(
            "pull_request:\n    paths:" not in required_workflow
            and "name: Required-check scope" in required_workflow
            and "needs: scope" in required_workflow
            and "needs.scope.outputs.run == 'true'" in required_workflow,
            "required status-check workflows must always instantiate on pull requests and scope expensive work at job level",
        )
    require(
        "inputs.flutter_version != ''" in flutter_runner,
        "floating Flutter channels must not reuse content-addressed build contracts",
    )
    for runner in (flutter_runner, native_runner):
        require(
            'build-input "package-id:' in runner
            and 'build-input "maestro-flow:' in runner,
            "runtime contract inputs must participate in build identity",
        )
        require(
            'toolchain "java:${{ steps.java_identity.outputs.version }}"' in runner
            and 'toolchain "java:${{ inputs.java_version }}"' not in runner,
            "build reuse must be keyed by the resolved Java runtime patch",
        )
        require(
            runner.count('toolchain "runner:${RUNNER_OS:-unknown}:${RUNNER_ARCH:-unknown}:${ImageOS:-unknown}:${ImageVersion:-unknown}"') >= 2,
            "initial and post-build execution identities must include the hosted runner image",
        )
        require(
            "BUILD_CACHE_APPLICABLE" in runner,
            "cache telemetry must distinguish not-applicable from MISS",
        )
        require(
            "analysis_plan_sha256" in runner
            and "REGENERATED_EXECUTION_KEY" in runner
            and 'applab-build-contract/analysis-plan.json' in runner,
            "post-build execution evidence must be regenerated from sealed trusted inputs",
        )
        for needle in (
            "scripts/execution_acceleration.py",
            "Restore content-addressed build contract",
            "scripts/restore_build_contract.sh",
            "--expected-applab-sha",
            "--trusted-applab-sha",
            "retention-days: 7",
        ):
            require(needle in runner, f"accelerated runner missing invariant: {needle}")
    require(
        "execution-plan.json" in trusted,
        "trusted verifier must preserve acceleration evidence",
    )
    require(
        '"N/A" if c.get("applicable") is False' in trusted,
        "trusted summary must preserve build-cache not-applicable state",
    )
    require(
        'for ARTIFACT_ID in "${ARTIFACT_IDS[@]}"' in restore_build
        and "rows[:20]" in restore_build
        and 'miss "no-valid-artifact"' in restore_build,
        "build reuse must search multiple matching artifacts before rebuilding",
    )
    require(
        '"build_cache_hit"' in metrics
        and '"build_cache_applicable"' in metrics
        and '"execution_key"' in metrics,
        "pipeline metrics must expose build reuse evidence and applicability",
    )
    acceleration = (ROOT / "scripts/execution_acceleration.py").read_text(
        encoding="utf-8"
    )
    require(
        "semantic_keys = (" in acceleration
        and '"learning_profile"' not in acceleration.split("semantic_keys = (", 1)[1].split(")", 1)[0],
        "execution identity must exclude historical learning telemetry",
    )
    require(
        '"cached_quality_timings_ignored"' in metrics
        and 'timings={} if build_cache_hit is True else producer_timings' in metrics,
        "cache-hit metrics must exclude producer-run quality timings",
    )
    doctor = (ROOT / "scripts/applab_doctor.py").read_text(encoding="utf-8")
    require(
        "python-runtime" in doctor
        and "sys.executable" in doctor
        and "docker-compose-v2" in doctor
        and 'docker_path, "compose", "version"' in doctor,
        "AppLab Doctor must use the running Python interpreter and require Compose v2 for full profile",
    )
    require(
        "artifact lookup failed; retrying within wait budget" in restore_fixture
        and "artifact download failed; retrying within wait budget" in restore_fixture
        and "artifact unzip failed; retrying within wait budget" in restore_fixture
        and "if gh api" in restore_fixture,
        "runtime fixture transport must tolerate transient GitHub API/download failures",
    )
    require(
        '"docker-daemon"' in doctor
        and '"info", "--format"' in doctor
        and 'docker_daemon["required"] = profile == "full"' in doctor,
        "full AppLab Doctor profile must verify Docker daemon readiness",
    )
    require(
        "python scripts/execution_acceleration.py --self-test" in ci
        and "python scripts/build_reuse_eligibility.py --self-test" in ci
        and "python scripts/applab_doctor.py --self-test" in ci,
        "CI must gate acceleration, hermetic build reuse eligibility and doctor self-tests",
    )


def check_certification_studio_contract() -> None:
    cockpit = (ROOT / "scripts/certification_studio.py").read_text(encoding="utf-8")
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")
    require(
        'STUDIO_VERSION = "4.7.0"' in cockpit
        and '"read_only": True' in cockpit
        and '"why_not_certified"' in cockpit
        and 'CERTIFICATION_PREREQUISITE_STAGES' in cockpit
        and 'row.get("key") or row.get("stage")' in cockpit
        and 'project_dir / "certification.json"' in cockpit
        and '"why_not_certified_truncated": False' in cockpit,
        "Certification Studio must expose an explicit read-only why-not-certified projection",
    )
    require(
        "certification_studio.project_from_directory" in studio
        and '"release_cockpit": release_cockpit' in studio,
        "Studio snapshot must source Release Cockpit from the read-only Release Reality loader",
    )
    require(
        "Why is this not CERTIFIED?" in frontend
        and "release_cockpit.certification_status" in frontend
        and "release_cockpit.certification_authority" in frontend
        and "release_cockpit.artifact?.same_bytes_verified" in frontend,
        "Control Center must expose release blockers and exact-artifact state",
    )
    forbidden = (
        "certification_score",
        "overall_release_score",
        "release_health_score",
    )
    require(
        not any(token in cockpit for token in forbidden),
        "Certification Studio must not introduce an opaque release/certification score",
    )



def check_cross_app_verification_contract() -> None:
    core = (ROOT / "scripts/ecosystem_core_contract.py").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts/cross_app_verification.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/cross-app-verification.yml").read_text(
        encoding="utf-8"
    )
    require(
        'CONTRACT_NAME = "Shared Ecosystem Core"' in core
        and 'PRIVATE_MEDIA_MARKERS' in core
        and 'validate_envelope' in core
        and 'require_contract_version' in core
        and 'if not isinstance(value, str)' in core
        and 'CANONICAL_CONTRACT_REFS' in core
        and '_private_media_reference' in core,
        "v4.8 must reuse and fail-close the Shared Ecosystem Core contract",
    )
    for needle in (
        'APPLAB_VERSION="4.8.0"',
        '"independent_from_single_app_pass":True',
        '"requires_installed_apps"',
        '"missing_pair_evidence_never_becomes_pass":True',
        '"physical_evidence_required_when_transport_depends_on_installed_apps":True',
        'producer Release Reality identity mismatch',
        'consumer Release Reality identity mismatch',
        'SUPPORTED_TRANSPORTS',
        'installed=kind in INSTALLED_APP_TRANSPORTS',
        'unsupported cross-app scenario transport',
        'scenario transport must match pair transport',
        'EVIDENCE_URI_PREFIXES',
        'kind in {"deep_link","android_intent"}',
        'producer and consumer cannot use identical APK bytes',
        'producer and consumer must use distinct Android package ids',
        'PACKAGE_RE=re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*)+$")',
        'VERSION_CODE_RE=re.compile(r"^[1-9][0-9]*$")',
        'MAX_ANDROID_VERSION_CODE=2_100_000_000',
        'version_code must be an Android positive integer',
        'semantic contract lineage mismatch',
        'paired physical evidence requires at least one hashed evidence reference',
        'if result!=FAIL: result=BLOCKED',
        'return 0 if r["cross_app_round_trip"]["state"]==PASS else 1',
    ):
        require(needle in verifier, f"cross-app verifier missing invariant: {needle}")
    require(
        'refs/heads/main' in workflow
        and 'scripts/cross_app_verification.py' in workflow
        and 'retention-days: 90' in workflow
        and 'persist-credentials: false' in workflow,
        "cross-app trusted workflow boundary drift",
    )

def check_release_assurance_contract() -> None:
    assurance = (ROOT / "scripts/release_assurance.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")

    for needle in (
        'APPLAB_VERSION = "4.9.0"',
        'RECORD_TYPE = "AUTONOMOUS_RELEASE_ASSURANCE"',
        'AUTHORITY = "APPLAB_RELEASE_ASSURANCE"',
        '"release_assurance_can_certify": False',
        '"same_artifact_required": True',
        '"missing_required_evidence_never_passes": True',
        '"certification_is_not_distribution_proof": True',
        '"cross_app_pass_is_independent_from_single_app_pass": True',
        'same_bytes_verified") is True',
        '"Adaptive validation plan risk_score is invalid."',
        '"Adaptive validation plan confidence is invalid."',
        "certification_identity_matches",
        "certification_contract_state",
        "CANONICAL_STAGE_KEYS",
        'graph.get("schema_version") != 2',
        'clean(graph.get("graph_version")) != "2.0"',
        '"BuildArtifact"',
        '"apk_sha256"',
        "pair_identity_matches",
        "risk_plan_state",
        "PLAN_LANES",
        "PLAN_LABS",
        "set(selected) != PLAN_LABS",
        'result = clean(record.get("result")).upper()',
        "Canonical certification.json is missing",
        "Cross-app evidence uses invalid round-trip state",
        "Release Reality records a distribution failure",
        "def overall_state",
        "Required assurance stage cannot be N/A",
        "physical_present",
        'return 0 if payload["state"] == PASS or not args.require_pass else 1',
    ):
        require(needle in assurance, f"v4.9 release assurance missing invariant: {needle}")

    for needle in (
        "Build Autonomous Release Assurance",
        "scripts/release_assurance.py",
        "release-assurance.md",
        "release-reality.json",
        "evidence-graph.md",
        "AppLab True Autonomous App Review v5.3.2",
        "release_assurance|simulated_human_qa|studio_simulated_human|design_system_advisor|studio_design_advisor|competitive_product_intelligence|studio_competitive_product|virtual_product_review_council|studio_review_council|trusted_cross_app_evidence|physical_evidence",
        "cross_app_run_id",
        "trusted_cross_app_evidence.py verify-run",
        "trusted_cross_app_evidence.py validate",
        "cross-app-verification.bound.json",
    ):
        require(needle in workflow, f"v4.9 autonomous review integration missing: {needle}")

    require(
        "studio_release_assurance.project_from_directory" in studio
        and "studio_release_assurance.portfolio_summary(projects)" in studio,
        "Studio must source release assurance from the dedicated read-only projection",
    )
    projection = (ROOT / "scripts/studio_release_assurance.py").read_text(encoding="utf-8")
    require(
        '"release_assurance_blocked"' in projection
        and '"release_assurance_fail"' in projection
        and "_identity_match" in projection
        and "_validated_record" in projection
        and "release_assurance.digest" in projection
        and "release_assurance.overall_state" in projection
        and 'reason = "IDENTITY_MISMATCH"' in projection
        and '"certification_status": "NOT_VERIFIED"' in projection
        and '"record_valid": False' in projection
        and "release_assurance.CANONICAL_STAGE_KEYS" in projection
        and '"canonical_stage_set"' in projection
        and "type(required) is not bool" in projection
        and "stage_structure_valid" in projection
        and "except (KeyError, TypeError, ValueError)" in projection
        and '"unreadable_or_empty_record"' in projection
        and "assurance_path.is_file()" in projection,
        "Release Assurance Studio projection must preserve blocked/fail states and reject stale identities",
    )
    require(
        "Autonomous Release Assurance" in frontend
        and "release_assurance_pass" in frontend
        and "release_assurance_blocked" in frontend
        and "project.release_assurance.blockers" in frontend
        and "project.release_assurance.failures" in frontend
        and "project.release_assurance.identity_match === false" in frontend
        and "project.release_assurance.record_valid === false" in frontend,
        "Control Center must expose release assurance state",
    )
    cross_helper = (ROOT / "scripts/trusted_cross_app_evidence.py").read_text(
        encoding="utf-8"
    )
    for needle in (
        'AUTHORITY = "APPLAB_CROSS_APP_VERIFICATION"',
        'WORKFLOW_PATH = ".github/workflows/cross-app-verification.yml"',
        "cross-app run must originate from main",
        "cross-app evidence digest mismatch",
        "reviewed repository/revision",
    ):
        require(needle in cross_helper, f"trusted cross-app evidence helper missing: {needle}")

    require(
        (ROOT / "integration/certification/AUTONOMOUS_RELEASE_ASSURANCE_V49.md").is_file(),
        "v4.9 release assurance contract documentation is required",
    )


def check_simulated_human_qa_contract() -> None:
    engine = (ROOT / "scripts/simulated_human_qa.py").read_text(encoding="utf-8")
    projection = (ROOT / "scripts/studio_simulated_human.py").read_text(encoding="utf-8")
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )

    for needle in (
        'LAB_VERSION = "5.0.0"',
        'RECORD_TYPE = "SIMULATED_HUMAN_QA"',
        'AUTHORITY = "APPLAB_SIMULATED_HUMAN_QA_ADVISORY"',
        'CLASSIFICATION = "SIMULATED USER REVIEW"',
        '"beginner"',
        '"power_user"',
        '"older_user"',
        '"accessibility_focused"',
        '"privacy_conscious"',
        '"impatient"',
        '"offline_user"',
        '"VERIFY_NEXT", "IMPROVE", "NO_ACTION"',
        '"simulated_review_is_not_real_user_validation": True',
        '"simulated_review_is_not_physical_device_evidence": True',
        '"simulated_review_has_no_release_verdict": True',
        '"simulated_review_never_emits_fix_now": True',
        '"deterministic_core_no_llm_required": True',
        'graph.get("schema_version") != 2',
        'clean(graph.get("graph_version")) != "2.0"',
        "TAG_PREFIX_PATTERNS",
        "pattern_matches",
        "covered_states",
        "is_evidence_gap_signal",
        "EVIDENCE_GAP_MARKERS",
        "friction_candidates",
        "if not available:",
        '"artifact_sha256"',
        '"version_name"',
        '"version_code"',
        'print("AppLab v5.0 Simulated Human QA self-test PASS")',
    ):
        require(needle in engine, f"v5.0 simulated-human engine missing invariant: {needle}")

    for needle in (
        "_identity_match",
        "_validated_record",
        "simulated.evidence_identity(graph)",
        '"canonical_tasks"',
        '"walkthrough_state"',
        '"persona_summary"',
        '"heuristic_review"',
        '"heuristic_state"',
        '"finding_persona_derivation"',
        '"summary"',
        '"action_consistency"',
        '"finding_signal_ids"',
        '"action_finding_binding"',
        '"action_personas"',
        "type(support_count) is not int",
        "type(recurring) is not bool",
        '"record_valid": False',
        '"identity_match"',
        '"validation_errors"',
        '"simulated_review_required"',
        '"friction_sessions": sum(',
        '"evidence_incomplete_sessions": sum(',
        'print("AppLab v5.0 Simulated Human Studio projection self-test PASS")',
    ):
        require(needle in projection, f"v5.0 Studio projection missing invariant: {needle}")

    require(
        "studio_simulated_human.project_from_directory" in studio
        and "studio_simulated_human.portfolio_summary(projects)" in studio
        and 'STUDIO_VERSION = "5.3.2"' in studio,
        "Studio must expose v5.0 simulated-human evidence through the v5.1 Studio projection",
    )
    require(
        "Simulated Human QA" in frontend
        and "with_simulated_human" in frontend
        and "project.simulated_human.record_valid === false" in frontend
        and "SIMULATED USER REVIEW" in frontend,
        "Control Center must surface advisory simulated-human evidence",
    )
    for needle in (
        "Build Simulated Human QA",
        "scripts/simulated_human_qa.py",
        "simulated-human-qa.md",
        "AppLab True Autonomous App Review v5.3.2",
        "simulated_human_qa|studio_simulated_human|design_system_advisor|studio_design_advisor",
    ):
        require(needle in workflow, f"v5.0 autonomous review integration missing: {needle}")

    require(
        (ROOT / "integration/review/SIMULATED_HUMAN_QA_V50.md").is_file(),
        "v5.0 simulated-human QA contract documentation is required",
    )


def check_design_system_advisor_contract() -> None:
    engine = (ROOT / "scripts/design_system_advisor.py").read_text(encoding="utf-8")
    projection = (ROOT / "scripts/studio_design_advisor.py").read_text(encoding="utf-8")
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )

    for needle in (
        'LAB_VERSION = "5.1.0"',
        'RECORD_TYPE = "DESIGN_SYSTEM_UI_LIBRARY_ADVISOR"',
        'AUTHORITY = "APPLAB_DESIGN_SYSTEM_ADVISOR_ADVISORY"',
        'CLASSIFICATION = "DESIGN SYSTEM ADVISORY"',
        '"KEEP", "ADAPT", "REPLACE_CANDIDATE", "EVIDENCE_INCOMPLETE"',
        '"hierarchy"',
        '"typography"',
        '"spacing"',
        '"density"',
        '"component_consistency"',
        '"feedback"',
        '"empty_loading_error_states"',
        '"interaction_affordances"',
        '"accessibility"',
        '"responsive"',
        '"dark_mode"',
        '"localization"',
        '"no_numeric_aesthetic_score": True',
        '"no_automatic_library_replacement": True',
        '"different_library_is_not_automatically_better": True',
        '"missing_evidence_fails_closed": True',
        'evidence-graph.json is required for Design System Advisor',
        '"artifact_sha256"',
        '"version_name"',
        '"version_code"',
        'AppLab Design System Advisor self-test PASS',
    ):
        require(needle in engine, f"v5.1 design advisor engine missing invariant: {needle}")

    for needle in (
        'LAB_VERSION = "5.1.0"',
        'validation_errors',
        'record_digest_sha256',
        'dimensions.canonical_set',
        '"record_valid": False',
        '"EVIDENCE_INCOMPLETE"',
        'portfolio_summary',
        'AppLab Studio Design Advisor self-test PASS',
    ):
        require(needle in projection, f"v5.1 Studio design projection missing invariant: {needle}")

    require(
        "studio_design_advisor.project_from_directory" in studio
        and "studio_design_advisor.portfolio_summary(projects)" in studio
        and 'STUDIO_VERSION = "5.3.2"' in studio,
        "Studio must expose v5.1 design-advisor evidence through the dedicated projection",
    )
    require(
        "Design System & UI Library Advisor" in frontend
        and "with_design_advisor" in frontend
        and "project.design_advisor.record_valid === false" in frontend,
        "Control Center must surface advisory design-system evidence",
    )
    for needle in (
        "Build Design System & UI Library Advisor",
        "scripts/design_system_advisor.py",
        "design-system-advisor.md",
        "AppLab True Autonomous App Review v5.3.2",
        "design_system_advisor|studio_design_advisor",
    ):
        require(needle in workflow, f"v5.1 autonomous review integration missing: {needle}")

    require(
        (ROOT / "integration/design/DESIGN_SYSTEM_UI_LIBRARY_ADVISOR_V51.md").is_file(),
        "v5.1 design advisor contract documentation is required",
    )


def check_competitive_product_intelligence_contract() -> None:
    engine = (ROOT / "scripts/competitive_product_intelligence.py").read_text(encoding="utf-8")
    projection = (ROOT / "scripts/studio_competitive_product.py").read_text(encoding="utf-8")
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(encoding="utf-8")

    for needle in (
        'LAB_VERSION = "5.2.0"',
        'RECORD_TYPE = "COMPETITIVE_PRODUCT_INTELLIGENCE"',
        'AUTHORITY = "APPLAB_COMPETITIVE_PRODUCT_INTELLIGENCE_ADVISORY"',
        'CLASSIFICATION = "COMPETITIVE PRODUCT INTELLIGENCE"',
        'EXTENDED_DIMENSIONS = ("workflows", "onboarding", "visual_patterns")',
        '"no_auto_feature_addition": True',
        '"no_competitor_feature_copying": True',
        '"parity_requires_product_contract_and_target_user_context": True',
        '"source_traceability_required": True',
        '"freshness_required": True',
        '"trusted_verifier_does_not_scrape_web": True',
        '"RELEVANT_PARITY_REVIEW"',
        '"NOT_PRODUCT_CONTRACT_RELEVANT"',
        '"TARGET_USER_CONTEXT_INCOMPLETE"',
        '"MARKET_WEAKNESS_OPPORTUNITY"',
        '"PROTECT_DIFFERENTIATOR"',
        'evidence-graph.json is required for Competitive Product Intelligence',
        'AppLab Competitive Product Intelligence v5.2 self-test PASS',
    ):
        require(needle in engine, f"v5.2 competitive engine missing invariant: {needle}")

    for needle in (
        'LAB_VERSION = "5.2.0"',
        'record_digest_sha256',
        '"record_valid": False',
        '"EVIDENCE_INCOMPLETE"',
        'portfolio_summary',
        'AppLab Studio Competitive Product v5.2 self-test PASS',
    ):
        require(needle in projection, f"v5.2 competitive Studio projection missing invariant: {needle}")

    require(
        "studio_competitive_product.project_from_directory" in studio
        and "studio_competitive_product.portfolio_summary(projects)" in studio
        and 'STUDIO_VERSION = "5.3.2"' in studio,
        "Studio must expose v5.2 competitive-product evidence",
    )
    require(
        "Competitive Product Intelligence" in frontend
        and "with_competitive_product" in frontend
        and "project.competitive_product.record_valid === false" in frontend,
        "Control Center must surface competitive-product evidence",
    )
    for needle in (
        "Build Competitive Product Intelligence",
        "scripts/competitive_product_intelligence.py",
        "competitive-product-intelligence.md",
        "AppLab True Autonomous App Review v5.3.2",
        "competitive_product_intelligence|studio_competitive_product",
        "market_evidence_path:",
    ):
        require(needle in workflow, f"v5.2 autonomous review integration missing: {needle}")

    require(
        (ROOT / "integration/market/COMPETITIVE_PRODUCT_INTELLIGENCE_V52.md").is_file(),
        "v5.2 competitive product contract documentation is required",
    )


def check_virtual_product_review_council_contract() -> None:
    engine = (ROOT / "scripts/virtual_product_review_council.py").read_text(encoding="utf-8")
    projection = (ROOT / "scripts/studio_review_council.py").read_text(encoding="utf-8")
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/ControlCenter.tsx").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(encoding="utf-8")

    for needle in (
        'LAB_VERSION = "5.3.0"',
        'RECORD_TYPE = "VIRTUAL_PRODUCT_REVIEW_COUNCIL"',
        'AUTHORITY = "APPLAB_VIRTUAL_PRODUCT_REVIEW_COUNCIL_ADVISORY"',
        'CLASSIFICATION = "VIRTUAL PRODUCT REVIEW COUNCIL"',
        'REVIEWERS = ("QA", "UX", "ACCESSIBILITY", "PRODUCT", "DESIGN", "MARKET")',
        'BUCKETS = ("FIX_NOW", "VERIFY_NEXT", "IMPROVE", "CONSIDER", "NO_ACTION")',
        '"TECHNICAL_DEFECT"',
        '"USABILITY_RISK"',
        '"ACCESSIBILITY_RISK"',
        '"DESIGN_FIT_QUESTION"',
        '"PRODUCT_OPPORTUNITY"',
        '"MARKET_OPPORTUNITY"',
        '"no_numeric_consensus_score": True',
        '"fix_now_only_from_existing_technical_runtime_evidence": True',
        '"simulated_users_are_not_real_users": True',
        '"physical_device_validation_remains_separate": True',
        '"release_certification_remains_separate": True',
        '"council_does_not_replace_product_ownership": True',
        'CROSS_REVIEW_AGREEMENT',
        'CROSS_REVIEW_ACTION_CONTRADICTION',
        'evidence-graph.json is required for Virtual Product Review Council',
        'AppLab Virtual Product Review Council v5.3 self-test PASS',
    ):
        require(needle in engine, f"v5.3 review council engine missing invariant: {needle}")

    for needle in (
        'LAB_VERSION = "5.3.0"',
        'reviewers.canonical_set',
        'product_review_brief.fix_now_authority',
        'record_digest_sha256',
        '"record_valid": False',
        'portfolio_summary',
        'AppLab Studio Virtual Product Review Council v5.3 self-test PASS',
    ):
        require(needle in projection, f"v5.3 council Studio projection missing invariant: {needle}")

    require(
        "studio_review_council.project_from_directory" in studio
        and "studio_review_council.portfolio_summary(projects)" in studio
        and 'STUDIO_VERSION = "5.3.2"' in studio,
        "Studio must expose v5.3 review-council evidence",
    )
    require(
        "Virtual Product Review Council" in frontend
        and "with_review_council" in frontend
        and "project.review_council.record_valid === false" in frontend,
        "Control Center must surface review-council evidence",
    )
    for needle in (
        "Build Virtual Product Review Council",
        "scripts/virtual_product_review_council.py",
        "virtual-product-review-council.md",
        "AppLab True Autonomous App Review v5.3.2",
        "virtual_product_review_council|studio_review_council",
    ):
        require(needle in workflow, f"v5.3 autonomous review integration missing: {needle}")

    require(
        (ROOT / "integration/review/VIRTUAL_PRODUCT_REVIEW_COUNCIL_V53.md").is_file(),
        "v5.3 review council contract documentation is required",
    )


def check_v531_technical_hardening_contract() -> None:
    live_spec = (ROOT / "frontend/e2e/live-webrtc.spec.mjs").read_text(encoding="utf-8")
    live_workflow = (ROOT / ".github/workflows/live-emulator-self-test.yml").read_text(
        encoding="utf-8"
    )
    preview = (ROOT / ".github/workflows/web-preview.yml").read_text(encoding="utf-8")
    lock = (ROOT / ".github/workflows/frontend-lock.yml").read_text(encoding="utf-8")
    production = (ROOT / ".github/workflows/production-certification.yml").read_text(
        encoding="utf-8"
    )
    retention = (ROOT / "scripts/evidence_retention_contract.py").read_text(
        encoding="utf-8"
    )
    maintainability = (ROOT / "scripts/maintainability_budget.py").read_text(
        encoding="utf-8"
    )

    for needle in (
        "async function videoDiagnostics",
        "async function attachFrameRecoveryDiagnostics",
        "async function waitForDecodedFrame",
        "webrtc-frame-recovery-attempt-",
        "for (let attempt = 1; attempt <= 2; attempt += 1)",
        "if (attempt === 2) throw error",
        "WebRTC connected but no decoded Android video frame arrived",
        "WebRTC connected but no non-black Android frame was decoded",
        "Android UI did not react to the WebRTC pointer input",
    ):
        require(needle in live_spec, f"v5.3.1 WebRTC hardening missing invariant: {needle}")

    for needle in (
        "Setup Node for browser tooling",
        'node-version: "22"',
        "Validate frontend dependency graph before runtime work",
        "npm ci --ignore-scripts --no-audit --no-fund --dry-run",
        "frontend-dependency-preflight.txt",
        "retention-days: 7",
    ):
        require(needle in live_workflow, f"v5.3.1 live workflow hardening missing: {needle}")

    for needle in (
        "pull_request:",
        "applab-frontend-lock-${{ github.ref }}",
        "Validate install graph",
        "Require clean lockfile on pull request",
        "github.event_name != 'pull_request'",
    ):
        require(needle in lock, f"v5.3.1 frontend lock hardening missing: {needle}")

    for needle in (
        "Detect Pages availability",
        "pages_enabled: ${{ steps.pages_status.outputs.enabled }}",
        "Upload non-deployed preview evidence",
        "if: steps.pages_status.outputs.enabled == 'true'",
        "if: needs.build.outputs.pages_enabled == 'true'",
        "GitHub Pages is not configured for this repository",
    ):
        require(needle in preview, f"v5.3.1 preview hardening missing: {needle}")

    for needle in (
        'POLICY_VERSION = "1.0"',
        '"RELEASE_CRITICAL", 90',
        '"LONGITUDINAL", 90',
        '"INFRA_DIAGNOSTIC", 7',
        "Upload certified release bundle",
        "Upload final certification evidence",
        "Upload certification history",
        "Upload physical evidence attestation",
        "Upload paired verification evidence",
        "Upload repository-wide longitudinal history",
        "Upload live browser evidence",
        "AppLab evidence retention policy v",
    ):
        require(needle in retention, f"v5.3.1 retention contract missing invariant: {needle}")

    require(
        production.count("retention-days: 90") >= 3,
        "production certification release-critical artifacts must retain 90 days",
    )
    require(
        '"scripts/evidence_retention_contract.py": 180' in maintainability,
        "retention contract must have a maintainability ceiling",
    )
    require(
        (ROOT / "integration/hardening/TECHNICAL_HARDENING_V531.md").is_file(),
        "v5.3.1 technical hardening documentation is required",
    )


def check_v532_graph_aware_planning_feedback_contract() -> None:
    feedback = (ROOT / "scripts/planner_feedback.py").read_text(encoding="utf-8")
    planner = (ROOT / "scripts/smart_test_plan.py").read_text(encoding="utf-8")
    packager = (ROOT / "scripts/package_build_contract.py").read_text(encoding="utf-8")
    graph = (ROOT / "scripts/evidence_graph.py").read_text(encoding="utf-8")
    flutter = (ROOT / ".github/workflows/external-project-runner.yml").read_text(encoding="utf-8")
    native = (ROOT / ".github/workflows/external-native-android-runner.yml").read_text(encoding="utf-8")
    review = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(encoding="utf-8")
    watcher = (ROOT / ".github/workflows/repo-watcher.yml").read_text(encoding="utf-8")
    fingerprint = (ROOT / "scripts/contract_fingerprint.py").read_text(encoding="utf-8")
    maintainability = (ROOT / "scripts/maintainability_budget.py").read_text(encoding="utf-8")
    acceleration = (ROOT / "scripts/execution_acceleration.py").read_text(encoding="utf-8")

    for needle in (
        'ENGINE_VERSION = "5.3.2"',
        'RECORD_TYPE = "EVIDENCE_GRAPH_PLANNER_FEEDBACK"',
        'GRAPH_SCHEMA_VERSION = 2',
        'GRAPH_VERSION = "2.0"',
        'MAX_RISK_BOOST = 20',
        "def build_feedback(",
        "def evaluate_feedback(",
        '"advisory_input_only": True',
        '"smart_test_plan_remains_single_authority": True',
        '"cannot_reduce_coverage": True',
        '"current_run_graph_cannot_retroactively_change_lane": True',
        '"exact_baseline_sha_required": True',
        '"missing_invalid_or_truncated_feedback_is_ignored": True',
        "BASELINE_SHA_MISMATCH",
        "LINEAGE_MISMATCH",
        "SOURCE_ANALYSIS_TRUNCATED",
        "IMPACT_PATH_CAP_REACHED",
        "DIGEST_MISMATCH",
        "AppLab Graph-aware Planner Feedback v5.3.2 self-test PASS",
    ):
        require(needle in feedback, f"v5.3.2 planner-feedback contract missing: {needle}")

    for needle in (
        'from planner_feedback import evaluate_feedback',
        '"planner_version": "1.1.0"',
        "def apply_graph_planner_feedback(",
        '"coverage_reduced": False',
        "APPLIED_ESCALATION_ONLY",
        "prior trusted Evidence Graph risk escalation to FULL",
        'parser.add_argument("--planner-feedback"',
        "planner_feedback_path",
    ):
        require(needle in planner, f"v5.3.2 Smart Test Plan integration missing: {needle}")

    require(
        'planner_feedback_path=args.planner_feedback' in packager
        and '"planner_feedback",' in packager
        and 'output / "planner-feedback.json"' in packager,
        "trusted build-contract recomputation must bind planner feedback immutably",
    )
    require(
        '"graph_does_not_retroactively_change_current_fast_full_certification": True' in graph
        and '"graph_does_not_change_fast_full_certification": True' not in graph,
        "Evidence Graph must express future-feedback vs current-run authority precisely",
    )

    for workflow in (flutter, native):
        for needle in (
            "Restore prior graph planner feedback",
            "restore_planner_feedback.sh",
            '--planner-feedback "$RUNNER_TEMP/applab-planner-feedback.json"',
        ):
            require(needle in workflow, f"v5.3.2 external runner integration missing: {needle}")

    for needle in (
        "Build graph-aware planner feedback",
        "scripts/planner_feedback.py",
        "planner-feedback.md",
        ".applab-longitudinal/planner-feedback.json",
        "AppLab True Autonomous App Review v5.3.2",
    ):
        require(needle in review, f"v5.3.2 autonomous review integration missing: {needle}")

    require(
        '"scripts/planner_feedback.py"' in fingerprint
        and '"scripts/restore_planner_feedback.sh"' in fingerprint,
        "planner feedback producer/restore helper must invalidate core contract fingerprints",
    )
    require(
        '"scripts/planner_feedback.py"' in watcher
        and '"scripts/restore_planner_feedback.sh"' in watcher,
        "Repo Watcher must react to planner-feedback contract changes",
    )
    require(
        '"scripts/smart_test_plan.py": 1000' in maintainability
        and '"scripts/planner_feedback.py": 420' in maintainability,
        "v5.3.2 planner modules must have maintainability ceilings",
    )
    require(
        '"planner_feedback",' in acceleration,
        "execution identity must include planner-feedback provenance",
    )
    require(
        (ROOT / "integration/hardening/GRAPH_AWARE_PLANNING_FEEDBACK_V532.md").is_file(),
        "v5.3.2 graph-aware planning feedback documentation is required",
    )


def main() -> int:
    check_version_alignment()
    check_local_controller_boundary()
    check_actions_pinned()
    check_trusted_review_contract()
    check_schema_forwarding()
    check_no_floating_self_reference()
    check_residual_hardening_contract()
    check_evidence_graph_contract()
    check_project_adapter_contract()
    check_release_reality_contract()
    check_certification_studio_contract()
    check_cross_app_verification_contract()
    check_release_assurance_contract()
    check_simulated_human_qa_contract()
    check_design_system_advisor_contract()
    check_competitive_product_intelligence_contract()
    check_virtual_product_review_council_contract()
    check_v531_technical_hardening_contract()
    check_v532_graph_aware_planning_feedback_contract()
    check_physical_evidence_contract()
    check_execution_acceleration_contract()
    print("AppLab audit hardening contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
