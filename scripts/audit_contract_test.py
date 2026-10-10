#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "4.3.0"
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
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
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
    studio = (ROOT / "scripts/studio_snapshot.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/autonomous-app-review-v31.yml").read_text(
        encoding="utf-8"
    )
    for node_type in (
        "Project",
        "Revision",
        "BuildArtifact",
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
        "history",
        "evidence",
    ):
        require(query in graph, f"Evidence Graph missing query contract {query}")
    require(
        'first_observed_sha_is_not_proof_of_introducing_commit' in graph,
        "Evidence Graph must not convert first observation into causal blame",
    )
    require(
        "Build Evidence Graph" in workflow and "evidence-graph.md" in workflow,
        "trusted review must build and publish Evidence Graph",
    )
    require(
        'evidence-graph.json' in studio,
        "Studio must ingest Evidence Graph summary evidence",
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
        and "APK package id is unavailable" in validator,
        "trusted contract validation must bind configured package to available built APK identity",
    )
    require(
        "riccardopinato/CamperBoss" in integration
        and "riccardopinato/Battery_Guard" in integration,
        "v4.3 adapter must keep real App Factory integration coverage",
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
    check_execution_acceleration_contract()
    print("AppLab audit hardening contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
