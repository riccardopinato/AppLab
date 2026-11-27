#!/usr/bin/env python3
"""Source-bound Android APK anomaly probe for existing AppLab build runners.

Only a unique merged manifest and verified built APK may emit a REA signal.
Without tools/rights, write a PROPOSE/SKIP report, never certify or mutate.
"""
from __future__ import annotations

import argparse
import json
import os
import hashlib
import re
import shutil
from pathlib import Path

import package_build_contract
import rea_anomaly_feed
import rea_auto_router

SKIP = {"status": "SKIP", "reason_codes": ["NO_UNAMBIGUOUS_TRUSTED_APK_PERMISSION_EVIDENCE"],
        "signals": [], "certification": "NONE", "donor_admission": "RESEARCH_ONLY"}


def merged_manifest(source: Path, work: Path) -> Path | None:
    """Discover one merged manifest across application modules, not just app."""
    if not work.is_relative_to(source):
        return None
    roots = {work / "build"}
    for container in (work, work / "android"):
        if container.is_dir() and not container.is_symlink():
            modules = [p for p in container.iterdir()
                       if p.is_dir() and not p.is_symlink()
                       and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", p.name)]
            if len(modules) > 60:
                return None
            roots.update(p / "build" for p in modules)
    found: dict[str, Path] = {}
    for root in sorted(roots):
        if not root.is_dir() or root.is_symlink():
            continue
        for path in root.glob("**/merged_manifests/**/AndroidManifest.xml"):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source):
                found[str(path.resolve())] = path.resolve()
                if len(found) > 1:
                    return None
    return next(iter(found.values())) if len(found) == 1 else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def capture(args: argparse.Namespace) -> None:
    """Copy exactly one machine-generated manifest outside the later git clean."""
    source = args.source_root.resolve()
    manifest = merged_manifest(source, (source / args.working_directory).resolve())
    if manifest is None or manifest.stat().st_size > 262144:
        print(json.dumps({"manifest": "NOT_CAPTURED_AMBIGUOUS_OR_MISSING"}))
        return
    destination = args.output
    if not destination.is_absolute() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("Manifest snapshot must be a private absolute runner path")
    if destination.resolve().is_relative_to(source):
        raise ValueError("Snapshot must survive target checkout cleanup")
    if destination.exists():
        raise ValueError("Manifest snapshot must not overwrite existing evidence")
    shutil.copyfile(manifest, destination)
    if _sha256(manifest) != _sha256(destination):
        destination.unlink(missing_ok=True)
        raise ValueError("Manifest snapshot identity mismatch")
    digest = _sha256(destination)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as out:
            out.write(f"manifest_file={destination}\n")
            out.write(f"manifest_sha256={digest}\n")
    print(json.dumps({"manifest": "CAPTURED_HASHED", "sha256": digest}))


def build(args: argparse.Namespace) -> tuple[dict, bool, bool]:
    source = args.source_root.resolve()
    work = (source / args.working_directory).resolve()
    preserved = os.environ.get("APPLAB_REA_PRESERVED_MANIFEST", "")
    manifest = Path(preserved) if preserved else merged_manifest(source, work)
    aapt = package_build_contract.android_build_tool("aapt")
    if not manifest or not aapt:
        return dict(SKIP), False, False
    if preserved:
        digest = os.environ.get("APPLAB_REA_PRESERVED_MANIFEST_SHA256", "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            return dict(SKIP), False, False
        if manifest.is_symlink() or not manifest.is_file() or _sha256(manifest) != digest.lower():
            return dict(SKIP), False, False
        os.environ["APPLAB_REA_MERGED_MANIFEST_SHA256"] = digest
    os.environ["APPLAB_REA_MERGED_MANIFEST"] = str(manifest)
    os.environ["APPLAB_REA_TRUSTED_AAPT_BIN"] = str(Path(aapt).resolve())
    context = rea_anomaly_feed.from_trusted_apk(source, args.stack)
    if context is None:
        return dict(SKIP), False, False
    plan = rea_auto_router.decide(context)
    gap = bool(context["signals"])
    owned = context.get("authorization") == "OWNED"
    if args.execute_eligible and gap:
        plan = rea_auto_router.execute(context, plan)
    return plan, gap, owned


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", required=True, type=Path)
    p.add_argument("--working-directory", default=".")
    p.add_argument("--stack", choices=("flutter", "native_android"), required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--github-output", type=Path)
    p.add_argument("--execute-eligible", action="store_true")
    p.add_argument("--capture-manifest", action="store_true",
                   help="Snapshot the unique merged manifest before checkout cleanup")
    a = p.parse_args()
    if a.capture_manifest:
        capture(a)
        return 0
    report, gap, owned = build(a)
    public = {
        "schema_version": 1,
        "status": report["status"], "signals": report.get("signals", []),
        "reason_codes": report.get("reason_codes", []),
        "score": report.get("score", 0),
        "mode": report.get("mode"), "operations": report.get("operations", []),
        "execution": report.get("execution", "NOT_REQUESTED"),
        "certification": "NONE", "donor_admission": "RESEARCH_ONLY",
        "artifact_executed": False,
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if a.github_output:
        with a.github_output.open("a", encoding="utf-8") as out:
            out.write(f"binary_gap={'true' if gap else 'false'}\n")
            out.write(f"owned={'true' if owned else 'false'}\n")
    print(json.dumps({"rea_status": public["status"], "research_execution": public["execution"],
                      "binary_gap": gap, "owned": owned}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
