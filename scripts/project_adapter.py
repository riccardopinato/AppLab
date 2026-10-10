#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ADAPTER_VERSION = "4.3.0"
SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 64 * 1024
CONFIG_CANDIDATES = ("applab.project.json", ".applab/project.json")
ALLOWED_PROJECT_TYPES = {"auto", "flutter", "native_android"}
ALLOWED_TOP_LEVEL = {
    "schema_version",
    "project_type",
    "working_directory",
    "package_id",
    "toolchain",
    "release_artifact_pattern",
    "journeys",
    "physical_validation",
}
ALLOWED_TOOLCHAIN = {
    "flutter_channel",
    "flutter_version",
    "java_version",
    "gradle_version",
    "compile_sdk",
    "build_tools",
}
ALLOWED_JOURNEYS = {"primary", "settings", "critical"}
ALLOWED_PHYSICAL = {"required", "capabilities"}
FLOW_SUFFIXES = {".yaml", ".yml"}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def safe_relative(raw: str, *, allow_glob: bool = False) -> str:
    value = (raw or ".").strip().replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe relative path: {raw!r}")
    if not allow_glob and any(ch in value for ch in "*?["):
        raise ValueError(f"Glob syntax is not allowed here: {raw!r}")
    normalized = path.as_posix()
    return normalized or "."


