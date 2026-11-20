#!/usr/bin/env python3
"""Produce REA signals from AppLab's own compiled-artifact evidence.

The trusted runner binds the checkout, built APK, merged Android manifest and
Android SDK aapt binary. Neither source comments nor WorkItem text can invent
a diagnostic signal. Missing prerequisites cause a normal source-first SKIP.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

PERMISSION = re.compile(r"uses-permission(?:-sdk-23)?:\s*name='([^']+)'")
ANDROID_NAME = "{http://schemas.android.com/apk/res/android}name"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _regular(path: Path) -> bool:
    return path.is_absolute() and path.is_file() and not path.is_symlink()


def from_trusted_apk(repo_root: Path, stack: str) -> dict | None:
    """Return context from a real machine-observed permission divergence.

    The optional probe is silent without a fully attested local build. The
    canonical REA router still independently checks all authorization gates.
    """
    names = (
        "APPLAB_REA_AUTHORIZED_ARTIFACT", "APPLAB_REA_AUTHORIZED_REPOSITORY",
        "APPLAB_REA_AUTHORIZED_SOURCE_SHA", "APPLAB_REA_TRUSTED_BIN",
        "APPLAB_REA_PRIVATE_OUTPUT_ROOT", "APPLAB_REA_MERGED_MANIFEST",
        "APPLAB_REA_TRUSTED_AAPT_BIN",
    )
    if not all(os.environ.get(k) for k in names):
        return None
    if stack not in {"flutter", "native_android"}:
        return None
    root = repo_root.resolve()
    try:
        apk = Path(os.environ["APPLAB_REA_AUTHORIZED_ARTIFACT"])
        manifest = Path(os.environ["APPLAB_REA_MERGED_MANIFEST"])
        aapt = Path(os.environ["APPLAB_REA_TRUSTED_AAPT_BIN"])
        sha = os.environ["APPLAB_REA_AUTHORIZED_SOURCE_SHA"].lower()
        if not all(_regular(p) for p in (apk, manifest, aapt)):
            return None
        if apk.suffix.lower() != ".apk" or manifest.stat().st_size > 262144:
            return None
        if not manifest.resolve().is_relative_to(root):
            return None
        checked = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        if checked.returncode != 0 or checked.stdout.strip().lower() != sha:
            return None
        expected = {
            node.get(ANDROID_NAME)
            for node in ET.parse(manifest).getroot()
            if node.tag in {"uses-permission", "uses-permission-sdk-23"}
            and node.get(ANDROID_NAME)
        }
        observed = subprocess.run(
            [str(aapt), "dump", "permissions", str(apk)],
            capture_output=True, text=True, check=False, timeout=15,
        )
        if observed.returncode != 0 or len(observed.stdout) > 131072:
            return None
        actual = set(PERMISSION.findall(observed.stdout))
        # Do not infer "no permissions" from an empty/unknown aapt response.
        if not actual and "uses-permission" not in observed.stdout:
            return None
        missing, added = sorted(expected - actual), sorted(actual - expected)
        ctx = {
            "repository": os.environ["APPLAB_REA_AUTHORIZED_REPOSITORY"],
            "source_sha": sha, "authorization": "OWNED",
            "artifact_path": str(apk), "artifact_sha256": _digest(apk),
            "artifact_kind": "APK", "stack": stack, "source_complete": True,
            "signals": ["PERMISSION_DECLARATION_MISMATCH"] if (missing or added) else [],
            "rea_bin": os.environ["APPLAB_REA_TRUSTED_BIN"],
            "output_dir": os.environ["APPLAB_REA_PRIVATE_OUTPUT_ROOT"],
        }
        if os.environ.get("APPLAB_REA_TRUSTED_ENTRY"):
            ctx["rea_entry"] = os.environ["APPLAB_REA_TRUSTED_ENTRY"]
        if os.environ.get("REA_JADX_MCP_JAR"):
            ctx["jadx_jar"] = os.environ["REA_JADX_MCP_JAR"]
        return ctx
    except (OSError, ValueError, ET.ParseError, subprocess.SubprocessError):
        return None
