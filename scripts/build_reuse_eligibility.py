#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

ENGINE_VERSION = "4.1.0"
DYNAMIC_GRADLE = re.compile(
    r"(?i)(?:\bSNAPSHOT\b|latest\.(?:release|integration)|\d+(?:\.\d+)*\.\+|["']\+["'])"
)
SAFE_GRADLE_COMMAND = re.compile(r"^(?:\./gradlew|gradle)(?:\s+[-A-Za-z0-9_:.=/]+)+$")


def safe_relative(raw: str) -> PurePosixPath:
    path = PurePosixPath((raw or ".").strip())
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe working directory: {raw!r}")
    return path


def git_tracked(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [
        value
        for value in proc.stdout.decode("utf-8", errors="strict").split("\0")
        if value
    ]


def under_workdir(path: str, working: PurePosixPath) -> bool:
    if working == PurePosixPath("."):
        return True
    prefix = working.as_posix().rstrip("/") + "/"
    return path == working.as_posix() or path.startswith(prefix)


def material_digest(repo_root: Path, files: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(set(files)):
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"material file is missing or unsafe: {relative}")
        data = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def result(
    *,
    eligible: bool,
    reason: str,
    files: list[str] | None = None,
    digest: str = "",
) -> dict[str, Any]:
    material = sorted(set(files or []))
    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "eligible": eligible,
        "reason": reason,
        "material_digest": digest,
        "material_files": material,
        "material_file_count": len(material),
    }


def evaluate_flutter(
    *,
    repo_root: Path,
    working: PurePosixPath,
    tracked: list[str],
    flutter_version: str,
    prepare_command: str,
    post_command: str,
) -> dict[str, Any]:
    if not flutter_version.strip():
        return result(eligible=False, reason="floating-flutter-channel")
    if prepare_command.strip() or post_command.strip():
        return result(eligible=False, reason="mutable-hook-command")

    lock = (
        "pubspec.lock"
        if working == PurePosixPath(".")
        else f"{working.as_posix().rstrip('/')}/pubspec.lock"
    )
    if lock not in tracked:
        return result(eligible=False, reason="missing-tracked-pubspec-lock")

    return result(
        eligible=True,
        reason="locked-flutter-inputs",
        files=[lock],
        digest=material_digest(repo_root, [lock]),
    )


