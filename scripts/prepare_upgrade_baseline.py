#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(
    source_apk: Path,
    baseline_dir: Path,
    repository: str,
    resolved_sha: str,
    version: str,
) -> dict:
    if not source_apk.is_file() or source_apk.stat().st_size <= 0:
        raise ValueError("source APK is missing or empty")
    baseline_dir.mkdir(parents=True, exist_ok=True)
    target = baseline_dir / "baseline.apk"
    shutil.copy2(source_apk, target)
    payload = {
        "schema_version": 1,
        "applab_version": version,
        "repository": repository,
        "resolved_sha": resolved_sha,
        "size_bytes": target.stat().st_size,
        "sha256": sha256(target),
    }
    (baseline_dir / "baseline.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "app.apk"
        source.write_bytes(b"upgrade-baseline")
        payload = prepare(
            source,
            root / "baseline",
            "owner/repo",
            "a" * 40,
            "0.7.5",
        )
        assert payload["sha256"] == sha256(source)
        assert (root / "baseline/baseline.apk").read_bytes() == source.read_bytes()
    print("AppLab upgrade baseline self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-apk")
    parser.add_argument("--baseline-dir")
    parser.add_argument("--repository", default="")
    parser.add_argument("--resolved-sha", default="")
    parser.add_argument("--version", default="0.7.5")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.source_apk or not args.baseline_dir:
        parser.error("--source-apk and --baseline-dir are required")
    payload = prepare(
        Path(args.source_apk),
        Path(args.baseline_dir),
        args.repository,
        args.resolved_sha,
        args.version,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
