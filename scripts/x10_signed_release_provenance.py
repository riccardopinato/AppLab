#!/usr/bin/env python3
"""X10-031: fail-closed release-identity adoption of existing AppLab evidence.

Source+CI contract only. The trusted runner must provide platform inspectors
from existing package_build_contract, plus a signed AAB verifier when needed.
This does NOT mint a signing key, upload an artifact, or certify Store readiness.
"""
from __future__ import annotations

import hashlib
import re
from zipfile import BadZipFile, ZipFile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VERSION = re.compile(r"^[0-9]+$")
KINDS = {"APK", "AAB"}
SCOPES = {"arm64-v8a", "armeabi-v7a", "universal", "bundle"}


class ProvenanceGateError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ProvenanceGateError(reason)


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confined_artifact(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and 0 < len(relative) < 256,
            "UNSAFE_ARTIFACT_PATH")
    raw = PurePosixPath(relative)
    require(not raw.is_absolute() and not any(
        chunk in (".", "..", "") for chunk in relative.split("/")
    ) and "\\" not in relative and raw.suffix.lower() in (".apk", ".aab"),
            "UNSAFE_ARTIFACT_PATH")
    require(root.is_dir() and not root.is_symlink(), "INVALID_ARTIFACT_ROOT")
    target = root / Path(relative)
    require(target.is_file() and not target.is_symlink()
            and target.resolve().is_relative_to(root.resolve())
            and 0 < target.stat().st_size <= 1024 * 1024 * 1024,
            "UNAVAILABLE_OR_UNSAFE_ARTIFACT")
    return target


def apk_native_abis(path: Path) -> set[str]:
    """Read ZIP entries only, never extract app-controlled native files."""
    try:
        with ZipFile(path) as archive:
            entries = archive.namelist()
            require(len(entries) <= 100000, "APK_ENTRY_COUNT_EXCEEDED")
            names = {p.split("/")[1] for p in entries
                     if p.startswith("lib/") and p.endswith(".so")
                     and len(p.split("/")) == 3}
            require(names <= {"arm64-v8a", "armeabi-v7a", "x86", "x86_64"},
                    "UNKNOWN_NATIVE_ABI")
            return names
    except (BadZipFile, OSError) as exc:
        raise ProvenanceGateError("APK_ZIP_INVALID") from exc