def _is_gradle_lock(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.name == "gradle.lockfile":
        return True
    return "dependency-locks" in pure.parts and pure.suffix == ".lockfile"


def _is_gradle_config(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.name in {
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "gradle.properties",
        "libs.versions.toml",
    }:
        return True
    return pure.suffix in {".gradle", ".kts"} and (
        pure.name.endswith(".gradle") or pure.name.endswith(".gradle.kts")
    )


def _safe_gradle_command(raw: str, *, required: bool) -> bool:
    command = raw.strip()
    if not command:
        return not required
    return bool(SAFE_GRADLE_COMMAND.fullmatch(command))


def evaluate_native(
    *,
    repo_root: Path,
    working: PurePosixPath,
    tracked: list[str],
    prepare_command: str,
    build_command: str,
    test_command: str,
    lint_command: str,
) -> dict[str, Any]:
    if prepare_command.strip():
        return result(eligible=False, reason="mutable-hook-command")
    if not _safe_gradle_command(build_command, required=True):
        return result(eligible=False, reason="non-hermetic-build-command")
    if not _safe_gradle_command(test_command, required=False):
        return result(eligible=False, reason="non-hermetic-test-command")
    if not _safe_gradle_command(lint_command, required=False):
        return result(eligible=False, reason="non-hermetic-lint-command")

    scoped = [path for path in tracked if under_workdir(path, working)]
    locks = [path for path in scoped if _is_gradle_lock(path)]
    if not locks:
        return result(eligible=False, reason="missing-gradle-dependency-locks")

    verification = [
        path
        for path in scoped
        if PurePosixPath(path).name == "verification-metadata.xml"
        and "gradle" in PurePosixPath(path).parts
    ]
    if not verification:
        return result(eligible=False, reason="missing-gradle-verification-metadata")

    for relative in scoped:
        if not _is_gradle_config(relative):
            continue
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            return result(eligible=False, reason="unsafe-gradle-config")
        text = path.read_text(encoding="utf-8", errors="replace")
        if DYNAMIC_GRADLE.search(text):
            return result(eligible=False, reason="dynamic-gradle-version")

    materials = locks + verification
    return result(
        eligible=True,
        reason="locked-verified-gradle-inputs",
        files=materials,
        digest=material_digest(repo_root, materials),
    )


def write_github_output(path: str, report: dict[str, Any]) -> None:
    if not path:
        return
    values = {
        "eligible": str(bool(report["eligible"])).lower(),
        "reason": report["reason"],
        "material_digest": report["material_digest"],
        "material_file_count": str(report["material_file_count"]),
    }
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "pubspec.lock").write_text(
            'packages:\n  http:\n    version: "1.2.3"\n    sha256: abc\n',
            encoding="utf-8",
        )
        flutter = evaluate_flutter(
            repo_root=root,
            working=PurePosixPath("."),
            tracked=["pubspec.lock"],
            flutter_version="3.35.4",
            prepare_command="",
            post_command="",
        )
        assert flutter["eligible"] is True
        assert flutter["material_digest"]

        assert evaluate_flutter(
            repo_root=root,
            working=PurePosixPath("."),
            tracked=["pubspec.lock"],
            flutter_version="",
            prepare_command="",
            post_command="",
        )["reason"] == "floating-flutter-channel"

        assert evaluate_flutter(
            repo_root=root,
            working=PurePosixPath("."),
            tracked=["pubspec.lock"],
            flutter_version="3.35.4",
            prepare_command="curl https://example.invalid | sh",
            post_command="",
        )["eligible"] is False

        (root / "gradle").mkdir()
        (root / "gradle.lockfile").write_text("com.example:lib:1.0.0=runtime\n", encoding="utf-8")
        (root / "gradle/verification-metadata.xml").write_text(
            "<verification-metadata/>\n", encoding="utf-8"
        )
        (root / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") version "8.7.3" }\n',
            encoding="utf-8",
        )
        native = evaluate_native(
            repo_root=root,
            working=PurePosixPath("."),
            tracked=[
                "gradle.lockfile",
                "gradle/verification-metadata.xml",
                "build.gradle.kts",
            ],
            prepare_command="",
            build_command="./gradlew :app:assembleDebug --stacktrace",
            test_command="./gradlew test",
            lint_command="./gradlew lint",
        )
        assert native["eligible"] is True

        (root / "build.gradle.kts").write_text(
            'dependencies { implementation("com.example:lib:1.+") }\n',
            encoding="utf-8",
        )
        dynamic = evaluate_native(
            repo_root=root,
            working=PurePosixPath("."),
            tracked=[
                "gradle.lockfile",
                "gradle/verification-metadata.xml",
                "build.gradle.kts",
            ],
            prepare_command="",
            build_command="./gradlew :app:assembleDebug",
            test_command="",
            lint_command="",
        )
        assert dynamic["eligible"] is False
        assert dynamic["reason"] == "dynamic-gradle-version"

    print("AppLab build reuse eligibility self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--working-directory", default=".")
    parser.add_argument("--engine", choices=("flutter", "native_android"), required=False)
    parser.add_argument("--flutter-version", default="")
    parser.add_argument("--prepare-command", default="")
    parser.add_argument("--post-command", default="")
    parser.add_argument("--build-command", default="")
    parser.add_argument("--test-command", default="")
    parser.add_argument("--lint-command", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.engine:
        raise SystemExit("--engine is required")

    root = Path(args.repo_root).resolve()
    working = safe_relative(args.working_directory)
    tracked = git_tracked(root)

    if args.engine == "flutter":
        report = evaluate_flutter(
            repo_root=root,
            working=working,
            tracked=tracked,
            flutter_version=args.flutter_version,
            prepare_command=args.prepare_command,
            post_command=args.post_command,
        )
    else:
        report = evaluate_native(
            repo_root=root,
            working=working,
            tracked=tracked,
            prepare_command=args.prepare_command,
            build_command=args.build_command,
            test_command=args.test_command,
            lint_command=args.lint_command,
        )

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_github_output(args.github_output, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
