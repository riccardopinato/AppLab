#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


IGNORED_DIRS = {
    ".git",
    ".dart_tool",
    ".gradle",
    ".idea",
    "build",
    "node_modules",
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def files_under(root: Path, names: set[str] | None = None) -> list[Path]:
    result: list[Path] = []
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        completed = None

    if completed is not None and completed.returncode == 0:
        for raw in completed.stdout.decode("utf-8", errors="ignore").split("\0"):
            if not raw:
                continue
            path = root / raw
            if any(part in IGNORED_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            if names is None or path.name in names:
                result.append(path)
        return result

    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if names is None or path.name in names:
            result.append(path)
    return result


def workflow_text(root: Path) -> str:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return ""
    chunks = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        chunks.append(read_text(path))
    return "\n".join(chunks)


def rel(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    return value or "."


def detect_flutter_root(root: Path) -> Path | None:
    candidates = files_under(root, {"pubspec.yaml"})
    if not candidates:
        return None

    def score(pubspec: Path) -> tuple[int, int, str]:
        project = pubspec.parent
        value = 0
        if project == root:
            value += 100
        if (project / "lib" / "main.dart").is_file():
            value += 60
        text = read_text(pubspec)
        if re.search(r"^\s*flutter:\s*$", text, re.MULTILINE):
            value += 20
        depth = len(project.relative_to(root).parts)
        return (-value, depth, project.as_posix())

    return sorted(candidates, key=score)[0].parent


def detect_native_root(root: Path) -> Path | None:
    names = {"settings.gradle", "settings.gradle.kts"}
    candidates = files_under(root, names)
    if not candidates:
        build_candidates = files_under(root, {"build.gradle", "build.gradle.kts"})
        candidates = [
            path
            for path in build_candidates
            if (path.parent / "app").is_dir()
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (len(p.parent.relative_to(root).parts), p.as_posix()))
    return candidates[0].parent


def first_regex(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        if match:
            value = match.group(1)
            return value.strip() if value is not None else ""
    return ""


def detect_package_id(project: Path) -> str:
    paths = [
        project / "android" / "app" / "build.gradle.kts",
        project / "android" / "app" / "build.gradle",
        project / "app" / "build.gradle.kts",
        project / "app" / "build.gradle",
    ]
    for path in paths:
        text = read_text(path)
        value = first_regex(
            text,
            [
                r'applicationId\s*=\s*["\']([^"\']+)["\']',
                r'applicationId\s+["\']([^"\']+)["\']',
                r'namespace\s*=\s*["\']([^"\']+)["\']',
            ],
        )
        if value:
            return value

    manifests = list(project.rglob("AndroidManifest.xml"))
    for manifest in manifests:
        value = first_regex(read_text(manifest), [r'package=["\']([^"\']+)["\']'])
        if value:
            return value
    return ""


def detect_java_version(root: Path, project: Path, workflows: str) -> str:
    value = first_regex(
        workflows,
        [
            r"java-version:\s*[\"']?([0-9]+)",
            r"JAVA_VERSION:\s*[\"']?([0-9]+)",
        ],
    )
    if value:
        return value

    gradle_text = "\n".join(
        read_text(path)
        for path in files_under(
            project,
            {"build.gradle", "build.gradle.kts", "gradle.properties"},
        )
    )
    value = first_regex(
        gradle_text,
        [
            r"JavaVersion\.VERSION_([0-9]+)",
            r"jvmTarget\s*=\s*[\"']([0-9]+)",
        ],
    )
    return value or "17"


def detect_flutter_version(workflows: str) -> str:
    return first_regex(
        workflows,
        [
            r"flutter-version:\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)",
            r"FLUTTER_VERSION:\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)",
        ],
    )


def detect_repo_owner(root: Path) -> str:
    config = read_text(root / ".git" / "config")
    owner = first_regex(
        config,
        [
            r"github\.com[/:]([A-Za-z0-9_.-]+)/[A-Za-z0-9_.-]+(?:\.git)?",
        ],
    )
    return re.sub(r"[^A-Za-z0-9_]", "_", owner).lower()


def detect_pubspec_name(project: Path) -> str:
    return first_regex(
        read_text(project / "pubspec.yaml"),
        [r"^name:\s*([A-Za-z0-9_]+)\s*$"],
    )


def detect_gradle_version(project: Path, workflows: str) -> str:
    wrapper = project / "gradle" / "wrapper" / "gradle-wrapper.properties"
    value = first_regex(
        read_text(wrapper),
        [r"gradle-([0-9]+(?:\.[0-9]+){1,2})-(?:bin|all)\.zip"],
    )
    if value:
        return value
    value = first_regex(
        workflows,
        [r"gradle-version:\s*[\"']?([0-9]+(?:\.[0-9]+){1,2})"],
    )
    return value or "8.14.3"


def detect_min_sdk(project: Path) -> str:
    text = "\n".join(
        read_text(path)
        for path in files_under(project, {"build.gradle", "build.gradle.kts", "AndroidManifest.xml"})
    )
    return first_regex(
        text,
        [
            r"minSdk\s*=\s*([0-9]+)",
            r"minSdkVersion\s+([0-9]+)",
            r"android:minSdkVersion=[\"']([0-9]+)[\"']",
        ],
    ) or "23"


def detect_compile_sdk(project: Path) -> str:
    text = "\n".join(
        read_text(path)
        for path in files_under(project, {"build.gradle", "build.gradle.kts"})
    )
    return first_regex(
        text,
        [
            r"compileSdk\s*=\s*([0-9]+)",
            r"compileSdkVersion\s+([0-9]+)",
        ],
    ) or "35"


def gradle_lines(workflows: str) -> list[str]:
    result = []
    for raw in workflows.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        match = re.search(r"(?:\./gradlew|gradle)\s+[^|#]+", line)
        if match:
            result.append(match.group(0).strip())
    return result


def pick_gradle_command(lines: list[str], token: str) -> str:
    token_lower = token.lower()
    for line in lines:
        lowered = line.lower()
        if token_lower in lowered:
            command = line.split("|", 1)[0].strip()
            command = re.sub(r"\s+#.*$", "", command).strip()
            return command
    return ""


def release_gradle_command(build_command: str, prefix: str) -> str:
    if re.search(r"release", build_command, re.IGNORECASE):
        return build_command
    if re.search(r"debug", build_command, re.IGNORECASE):
        return re.sub(r"debug", "Release", build_command, count=1, flags=re.IGNORECASE)
    return f"{prefix} assembleRelease --stacktrace"


def infer_apk_path(build_command: str) -> str:
    # Handle module/variant explicitly because the module group is optional.
    match = re.search(
        r"(?:^|\s)(?::([A-Za-z0-9_.-]+):)?assemble([A-Za-z0-9_.-]+)",
        build_command,
        re.IGNORECASE,
    )
    module = "app"
    variant = "debug"
    if match:
        if match.group(1):
            module = match.group(1)
        if match.group(2):
            variant = match.group(2).lower()
    filename = f"{module}-{variant}.apk"
    return f"{module}/build/outputs/apk/{variant}/{filename}"


def detect_maestro_flow(root: Path) -> str:
    preferred = [
        root / ".maestro" / "applab-smoke.yaml",
        root / ".maestro" / "smoke.yaml",
        root / ".maestro" / "applab-smoke.yml",
        root / ".maestro" / "smoke.yml",
    ]
    for path in preferred:
        if path.is_file():
            return rel(path, root)
    return ""


def flutter_profile(root: Path, project: Path, workflows: str) -> dict[str, Any]:
    pubspec = read_text(project / "pubspec.yaml")
    android_exists = (project / "android").is_dir()
    build_runner = bool(
        re.search(r"^\s*(build_runner|drift_dev):", pubspec, re.MULTILINE)
    )
    owner = detect_repo_owner(root)
    project_name = detect_pubspec_name(project)
    package_id = detect_package_id(project)
    prepare_command = ""

    if not android_exists:
        if owner:
            organization = f"com.{owner}"
            prepare_command = (
                f"flutter create --platforms=android --org {organization} ."
            )
            if not package_id and project_name:
                package_id = f"{organization}.{project_name}"
        else:
            prepare_command = "flutter create --platforms=android ."

    return {
        "schema_version": 1,
        "detected": True,
        "engine": "flutter",
        "working_directory": rel(project, root),
        "flutter_channel": "stable",
        "flutter_version": detect_flutter_version(workflows),
        "java_version": detect_java_version(root, project, workflows),
        "prepare_command": prepare_command,
        "post_pub_get_command": (
            "dart run build_runner build --delete-conflicting-outputs"
            if build_runner
            else ""
        ),
        "android_prepare_command": "",
        "api_level": "35",
        "min_sdk": detect_min_sdk(project),
        "emulator_profile": "pixel_7_pro",
        "apk_path": "build/app/outputs/flutter-apk/app-debug.apk",
        "certification_apk_path": "build/app/outputs/flutter-apk/app-release.apk",
        "package_id": package_id,
        "build_command": "flutter build apk --debug",
        "certification_build_command": "flutter build apk --release",
        "run_flutter_tests": True,
        "run_maestro": True,
        "maestro_flow": detect_maestro_flow(root),
        "detection": {
            "android_scaffold_present": android_exists,
            "build_runner_detected": build_runner,
        },
    }


def native_profile(root: Path, project: Path, workflows: str) -> dict[str, Any]:
    lines = gradle_lines(workflows)
    wrapper_exists = (project / "gradlew").is_file()
    prefix = "./gradlew" if wrapper_exists else "gradle"

    build_command = pick_gradle_command(lines, "assemble")
    if not build_command:
        build_command = f"{prefix} assembleDebug --stacktrace"

    test_command = pick_gradle_command(lines, "test")
    if not test_command:
        test_command = f"{prefix} testDebugUnitTest --stacktrace"

    lint_command = pick_gradle_command(lines, "lint")
    if not lint_command:
        lint_command = f"{prefix} lintDebug --stacktrace"

    compile_sdk = detect_compile_sdk(project)
    release_build_command = release_gradle_command(build_command, prefix)
    build_tools = first_regex(
        workflows,
        [r"build-tools;([0-9]+(?:\.[0-9]+){1,2})"],
    ) or f"{compile_sdk}.0.0"
    return {
        "schema_version": 1,
        "detected": True,
        "engine": "native_android",
        "working_directory": rel(project, root),
        "java_version": detect_java_version(root, project, workflows),
        "gradle_version": detect_gradle_version(project, workflows),
        "compile_sdk": compile_sdk,
        "min_sdk": detect_min_sdk(project),
        "build_tools": build_tools,
        "prepare_command": "",
        "test_command": test_command,
        "lint_command": lint_command,
        "build_command": build_command,
        "certification_build_command": release_build_command,
        "apk_path": infer_apk_path(build_command),
        "certification_apk_path": infer_apk_path(release_build_command),
        "package_id": detect_package_id(project),
        "verify_signature": True,
        "android_prepare_command": "",
        "api_level": "35",
        "emulator_profile": "pixel_7_pro",
        "run_maestro": True,
        "maestro_flow": detect_maestro_flow(root),
        "detection": {
            "gradle_wrapper_present": wrapper_exists,
            "workflow_gradle_commands": len(lines),
        },
    }


def discover(root: Path) -> dict[str, Any]:
    root = root.resolve()
    workflows = workflow_text(root)
    flutter = detect_flutter_root(root)
    native = detect_native_root(root)

    if flutter is not None:
        return flutter_profile(root, flutter, workflows)
    if native is not None:
        return native_profile(root, native, workflows)

    raise ValueError(
        "Unable to recognize a Flutter or native Android/Gradle project."
    )


def write_github_output(path: Path, profile: dict[str, Any]) -> None:
    compact = json.dumps(profile, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"engine={profile['engine']}\n")
        handle.write(f"profile={compact}\n")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)

        flutter = root / "flutter_app"
        (flutter / "lib").mkdir(parents=True)
        (flutter / "lib" / "main.dart").write_text("void main() {}\n")
        (flutter / "pubspec.yaml").write_text(
            "name: demo\n"
            "dependencies:\n  flutter:\n    sdk: flutter\n"
            "dev_dependencies:\n  build_runner: any\n"
        )
        profile = discover(root)
        assert profile["engine"] == "flutter"
        assert profile["working_directory"] == "flutter_app"
        assert "flutter create" in profile["prepare_command"]
        assert "build_runner" in profile["post_pub_get_command"]
        assert profile["certification_build_command"] == "flutter build apk --release"
        assert profile["certification_apk_path"].endswith("app-release.apk")

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "app").mkdir()
        (root / "settings.gradle.kts").write_text('rootProject.name = "Demo"\n')
        (root / "app" / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") }\n'
            'android { compileSdk = 36\n'
            ' defaultConfig { applicationId = "com.example.demo" } }\n'
        )
        workflows_dir = root / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "ci.yml").write_text(
            "steps:\n"
            "  - run: gradle testDebugUnitTest --stacktrace\n"
            "  - run: gradle lintSlim --stacktrace\n"
            "  - run: gradle assembleSlim --stacktrace\n"
            "  - uses: gradle/actions/setup-gradle@v4\n"
            "    with:\n      gradle-version: '9.6.0'\n"
        )
        profile = discover(root)
        assert profile["engine"] == "native_android"
        assert profile["package_id"] == "com.example.demo"
        assert profile["gradle_version"] == "9.6.0"
        assert profile["build_command"].startswith("gradle assembleSlim")
        assert profile["apk_path"] == "app/build/outputs/apk/slim/app-slim.apk"
        assert "assembleRelease" in profile["certification_build_command"]
        assert profile["certification_apk_path"].endswith("app-release.apk")

    print("AppLab v0.9 universal project auto-discovery self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--output")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if not args.repo_root:
        raise SystemExit("--repo-root is required unless --self-test is used")

    profile = discover(Path(args.repo_root))
    text = json.dumps(profile, indent=2, sort_keys=True) + "\n"

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")

    if args.github_output:
        write_github_output(Path(args.github_output), profile)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab auto-discovery failed: {exc}") from exc