def assess(
    request: dict[str, Any],
    build_contract: dict[str, Any], *,
    artifact_root: Path,
    apk_identity: Callable[[Path], dict[str, str]],
    apk_signing: Callable[[Path], dict[str, str]],
    aab_inspector: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate bytes and trusted platform inspection without publishing.

    When used by a real runner, inject AppLab's package_build_contract.apk_identity
    and apk_signing, and a separately trusted AAB verifier (jarsigner+bundletool).
    A fake inspector in unit tests is not trusted release evidence.
    """
    require(isinstance(request, dict) and isinstance(build_contract, dict),
            "INVALID_INPUT")
    require(request.get("schema_version") == 1, "UNKNOWN_SCHEMA")
    repo, sha, engine = (request.get(key) for key in
                         ("repository", "source_sha", "trusted_applab_sha"))
    require(isinstance(repo, str) and REPO.fullmatch(repo) is not None
            and isinstance(sha, str) and SHA40.fullmatch(sha) is not None
            and isinstance(engine, str) and SHA40.fullmatch(engine) is not None,
            "INVALID_SOURCE_IDENTITY")
    require(build_contract.get("repository") == repo
            and build_contract.get("resolved_sha") == sha
            and build_contract.get("trusted_applab_sha") == engine,
            "BUILD_CONTRACT_SOURCE_MISMATCH")
    pkg, v_name, v_code, cert = (request.get(key) for key in
                               ("package_id", "version_name", "version_code",
                                "expected_signing_cert_sha256"))
    require(isinstance(pkg, str) and re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", pkg) is not None
        and isinstance(v_name, str) and 0 < len(v_name) <= 100
        and isinstance(v_code, str) and VERSION.fullmatch(v_code) is not None
        and int(v_code) > 0 and isinstance(cert, str)
        and SHA256.fullmatch(cert) is not None, "INVALID_RELEASE_IDENTITY")
    run_id=request.get("workflow_run_id")
    run_repo=request.get("workflow_repository")
    require(type(run_id) is int and run_id > 0, "MISSING_WORKFLOW_RUN")
    require(isinstance(run_repo, str) and REPO.fullmatch(run_repo) is not None
            and run_repo in (repo, "riccardopinato/AppLab"),
            "UNTRUSTED_WORKFLOW_REPOSITORY")
    items=request.get("artifacts")
    require(isinstance(items, list) and 1 <= len(items) <= 4,
            "ARTIFACT_COUNT_INVALID")
    require(callable(apk_identity) and callable(apk_signing),
            "TRUSTED_APK_INSPECTOR_REQUIRED")
    seen=set()
    results=[]
    for item in items:
        require(isinstance(item, dict), "INVALID_ARTIFACT_ENTRY")
        kind, abi=item.get("kind"),item.get("abi")
        require(kind in KINDS and abi in SCOPES
                and ((kind == "AAB") == (abi == "bundle")),
                "INVALID_ARTIFACT_SCOPE")
        require((kind, abi) not in seen, "DUPLICATE_ARTIFACT_SCOPE")
        seen.add((kind, abi))
        filename=item.get("relative_path")
        require(isinstance(filename, str) and filename.lower().endswith(
            ".apk" if kind == "APK" else ".aab"), "ARTIFACT_TYPE_MISMATCH")
        path=confined_artifact(artifact_root, filename)
        claimed_sha=item.get("sha256")
        claimed_size=item.get("size_bytes")
        require(isinstance(claimed_sha, str)
                and SHA256.fullmatch(claimed_sha) is not None
                and type(claimed_size) is int and claimed_size > 0,
                "MISSING_ARTIFACT_DIGEST")
        require(path.stat().st_size == claimed_size and digest_file(path) == claimed_sha,
                "ARTIFACT_BYTES_MISMATCH")
        artifact_id=item.get("artifact_id")
        url=item.get("artifact_url")
        require(type(artifact_id) is int and artifact_id > 0
                and url == (f"https://github.com/{run_repo}/actions/runs/"
                            f"{run_id}/artifacts/{artifact_id}"),
                "UNBOUND_ARTIFACT_URL")
        if kind == "APK":
            identity=apk_identity(path)
            signing=apk_signing(path)
            require(isinstance(identity, dict) and isinstance(signing, dict),
                    "APK_INSPECTION_UNAVAILABLE")
            actual=(identity.get("package_id"),identity.get("version_name"),
                    str(identity.get("version_code", "")))
            signing_sha=signing.get("certificate_sha256")
            actual_abis=apk_native_abis(path)
            require((abi == "universal" and
                     (not actual_abis or {"arm64-v8a", "armeabi-v7a"} <= actual_abis))
                    or (abi != "universal" and actual_abis == {abi}),
                    "APK_ABI_SCOPE_MISMATCH")
            require(actual == (pkg,v_name,v_code), "APK_MANIFEST_IDENTITY_MISMATCH")
            require(signing_sha == cert, "APK_SIGNING_CERT_MISMATCH")
            source_apk=build_contract.get("apk")
            require(isinstance(source_apk, dict)
                    and source_apk.get("sha256") == claimed_sha
                    and source_apk.get("size_bytes") == claimed_size
                    and source_apk.get("package_id") == pkg
                    and source_apk.get("version_name") == v_name
                    and str(source_apk.get("version_code")) == v_code
                    and source_apk.get("signing_cert_sha256") == cert
                    and source_apk.get("build_variant") == "release",
                    "CANONICAL_APK_BUILD_CONTRACT_MISMATCH")
        else:
            # An AAB's signature does not attest source provenance by itself.
            # It must first match trusted source-bound build-contract bytes.
            source_aab=build_contract.get("aab")
            require(isinstance(source_aab, dict)
                    and source_aab.get("sha256") == claimed_sha
                    and source_aab.get("size_bytes") == claimed_size
                    and source_aab.get("package_id") == pkg
                    and source_aab.get("version_name") == v_name
                    and str(source_aab.get("version_code")) == v_code
                    and source_aab.get("signing_cert_sha256") == cert
                    and source_aab.get("build_variant") == "release",
                    "SOURCE_BOUND_AAB_BUILD_CONTRACT_REQUIRED")
            require(callable(aab_inspector), "AAB_VERIFIER_NOT_CONFIGURED")
            identity=aab_inspector(path)
            require(isinstance(identity, dict)
                    and identity.get("signature_verified") is True
                    and identity.get("package_id") == pkg
                    and identity.get("version_name") == v_name
                    and str(identity.get("version_code")) == v_code
                    and identity.get("certificate_sha256") == cert,
                    "AAB_SIGNATURE_OR_IDENTITY_NOT_VERIFIED")
        results.append({"kind":kind, "abi":abi, "sha256":claimed_sha,
                        "size_bytes":claimed_size, "artifact_url":url})
    return {
        "schema_version":1,"record_type":"X10_SIGNED_RELEASE_PROVENANCE_CANDIDATE",
        "authority":"SOURCE_BOUND_ONLY", "repository":repo,"source_sha":sha,
        "trusted_applab_sha":engine,"package_id":pkg,"version_code":v_code,
        "version_name":v_name,"signing_cert_sha256":cert,"artifacts":results,
        "state":"PENDING_INDEPENDENT_REMOTE_AND_DEVICE_EVIDENCE",
        "workflow_run_id":run_id, "workflow_repository":run_repo,
        "artifact_urls_verified_remotely":False,
        "trusted_runtime_verified":False,"device_verified":False,
        "store_ready":False,"production_released":False,
    }
