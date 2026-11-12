#!/usr/bin/env python3
"""X10-032: immutable artifact-bound physical/Play QA scenario generator.

This does not create a physical evidence receipt; only the pre-existing
AppLab physical_evidence.py trusted hub may verify a device scenario.
No runner, Play Console or device access is emulated.
"""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any

SHA = re.compile(r"[a-f0-9]{40}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+\Z")
CAPABILITIES = frozenset((
    "gps", "background", "camera", "scanner", "biometrics", "keystore",
    "notifications", "storage", "file_picker", "oem_battery",
    "oauth", "billing", "play_delivery", "model_delivery",
))
BASE_SCENARIOS = (
    ("fresh_install", "Install exact signed artifact and open app"),
    ("upgrade_preserve_data", "Install over prior version without clearing local data"),
    ("restart_preserve_data", "Force-stop/relaunch and check owner-scoped data"),
    ("reinstall_recovery", "Document uninstall/reinstall impact, recovery and user choice"),
    ("play_internal_delivery", "Verify Play internal track installation and package/signer"),
)
NATIVE_SCENARIOS = {
    "notifications": "notification_delivery_oem",
    "gps": "gps_background_permissions",
    "background": "background_restart",
    "camera": "camera_permission_recovery",
    "scanner": "scan_permission_recovery",
    "biometrics": "biometric_auth_lockout",
    "keystore": "keystore_identity_lifecycle",
    "oauth": "oauth_release_callback",
    "billing": "play_purchase_refund",
    "storage": "local_file_picker_restore",
    "file_picker": "local_file_picker_restore",
    "oem_battery": "oem_battery_restrictions",
    "model_delivery": "model_delivery_offline",
    "play_delivery": "play_internal_delivery",
}
MAX_CAPS = 15

class PhysicalPlanError(ValueError):
    pass

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise PhysicalPlanError(reason)

def create_plan(contract: dict[str, Any]) -> dict[str, Any]:
    """Only a preparation for a human to run on a REAL device and Play Console."""
    require(isinstance(contract, dict) and set(contract) == {
        "repository", "source_sha", "apk_sha256", "package_id",
        "version_code", "signing_cert_sha256", "capabilities",
        "release_workflow_url", "previous_version_code",
    }, "CONTRACT_FIELDS_INVALID")
    repo, source, artifact, package = (
        contract[k] for k in ("repository", "source_sha", "apk_sha256", "package_id")
    )
    require(isinstance(repo, str) and REPO.fullmatch(repo) is not None
            and isinstance(source, str) and SHA.fullmatch(source) is not None
            and isinstance(artifact, str) and DIGEST.fullmatch(artifact) is not None
            and isinstance(package, str) and PACKAGE.fullmatch(package) is not None
            and isinstance(contract["signing_cert_sha256"], str)
            and DIGEST.fullmatch(contract["signing_cert_sha256"]) is not None
            and type(contract["version_code"]) is int and contract["version_code"] > 0
            and type(contract["previous_version_code"]) is int
            and 0 <= contract["previous_version_code"] < contract["version_code"],
            "ARTIFACT_IDENTITY_OR_UPGRADE_VERSION_INVALID")
    url = contract["release_workflow_url"]
    require(isinstance(url, str)
            and (url.startswith(f"https://github.com/{repo}/actions/runs/")
                 or url.startswith("https://github.com/riccardopinato/AppLab/actions/runs/"))
            and re.search(r"/actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?\Z", url) is not None,
            "SOURCE_WORKFLOW_RUN_URL_INVALID")
    caps = contract["capabilities"]
    require(isinstance(caps, list) and len(caps) <= MAX_CAPS
            and len(set(caps)) == len(caps) and set(caps) <= CAPABILITIES,
            "UNSUPPORTED_CAPABILITIES")
    stages = list(BASE_SCENARIOS)
    already = {k for k, _ in stages}
    for cap in sorted(caps):
        scenario_id = NATIVE_SCENARIOS[cap]
        if scenario_id not in already:
            stages.append((scenario_id, "Physical on-device capability check: " + cap))
            already.add(scenario_id)
    scenarios = [{
        "scenario_id": key, "instructions": description,
        "status": "NOT_VERIFIED",
        "required_evidence": [
            "independent physical_evidence.py hub receipt",
            "exact same APK SHA256",
            "device model and Android build",
            "real observed result with redacted proof",
        ],
        "observed_result": None,
        "physical_attested": False,
        "play_console_verified": False,
    } for key, description in stages]
    fingerprint = hashlib.sha256(json.dumps({
        "artifact": artifact, "source": source, "package": package, "scenarios": stages
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "record_type": "X10_PHYSICAL_PLAY_ACCEPTANCE_PLAN",
        "authority": "PLAN_ONLY", "repository": repo, "source_sha": source,
        "apk_sha256": artifact, "package_id": package,
        "version_code": contract["version_code"],
        "signing_cert_sha256": contract["signing_cert_sha256"],
        "release_workflow_url": url,
        "scenario_count": len(scenarios), "scenarios": scenarios,
        "plan_digest": fingerprint, "physical_qa_complete": False,
        "play_internal_testing_complete": False, "actual_device_connected": False,
        "artifact_exists_verified_remotely": False, "certification_granted": False,
        "release_authorized": False,
        "instructions": "Use canonical AppLab physical_evidence.py authenticated verification; "
                        "obtain independent Play Console/internal testing proofs; "
                        "no test result is minted by this planner.",
    }
