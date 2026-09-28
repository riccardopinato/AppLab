#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MANIFEST_VERSION = "3.0.1"
MANIFEST_NAME = "trusted-evidence-manifest.json"


class EvidenceError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"Unable to read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"Expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_files(report_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(report_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == MANIFEST_NAME:
            continue
        files.append(path)
    return files


def derive_package_id(report_dir: Path) -> str:
    for name in ("result.json", "build-contract.json"):
        path = report_dir / name
        if not path.is_file():
            continue
        payload = read_json(path)
        value = str(payload.get("package_id", "")).strip()
        if value:
            return value
    return ""


def create_manifest(
    report_dir: Path,
    *,
    repository: str,
    resolved_sha: str,
    run_id: str,
    analysis_mode: str,
    contract_fingerprint: str,
    config_fingerprint: str,
    trusted_applab_sha: str,
) -> dict[str, Any]:
    if not report_dir.is_dir():
        raise EvidenceError(f"Evidence directory not found: {report_dir}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise EvidenceError("Invalid repository binding")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", resolved_sha):
        raise EvidenceError("resolved_sha must be a 40-character Git SHA")
    if not str(run_id).isdigit():
        raise EvidenceError("run_id must be numeric")

    result_path = report_dir / "result.json"
    contract_path = report_dir / "build-contract.json"
    if not result_path.is_file() or not contract_path.is_file():
        raise EvidenceError("Trusted evidence requires result.json and build-contract.json")

    result = read_json(result_path)
    contract = read_json(contract_path)
    package_id = derive_package_id(report_dir)
    if not package_id:
        raise EvidenceError("Trusted runtime evidence is missing package_id")

    checks = {
        "result_repository": str(result.get("repository", "")) == repository,
        "result_sha": str(result.get("resolved_sha", "")).lower() == resolved_sha.lower(),
        "result_run_id": str(result.get("workflow_run_id", "")) == str(run_id),
        "result_package_id": str(result.get("package_id", "")) == package_id,
        "contract_repository": str(contract.get("repository", "")) == repository,
        "contract_sha": str(contract.get("resolved_sha", "")).lower() == resolved_sha.lower(),
    }
    if not all(checks.values()):
        failed = ", ".join(key for key, ok in checks.items() if not ok)
        raise EvidenceError(f"Evidence binding mismatch while creating manifest: {failed}")

    entries = []
    for path in evidence_files(report_dir):
        relative = path.relative_to(report_dir).as_posix()
        entries.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "producer": "trusted-apk-verifier",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "binding": {
            "repository": repository,
            "resolved_sha": resolved_sha.lower(),
            "package_id": package_id,
            "workflow_run_id": str(run_id),
            "analysis_mode": analysis_mode,
            "contract_fingerprint": contract_fingerprint,
            "config_fingerprint": config_fingerprint,
            "trusted_applab_sha": trusted_applab_sha.lower(),
        },
        "result": {
            "result": str(result.get("result", "UNKNOWN")),
            "pipeline_status": str(result.get("pipeline_status", "UNKNOWN")),
        },
        "files": entries,
        "file_count": len(entries),
        "guardrails": {
            "generated_inside_trusted_verifier": True,
            "hashes_cover_all_evidence_files": True,
            "target_source_cannot_author_manifest": True,
        },
    }
    (report_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_manifest(
    report_dir: Path,
    *,
    expected_repository: str,
    expected_sha: str,
    expected_run_id: str | None = None,
    expected_package_id: str | None = None,
) -> dict[str, Any]:
    manifest_path = report_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise EvidenceError(f"Missing {MANIFEST_NAME}")
    manifest = read_json(manifest_path)
    if str(manifest.get("producer", "")) != "trusted-apk-verifier":
        raise EvidenceError("Evidence manifest producer is not trusted-apk-verifier")

    binding = manifest.get("binding")
    if not isinstance(binding, dict):
        raise EvidenceError("Evidence manifest is missing binding")

    failures: list[str] = []
    if str(binding.get("repository", "")) != expected_repository:
        failures.append("repository")
    if str(binding.get("resolved_sha", "")).lower() != expected_sha.lower():
        failures.append("resolved_sha")
    if expected_run_id is not None and str(binding.get("workflow_run_id", "")) != str(expected_run_id):
        failures.append("workflow_run_id")
    if expected_package_id is not None and str(binding.get("package_id", "")) != expected_package_id:
        failures.append("package_id")
    if not str(binding.get("package_id", "")).strip():
        failures.append("package_id_missing")
    if failures:
        raise EvidenceError("Trusted evidence binding mismatch: " + ", ".join(failures))

    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise EvidenceError("Evidence manifest contains no file hashes")

    listed: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceError("Invalid manifest file entry")
        relative = str(row.get("path", ""))
        expected_hash = str(row.get("sha256", ""))
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            raise EvidenceError(f"Unsafe manifest path: {relative!r}")
        path = report_dir / relative
        if not path.is_file():
            raise EvidenceError(f"Manifest file missing: {relative}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise EvidenceError(f"Evidence hash mismatch: {relative}")
        listed.add(relative)

    current = {
        path.relative_to(report_dir).as_posix()
        for path in evidence_files(report_dir)
    }
    if current != listed:
        missing = sorted(current - listed)
        extra = sorted(listed - current)
        raise EvidenceError(
            f"Evidence file set mismatch; unlisted={missing[:8]}, missing={extra[:8]}"
        )

    result = read_json(report_dir / "result.json")
    if str(result.get("repository", "")) != expected_repository:
        raise EvidenceError("result.json repository binding mismatch")
    if str(result.get("resolved_sha", "")).lower() != expected_sha.lower():
        raise EvidenceError("result.json SHA binding mismatch")
    if expected_run_id is not None and str(result.get("workflow_run_id", "")) != str(expected_run_id):
        raise EvidenceError("result.json workflow run binding mismatch")
    if str(result.get("package_id", "")) != str(binding.get("package_id", "")):
        raise EvidenceError("result.json package binding mismatch")

    return {
        "trusted": True,
        "producer": manifest["producer"],
        "binding": binding,
        "file_count": len(rows),
        "manifest_sha256": sha256_file(manifest_path),
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        sha = "a" * 40
        result = {
            "repository": "owner/demo",
            "resolved_sha": sha,
            "workflow_run_id": "12345",
            "package_id": "com.example.demo",
            "result": "PASS",
            "pipeline_status": "success",
        }
        contract = {
            "repository": "owner/demo",
            "resolved_sha": sha,
            "package_id": "com.example.demo",
        }
        (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (root / "build-contract.json").write_text(json.dumps(contract), encoding="utf-8")
        (root / "interaction-crawl.json").write_text('{"result":"PASS"}', encoding="utf-8")
        create_manifest(
            root,
            repository="owner/demo",
            resolved_sha=sha,
            run_id="12345",
            analysis_mode="full",
            contract_fingerprint="contract-1",
            config_fingerprint="config-1",
            trusted_applab_sha="b" * 40,
        )
        checked = validate_manifest(
            root,
            expected_repository="owner/demo",
            expected_sha=sha,
            expected_run_id="12345",
        )
        assert checked["trusted"] is True
        (root / "interaction-crawl.json").write_text('{"result":"FAIL"}', encoding="utf-8")
        try:
            validate_manifest(
                root,
                expected_repository="owner/demo",
                expected_sha=sha,
                expected_run_id="12345",
            )
        except EvidenceError:
            pass
        else:
            raise AssertionError("tampered evidence was not rejected")
    print("AppLab Trusted Evidence Manifest self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=("create", "validate"))
    parser.add_argument("--report-dir")
    parser.add_argument("--repository")
    parser.add_argument("--resolved-sha")
    parser.add_argument("--run-id")
    parser.add_argument("--package-id")
    parser.add_argument("--analysis-mode", default="full")
    parser.add_argument("--contract-fingerprint", default="manual")
    parser.add_argument("--config-fingerprint", default="manual")
    parser.add_argument("--trusted-applab-sha", default="")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.command:
        raise SystemExit("create or validate command is required")
    if not args.report_dir or not args.repository or not args.resolved_sha:
        raise SystemExit("--report-dir, --repository and --resolved-sha are required")

    root = Path(args.report_dir)
    if args.command == "create":
        if not args.run_id:
            raise SystemExit("--run-id is required for create")
        payload = create_manifest(
            root,
            repository=args.repository,
            resolved_sha=args.resolved_sha,
            run_id=args.run_id,
            analysis_mode=args.analysis_mode,
            contract_fingerprint=args.contract_fingerprint,
            config_fingerprint=args.config_fingerprint,
            trusted_applab_sha=args.trusted_applab_sha,
        )
    else:
        payload = validate_manifest(
            root,
            expected_repository=args.repository,
            expected_sha=args.resolved_sha,
            expected_run_id=args.run_id,
            expected_package_id=args.package_id,
        )

    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
