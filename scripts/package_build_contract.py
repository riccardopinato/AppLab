#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import smart_test_plan
from pathlib import Path, PurePosixPath

ALLOWED_EVIDENCE_SUFFIXES = {".yaml", ".yml", ".json"}
MAX_FLOW_BYTES = 1_048_576
MAX_EVIDENCE_BYTES = 10_485_760

def safe_relative(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw or ".")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe relative path: {raw!r}")
    return path

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def copy_evidence_file(source: Path, destination: Path) -> int:
    if source.is_symlink():
        raise ValueError(f"Symlink is not allowed in build contract: {source}")
    if not source.is_file():
        return 0
    if source.suffix.lower() not in ALLOWED_EVIDENCE_SUFFIXES:
        return 0
    size = source.stat().st_size
    if size > MAX_FLOW_BYTES:
        raise ValueError(f"Journey evidence file is too large: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return size

def copy_maestro_tree(repo_root: Path, relative_root: PurePosixPath, output_root: Path) -> int:
    source_root = repo_root / Path(relative_root) / ".maestro"
    if not source_root.is_dir():
        return 0
    total = 0
    for source in sorted(source_root.rglob("*")):
        if source.is_symlink():
            raise ValueError(f"Symlink is not allowed in .maestro: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(repo_root)
        total += copy_evidence_file(source, output_root / relative)
        if total > MAX_EVIDENCE_BYTES:
            raise ValueError("Journey evidence exceeds contract size limit")
    return total

def package(args: argparse.Namespace) -> dict:
    repo_root = Path(args.repo_root).resolve()
    apk = Path(args.apk).resolve()
    output = Path(args.output).resolve()
    working = safe_relative(args.working_directory)
    flow = safe_relative(args.maestro_flow) if args.maestro_flow else None

    if not apk.is_file() or apk.stat().st_size <= 0:
        raise ValueError(f"APK missing or empty: {apk}")
    try:
        apk.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("APK must be inside target repository") from exc

    if output.exists():
        shutil.rmtree(output)
    evidence_root = output / "target-evidence"
    evidence_root.mkdir(parents=True)

    shutil.copy2(apk, output / "app.apk")

    total = copy_maestro_tree(repo_root, PurePosixPath("."), evidence_root)
    if working != PurePosixPath("."):
        total += copy_maestro_tree(repo_root, working, evidence_root)

    if flow:
        source = repo_root / Path(flow)
        total += copy_evidence_file(source, evidence_root / Path(flow))
        if not (evidence_root / Path(flow)).is_file():
            raise ValueError(f"Configured Maestro flow is unavailable or unsupported: {flow}")

    if total > MAX_EVIDENCE_BYTES:
        raise ValueError("Journey evidence exceeds contract size limit")

    contract = {
        "schema_version": 1,
        "applab_version": "0.7.10",
        "repository": args.repository,
        "resolved_sha": args.resolved_sha,
        "engine": args.engine,
        "working_directory": str(working),
        "package_id": args.package_id.strip(),
        "maestro_flow": str(flow) if flow else "",
        "analysis_mode": args.analysis_mode,
        "analysis_plan": "analysis-plan.json",
        "apk": {
            "path": "app.apk",
            "size_bytes": (output / "app.apk").stat().st_size,
            "sha256": sha256(output / "app.apk"),
        },
        "evidence_bytes": total,
    }
    plan = smart_test_plan.classify(
        smart_test_plan.git_changed_files(repo_root),
        args.analysis_mode,
    )
    smart_test_plan.validate_plan(plan)
    (output / "analysis-plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    (output / "contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return contract

def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "repo"
        root.mkdir()
        apk = root / "app.apk"
        apk.write_bytes(b"APK")
        flow = root / ".maestro" / "smoke.yaml"
        flow.parent.mkdir()
        flow.write_text("appId: example\n---\n- assertVisible: Home\n", encoding="utf-8")
        out = Path(raw) / "out"
        args = argparse.Namespace(
            repo_root=str(root), apk=str(apk), output=str(out),
            repository="owner/repo", resolved_sha="a"*40, engine="flutter",
            working_directory=".", package_id="com.example.app",
            maestro_flow=".maestro/smoke.yaml",
            analysis_mode="fast",
        )
        contract = package(args)
        assert contract["apk"]["sha256"] == sha256(out / "app.apk")
        assert (out / "target-evidence/.maestro/smoke.yaml").is_file()
        assert (out / "analysis-plan.json").is_file()
    print("AppLab build contract packager self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--apk")
    parser.add_argument("--output")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--engine", choices=("flutter", "native_android"), default="flutter")
    parser.add_argument("--working-directory", default=".")
    parser.add_argument("--package-id", default="")
    parser.add_argument("--maestro-flow", default="")
    parser.add_argument("--analysis-mode", choices=("fast", "full"), default="full")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.apk or not args.output:
        raise SystemExit("--repo-root, --apk and --output are required")
    contract = package(args)
    print(json.dumps(contract, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