def expect_dict(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def reject_unknown(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def find_config(repo_root: Path) -> Path | None:
    found: list[Path] = []
    for relative in CONFIG_CANDIDATES:
        candidate = repo_root / relative
        if candidate.exists():
            found.append(candidate)
    if len(found) > 1:
        raise ValueError(
            "Multiple AppLab project adapter configs found; keep only one of "
            + ", ".join(CONFIG_CANDIDATES)
        )
    if not found:
        return None
    path = found[0]
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Adapter config must be a regular file: {path}")
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError("Adapter config exceeds 64 KiB")
    return path


def load_config(repo_root: Path) -> tuple[dict[str, Any], str]:
    path = find_config(repo_root)
    if path is None:
        return {}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path.relative_to(repo_root)}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("AppLab project adapter config must be a JSON object")
    reject_unknown(payload, ALLOWED_TOP_LEVEL, "adapter config")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("adapter config schema_version must be 1")
    return payload, path.relative_to(repo_root).as_posix()


def git_head(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        marker = read_text(repo_root / ".applab-test-head").strip().lower()
        if re.fullmatch(r"[0-9a-f]{40}", marker):
            return marker
        raise ValueError("Unable to resolve target repository HEAD") from exc
    sha = completed.stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Target repository HEAD is not an immutable 40-character SHA")
    return sha


def flutter_identity(project_root: Path) -> tuple[str, str]:
    text = read_text(project_root / "pubspec.yaml")
    match = re.search(r"^\s*version:\s*([^\s+#]+)(?:\+([0-9]+))?\s*$", text, re.MULTILINE)
    if not match:
        return "", ""
    return match.group(1).strip(), (match.group(2) or "").strip()


def native_identity(project_root: Path) -> tuple[str, str]:
    chunks = []
    for relative in ("app/build.gradle.kts", "app/build.gradle"):
        path = project_root / relative
        if path.is_file():
            chunks.append(read_text(path))
    text = "\n".join(chunks)
    version_name = ""
    version_code = ""
    match = re.search(r'versionName\s*(?:=|\s)\s*["\']([^"\']+)["\']', text)
    if match:
        version_name = match.group(1).strip()
    match = re.search(r"versionCode\s*(?:=|\s)\s*([0-9]+)", text)
    if match:
        version_code = match.group(1).strip()
    return version_name, version_code


def validate_flow(repo_root: Path, raw: str, label: str) -> str:
    if not raw:
        return ""
    relative = safe_relative(raw)
    path = repo_root / relative
    if path.suffix.lower() not in FLOW_SUFFIXES:
        raise ValueError(f"{label} must point to a .yaml or .yml file")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} does not exist as a regular file: {relative}")
    return relative


def auto_journeys(repo_root: Path, autodiscovery: dict[str, Any]) -> dict[str, Any]:
    primary = str(autodiscovery.get("maestro_flow", "") or "").strip()
    settings = ""
    critical: list[str] = []
    candidates: list[Path] = []
    root_maestro = repo_root / ".maestro"
    if root_maestro.is_dir():
        candidates.extend(sorted(root_maestro.glob("*.y*ml")))
    working = safe_relative(str(autodiscovery.get("working_directory", ".") or "."))
    if working != ".":
        working_maestro = repo_root / working / ".maestro"
        if working_maestro.is_dir():
            candidates.extend(sorted(working_maestro.glob("*.y*ml")))

    seen: set[str] = set()
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(repo_root).as_posix()
        if relative in seen:
            continue
        seen.add(relative)
        name = path.name.lower()
        if not settings and "setting" in name:
            settings = relative
        if any(token in name for token in ("critical", "release", "core")):
            critical.append(relative)
    critical = [item for item in critical if item != primary and item != settings][:16]
    return {"primary": primary, "settings": settings, "critical": critical}


def load_certification_real_device(repo_root: Path, working_directory: str) -> bool:
    candidates = [repo_root / ".maestro" / "applab-certification.json"]
    if working_directory != ".":
        candidates.append(
            repo_root / working_directory / ".maestro" / "applab-certification.json"
        )
    required = False
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError(f"Certification policy too large: {path.relative_to(repo_root)}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError(f"Invalid certification policy: {path.relative_to(repo_root)}")
        value = payload.get("requires_real_device", False)
        if not isinstance(value, bool):
            raise ValueError("requires_real_device must be boolean")
        required = required or value
    return required


def validate_string(value: Any, label: str, *, max_length: int = 256) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    value = value.strip()
    if len(value) > max_length:
        raise ValueError(f"{label} is too long")
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError(f"{label} contains control characters")
    return value


def build_profile(
    repo_root: Path,
    autodiscovery: dict[str, Any],
    repository: str,
    target_ref: str,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    config, config_path = load_config(repo_root)

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository.strip()):
        raise ValueError("repository must use owner/name format")
    target_ref = validate_string(target_ref, "target_ref") or "main"

    base = dict(autodiscovery)
    if base.get("schema_version") != 1 or base.get("engine") not in {"flutter", "native_android"}:
        raise ValueError("Unsupported auto-discovery profile")

    engine = str(base["engine"])
    config_type = validate_string(config.get("project_type", "auto"), "project_type")
    if config_type not in ALLOWED_PROJECT_TYPES:
        raise ValueError("project_type must be auto, flutter or native_android")
    if config_type != "auto" and config_type != engine:
        raise ValueError(
            f"Configured project_type {config_type!r} contradicts auto-discovered engine {engine!r}"
        )

    working = safe_relative(str(base.get("working_directory", ".") or "."))
    configured_working = config.get("working_directory")
    if configured_working is not None:
        asserted = safe_relative(validate_string(configured_working, "working_directory"))
        if asserted != working:
            raise ValueError(
                f"Configured working_directory {asserted!r} does not match "
                f"auto-discovered {working!r}; v1 adapter treats this field as an assertion"
            )
    project_root = repo_root if working == "." else repo_root / working
    if not project_root.is_dir():
        raise ValueError(f"Auto-discovered working_directory does not exist: {working}")

    package_override = validate_string(config.get("package_id"), "package_id")
    if package_override:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", package_override):
            raise ValueError("package_id is not a valid Android application id")
        base["package_id"] = package_override

    toolchain = expect_dict(config.get("toolchain"), "toolchain")
    reject_unknown(toolchain, ALLOWED_TOOLCHAIN, "toolchain")
    for key, raw in toolchain.items():
        value = validate_string(raw, f"toolchain.{key}", max_length=64)
        if value:
            base[key] = value

    release_pattern = validate_string(
        config.get("release_artifact_pattern"), "release_artifact_pattern", max_length=512
    )
    if release_pattern:
        release_pattern = safe_relative(release_pattern, allow_glob=True)
    else:
        release_pattern = safe_relative(str(base.get("certification_apk_path", "") or ""))

    journeys = auto_journeys(repo_root, base)
    configured_journeys = expect_dict(config.get("journeys"), "journeys")
    reject_unknown(configured_journeys, ALLOWED_JOURNEYS, "journeys")
    if "primary" in configured_journeys:
        journeys["primary"] = validate_flow(
            repo_root,
            validate_string(configured_journeys.get("primary"), "journeys.primary", max_length=512),
            "journeys.primary",
        )
    if "settings" in configured_journeys:
        journeys["settings"] = validate_flow(
            repo_root,
            validate_string(configured_journeys.get("settings"), "journeys.settings", max_length=512),
            "journeys.settings",
        )
    if "critical" in configured_journeys:
        raw_critical = configured_journeys["critical"]
        if not isinstance(raw_critical, list) or len(raw_critical) > 16:
            raise ValueError("journeys.critical must be an array with at most 16 entries")
        values: list[str] = []
        for index, item in enumerate(raw_critical):
            value = validate_flow(
                repo_root,
                validate_string(item, f"journeys.critical[{index}]", max_length=512),
                f"journeys.critical[{index}]",
            )
            if value and value not in values:
                values.append(value)
        journeys["critical"] = values
    if journeys["primary"]:
        base["maestro_flow"] = journeys["primary"]

    physical = expect_dict(config.get("physical_validation"), "physical_validation")
    reject_unknown(physical, ALLOWED_PHYSICAL, "physical_validation")
    requested = physical.get("required", False)
    if not isinstance(requested, bool):
        raise ValueError("physical_validation.required must be boolean")
    raw_caps = physical.get("capabilities", [])
    if not isinstance(raw_caps, list) or len(raw_caps) > 32:
        raise ValueError("physical_validation.capabilities must be an array with at most 32 entries")
    capabilities: list[str] = []
    for index, item in enumerate(raw_caps):
        value = validate_string(item, f"physical_validation.capabilities[{index}]", max_length=64)
        if not value or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
            raise ValueError(f"Invalid physical capability label: {value!r}")
        normalized = value.lower()
        if normalized not in capabilities:
            capabilities.append(normalized)

    policy_required = load_certification_real_device(repo_root, working)
    physical_required = bool(requested or policy_required or capabilities)

    version_name, version_code = (
        flutter_identity(project_root) if engine == "flutter" else native_identity(project_root)
    )
    resolved_sha = git_head(repo_root)
    base.update(
        {
            "adapter_schema_version": SCHEMA_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "repository": repository.strip(),
            "target_ref": target_ref,
            "resolved_sha": resolved_sha,
            "project_type": engine,
            "working_directory": working,
            "version_name": version_name,
            "version_code": version_code,
            "release_artifact_pattern": release_pattern,
            "journeys": journeys,
            "physical_validation": {
                "required": physical_required,
                "capabilities": capabilities,
                "certification_policy_requires_real_device": policy_required,
            },
            "adapter_config": {"present": bool(config_path), "path": config_path},
        }
    )
    fingerprint_payload = dict(base)
    fingerprint_payload.pop("profile_fingerprint", None)
    base["profile_fingerprint"] = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return base


def write_github_output(path: Path, profile: dict[str, Any]) -> None:
    compact = json.dumps(profile, separators=(",", ":"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"engine={profile['engine']}\n")
        handle.write(f"resolved_sha={profile['resolved_sha']}\n")
        handle.write(f"profile_fingerprint={profile['profile_fingerprint']}\n")
        handle.write(f"profile={compact}\n")


def self_test() -> None:
    base_flutter = {
        "schema_version": 1,
        "detected": True,
        "engine": "flutter",
        "working_directory": ".",
        "flutter_channel": "stable",
        "flutter_version": "3.35.0",
        "java_version": "17",
        "certification_apk_path": "build/app/outputs/flutter-apk/app-release.apk",
        "package_id": "com.example.demo",
        "maestro_flow": ".maestro/applab-smoke.yaml",
    }
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / ".applab-test-head").write_text("a" * 40, encoding="utf-8")
        (root / "pubspec.yaml").write_text("name: demo\nversion: 1.4.2+17\n", encoding="utf-8")
        (root / ".maestro").mkdir()
        for name in ("applab-smoke.yaml", "settings.yaml", "critical-export.yaml"):
            (root / ".maestro" / name).write_text("appId: com.example.demo\n", encoding="utf-8")
        (root / "applab.project.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_type": "flutter",
                    "working_directory": ".",
                    "package_id": "com.example.demo",
                    "toolchain": {"java_version": "21"},
                    "release_artifact_pattern": "build/app/outputs/flutter-apk/app-release.apk",
                    "journeys": {
                        "primary": ".maestro/applab-smoke.yaml",
                        "settings": ".maestro/settings.yaml",
                        "critical": [".maestro/critical-export.yaml"],
                    },
                    "physical_validation": {"required": True, "capabilities": ["gps", "background"]},
                }
            ),
            encoding="utf-8",
        )
        profile = build_profile(root, base_flutter, "owner/demo", "main")
        assert profile["resolved_sha"] == "a" * 40
        assert profile["project_type"] == "flutter"
        assert profile["version_name"] == "1.4.2"
        assert profile["version_code"] == "17"
        assert profile["java_version"] == "21"
        assert profile["journeys"]["settings"] == ".maestro/settings.yaml"
        assert profile["journeys"]["critical"] == [".maestro/critical-export.yaml"]
        assert profile["physical_validation"]["required"] is True
        assert len(profile["profile_fingerprint"]) == 64

    base_native = {
        "schema_version": 1,
        "detected": True,
        "engine": "native_android",
        "working_directory": ".",
        "java_version": "17",
        "gradle_version": "8.14.3",
        "certification_apk_path": "app/build/outputs/apk/release/app-release.apk",
        "package_id": "com.example.native",
        "maestro_flow": "",
    }
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / ".applab-test-head").write_text("b" * 40, encoding="utf-8")
        (root / "app").mkdir()
        (root / "app" / "build.gradle.kts").write_text(
            'android { defaultConfig { applicationId = "com.example.native"\nversionCode = 9\nversionName = "2.0.1" } }\n',
            encoding="utf-8",
        )
        (root / ".maestro").mkdir()
        (root / ".maestro" / "applab-certification.json").write_text(
            json.dumps({"schema_version": 1, "requires_real_device": True}),
            encoding="utf-8",
        )
        profile = build_profile(root, base_native, "owner/native", "release")
        assert profile["version_name"] == "2.0.1"
        assert profile["version_code"] == "9"
        assert profile["physical_validation"]["required"] is True
        assert profile["adapter_config"]["present"] is False

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / ".applab-test-head").write_text("c" * 40, encoding="utf-8")
        (root / "pubspec.yaml").write_text("name: demo\nversion: 1.0.0+1\n")
        (root / "applab.project.json").write_text(
            json.dumps({"schema_version": 1, "project_type": "native_android"}),
            encoding="utf-8",
        )
        try:
            build_profile(root, base_flutter, "owner/demo", "main")
        except ValueError as exc:
            assert "contradicts" in str(exc)
        else:
            raise AssertionError("project_type contradiction must fail")

    print("AppLab v4.3 project adapter self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--autodiscovery")
    parser.add_argument("--repository")
    parser.add_argument("--target-ref", default="main")
    parser.add_argument("--output")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.autodiscovery or not args.repository:
        raise SystemExit("--repo-root, --autodiscovery and --repository are required unless --self-test is used")
    payload = json.loads(Path(args.autodiscovery).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("auto-discovery profile must be a JSON object")
    profile = build_profile(Path(args.repo_root), payload, args.repository, args.target_ref)
    text = json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
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
    except (OSError, ValueError, AssertionError, json.JSONDecodeError) as exc:
        raise SystemExit(f"AppLab project adapter failed: {exc}") from exc
