#!/usr/bin/env python3
"""AppLab source-first REA routing: choose when static CLI research is worthwhile.

Pure triage by default; --execute performs only an already-authorized, SHA-bound
local inspection through the existing AppLab REA adapters. No MCP or auto-install.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from rea_cli_bridge import BridgeBlocked

SHA40 = re.compile(r"^[0-9a-f]{40}$", re.I)
SHA64 = re.compile(r"^[0-9a-f]{64}$", re.I)
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WEIGHTS = {
    "SOURCE_BINARY_MISMATCH": 7,
    "PERMISSION_DECLARATION_MISMATCH": 6,
    "MISSING_SOURCE": 5,
    "UNKNOWN_NATIVE_DEPENDENCY": 5,
    "MANAGED_METADATA_QUESTION": 5,
    "DESKTOP_PACKAGING_QUESTION": 5,
    "AOT_BINARY_QUESTION": 4,
    "UNEXPLAINED_SIZE_DELTA": 4,
}
RESEARCH_TRIGGERS = frozenset(WEIGHTS)
JADX_SHA256 = '6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75'
SYMPTOMS = {
    'source_vs_artifact_diff': 'SOURCE_BINARY_MISMATCH',
    'manifest_permissions_diverge': 'PERMISSION_DECLARATION_MISMATCH',
    'missing_source': 'MISSING_SOURCE',
    'unexpected_native_dependency': 'UNKNOWN_NATIVE_DEPENDENCY',
    'managed_dependencies_unknown': 'MANAGED_METADATA_QUESTION',
    'installer_contents_unknown': 'DESKTOP_PACKAGING_QUESTION',
    'aot_snapshot_unexplained': 'AOT_BINARY_QUESTION',
    'artifact_growth_unexplained': 'UNEXPLAINED_SIZE_DELTA',
}

MAX_BYTES = 512 * 1024 * 1024


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def decide(context: dict) -> dict:
    """Deterministic, auditable signal-to-route decision. Never executes REA."""
    if not isinstance(context, dict):
        raise ValueError("REA context must be a JSON object")
    symptoms = context.get("symptoms", [])
    if not isinstance(symptoms, list) or any(x not in SYMPTOMS for x in symptoms):
        raise ValueError("Unknown or invalid AppLab diagnostic symptoms")
    signals = context.get("signals", [])
    if not isinstance(signals, list) or any(not isinstance(s, str) for s in signals):
        raise ValueError("signals must be a list of known codes")
    unknown = set(signals) - RESEARCH_TRIGGERS
    if unknown:
        raise ValueError("Unknown REA trigger: " + ",".join(sorted(unknown)))
    signals = sorted(set(signals) | {SYMPTOMS[x] for x in symptoms})
    reason = []
    plan = {"schema_version": 1, "authority": "ADVISORY_UNTIL_GATED_EXECUTION",
            "status": "SKIP", "reason_codes": reason, "signals": signals,
            "score": min(10, sum(WEIGHTS[s] for s in signals)),
            "mode": None, "operations": [], "target_executed": False,
            "certification": "NONE", "donor_admission": "RESEARCH_ONLY"}
    if not signals:
        reason.append("SOURCE_FIRST_NO_BINARY_GAP")
        return plan
    if context.get("source_complete") is True and signals == ["MISSING_SOURCE"]:
        reason.append("SOURCE_SUFFICIENT_FOR_CURRENT_QUESTION")
        return plan
    if plan["score"] < 4:
        reason.append("BELOW_COST_BENEFIT_THRESHOLD")
        return plan
    if context.get("authorization") not in {"OWNED", "EXTERNAL_AUTHORIZED"}:
        plan["status"] = "BLOCKED"
        reason.append("MISSING_RESEARCH_AUTHORIZATION")
        return plan
    kind = context.get("artifact_kind")
    stack = context.get("stack")
    if kind == "APK":
        if "PERMISSION_DECLARATION_MISMATCH" in signals or "UNKNOWN_NATIVE_DEPENDENCY" in signals:
            mode, ops = "android", ["inspect-android-package"]
        elif stack == "flutter":
            mode, ops = "flutter", ["identify-flutter-build", "inspect-dart-aot"]
        else:
            mode, ops = "android", ["inspect-android-package"]
    elif kind == "DESKTOP_DIR":
        mode, ops = "desktop", ["inspect-desktop-application"]
    elif kind == "PE":
        if "MANAGED_METADATA_QUESTION" in signals:
            mode, ops = "managed", ["inspect-managed-artifact"]
        else:
            mode, ops = "pe", ["imports", "certificates"]
    else:
        plan["status"] = "BLOCKED"
        reason.append("UNSUPPORTED_OR_UNDECLARED_ARTIFACT_KIND")
        return plan
    plan.update(mode=mode, operations=ops)
    repo, sha = context.get("repository"), context.get("source_sha")
    expected = context.get("artifact_sha256")
    if not isinstance(repo, str) or not REPO.fullmatch(repo or "") or (
            not isinstance(sha, str) or not SHA40.fullmatch(sha)):
        plan["status"] = "BLOCKED"
        reason.append("MISSING_EXACT_SOURCE_IDENTITY")
        return plan
    if not isinstance(expected, str) or not SHA64.fullmatch(expected):
        plan["status"] = "PROPOSE"
        reason.append("ARTIFACT_SHA256_REQUIRED")
        return plan
    previous = context.get("previous_success")
    if isinstance(previous, dict) and previous.get("source_sha") == sha and (
            previous.get("artifact_sha256") == expected.lower() and
            previous.get("mode") == mode and previous.get("operations") == ops):
        reason.append("EXACT_ARTIFACT_ALREADY_INSPECTED")
        return plan
    raw = context.get("artifact_path")
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        plan["status"] = "PROPOSE"
        reason.append("LOCAL_ARTIFACT_REQUIRED")
        return plan
    path = Path(raw)
    try:
        if path.is_symlink() or not (path.is_dir() if mode == "desktop" else path.is_file()):
            raise ValueError("not a permitted regular local target")
        if mode != "desktop" and (path.stat().st_size <= 0 or
                                   path.stat().st_size > MAX_BYTES or _hash(path) != expected.lower()):
            raise ValueError("artifact size/hash not admitted")
    except (OSError, ValueError):
        plan["status"] = "BLOCKED"
        reason.append("LOCAL_ARTIFACT_IDENTITY_MISMATCH")
        return plan
    if mode == "desktop":
        # Use the exact canonical tree identity, not an invented file hash.
        from rea_cli_research import inspect_tree
        try:
            tree_identity = inspect_tree(path)
            if tree_identity["sha256"] != expected.lower():
                raise ValueError("desktop inventory identity mismatch")
        except (OSError, ValueError, BridgeBlocked):
            plan["status"] = "BLOCKED"
            reason.append("DESKTOP_TREE_IDENTITY_MISMATCH")
            return plan
    if context["authorization"] != "OWNED":
        plan["status"] = "PROPOSE"
        reason.append("EXTERNAL_SOURCE_REQUIRES_EXPLICIT_REVIEW")
        return plan
    exe = context.get("rea_bin")
    output = context.get("output_dir")
    budget = context.get("max_bytes", 64 * 1024 * 1024)
    if not isinstance(budget, int) or budget <= 0 or budget > MAX_BYTES:
        plan["status"] = "BLOCKED"
        reason.append("INVALID_RESEARCH_BYTE_BUDGET")
        return plan
    artifact_bytes = tree_identity["bytes"] if mode == "desktop" else path.stat().st_size
    if artifact_bytes > budget:
        plan["status"] = "PROPOSE"
        reason.append("ARTIFACT_EXCEEDS_CONFIGURED_BYTE_BUDGET")
        return plan
    if (not isinstance(exe, str) or not Path(exe).is_absolute() or
            not Path(exe).exists() or not isinstance(output, str) or
            not Path(output).is_absolute() or Path(output).is_symlink()):
        plan["status"] = "PROPOSE"
        reason.append("REA_ENVIRONMENT_NOT_READY")
        return plan
    output_real = Path(output).resolve()
    if (mode == "desktop" and output_real.is_relative_to(path.resolve())) or (
            mode != "desktop" and output_real == path.parent.resolve()):
        plan["status"] = "BLOCKED"
        reason.append("EVIDENCE_OUTPUT_INSIDE_TARGET")
        return plan
    if mode == "android":
        jar_raw = context.get("jadx_jar") or os.environ.get("REA_JADX_MCP_JAR")
        jar = Path(jar_raw) if isinstance(jar_raw, str) else None
        if (jar is None or not jar.is_absolute() or not jar.is_file() or
                jar.is_symlink() or _hash(jar) != JADX_SHA256):
            plan["status"] = "PROPOSE"
            reason.append("PINNED_JADX_ENGINE_NOT_READY")
            return plan
    entry = context.get("rea_entry")
    if entry is not None and (not isinstance(entry, str) or not Path(entry).is_absolute()):
        plan["status"] = "BLOCKED"
        reason.append("INVALID_REA_ENTRY_PATH")
        return plan
    # WorkItem JSON is data, never sufficient authority to select a process
    # executable, arbitrary local file, repository or output destination.
    bindings = {
        "APPLAB_REA_TRUSTED_BIN": exe,
        "APPLAB_REA_AUTHORIZED_ARTIFACT": raw,
        "APPLAB_REA_AUTHORIZED_REPOSITORY": repo,
        "APPLAB_REA_AUTHORIZED_SOURCE_SHA": sha,
        "APPLAB_REA_PRIVATE_OUTPUT_ROOT": output,
    }
    if any(not os.environ.get(key) for key in bindings):
        plan["status"] = "PROPOSE"
        reason.append("TRUSTED_RUNNER_BINDING_REQUIRED")
        return plan
    if (Path(os.environ["APPLAB_REA_TRUSTED_BIN"]).resolve() != Path(exe).resolve()
            or Path(os.environ["APPLAB_REA_AUTHORIZED_ARTIFACT"]).resolve() != path.resolve()
            or os.environ["APPLAB_REA_AUTHORIZED_REPOSITORY"] != repo
            or os.environ["APPLAB_REA_AUTHORIZED_SOURCE_SHA"].lower() != sha.lower()
            or not output_real.is_relative_to(
                Path(os.environ["APPLAB_REA_PRIVATE_OUTPUT_ROOT"]).resolve())
            or (entry and os.environ.get("APPLAB_REA_TRUSTED_ENTRY") != entry)):
        plan["status"] = "BLOCKED"
        reason.append("TRUSTED_RUNNER_SCOPE_MISMATCH")
        return plan
    engine = Path(exe).resolve()
    if engine == path.resolve() or (
            entry and Path(entry).resolve() == path.resolve()):
        plan["status"] = "BLOCKED"
        reason.append("REA_EXECUTABLE_EQUALS_TARGET")
        return plan
    plan["status"] = "AUTO_RUN"
    reason.append("OWNED_EXACT_ARTIFACT_WITH_MATERIAL_BINARY_GAP")
    return plan


def execute(context: dict, plan: dict) -> dict:
    """Use existing adapters; never shell, download/install tools or run target."""
    if plan["status"] != "AUTO_RUN":
        return {**plan, "execution": "NOT_STARTED"}
    script = ("rea_cli_bridge.py" if plan["mode"] == "pe"
              else "rea_cli_research.py")
    argv = [sys.executable, str(Path(__file__).with_name(script))]
    if plan["mode"] != "pe":
        argv += ["--mode", plan["mode"]]
    argv += ["--rea-bin", context["rea_bin"],
             "--artifact", context["artifact_path"],
             "--output-dir", context["output_dir"],
             "--repository", context["repository"],
             "--source-sha", context["source_sha"]]
    if plan["mode"] != "pe":
        argv += ["--expected-sha256", context["artifact_sha256"]]
    if context.get("rea_entry"):
        argv += ["--rea-entry", context["rea_entry"]]
    for op in plan["operations"]:
        argv += ["--operation", op]
    budget = context.get("timeout_seconds", 90)
    if not isinstance(budget, int) or not 5 <= budget <= 180:
        raise ValueError("REA auto-run timeout budget must be within 5..180 seconds")
    argv += ["--timeout", str(budget), "--max-bytes",
             str(context.get("max_bytes", 64 * 1024 * 1024))]
    env = os.environ.copy()
    if plan["mode"] == "android" and context.get("jadx_jar"):
        env["REA_JADX_MCP_JAR"] = context["jadx_jar"]
    try:
        run = subprocess.run(argv, capture_output=True, text=True, env=env,
                             check=False, timeout=budget * len(plan["operations"]) + 30)
    except subprocess.TimeoutExpired:
        return {**plan, "execution": "FAILED", "adapter_exit_code": 124,
                "reason_codes": plan["reason_codes"] + ["REA_ADAPTER_TIMEOUT"],
                "research_only": True}
    except OSError:
        return {**plan, "execution": "FAILED", "adapter_exit_code": 127,
                "reason_codes": plan["reason_codes"] + ["REA_ADAPTER_UNAVAILABLE"],
                "research_only": True}
    # Validate the adapter's bound artifact identity; never turn a stale
    # replacement or a fake successful command into a trusted PASS.
    ok = False
    if run.returncode == 0:
        try:
            receipt = json.loads(run.stdout)
            ok = (receipt.get("artifact", {}).get("sha256") ==
                  context["artifact_sha256"].lower())
        except (ValueError, TypeError, AttributeError):
            ok = False
    # Do not publish external evidence, stdout or private local file paths.
    return {**plan, "execution": "SUCCESS" if ok else "FAILED",
            "adapter_exit_code": run.returncode, "research_only": True}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context", required=True, type=Path)
    p.add_argument("--execute-eligible", action="store_true")
    args = p.parse_args()
    try:
        path = args.context
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 64 * 1024:
            raise ValueError("Expected a bounded local context JSON file")
        ctx = json.loads(path.read_text(encoding="utf-8"))
        result = decide(ctx)
        if args.execute_eligible:
            result = execute(ctx, result)
    except (ValueError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print("REA AUTO ROUTER BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("execution") != "FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
