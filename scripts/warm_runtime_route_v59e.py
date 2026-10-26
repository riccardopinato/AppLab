#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ENGINE_VERSION = "5.9E"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported warm runtime policy")
    if not isinstance(payload.get("enabled"), bool):
        raise ValueError("enabled must be boolean")
    if not isinstance(payload.get("global_kill_switch"), bool):
        raise ValueError("global_kill_switch must be boolean")
    repos = payload.get("repositories")
    if not isinstance(repos, dict):
        raise ValueError("repositories must be an object")
    for repo, cfg in repos.items():
        if not REPO_RE.fullmatch(str(repo)):
            raise ValueError(f"invalid repository: {repo}")
        if not isinstance(cfg, dict) or not isinstance(cfg.get("enabled"), bool):
            raise ValueError(f"invalid repository policy: {repo}")
    return payload


def evaluate(
    *,
    repository: str,
    cache_hit: bool,
    config: dict[str, Any],
    api_level: int,
    profile: str,
) -> dict[str, Any]:
    if not REPO_RE.fullmatch(repository):
        raise ValueError("repository must be owner/name")
    repo_cfg = config.get("repositories", {}).get(repository, {})
    admitted = bool(
        config.get("enabled")
        and not config.get("global_kill_switch")
        and repo_cfg.get("enabled") is True
    )
    profile_allowed = (
        int(repo_cfg.get("api_level", api_level)) == int(api_level)
        and str(repo_cfg.get("emulator_profile", profile)) == profile
    )
    warm = bool(admitted and profile_allowed and cache_hit)
    if warm:
        route = "WARM_TRUSTED_AVD"
        reason = "ALLOWLISTED_PRISTINE_AVD_CACHE_HIT"
    elif admitted and profile_allowed:
        route = "GITHUB_ACTIONS_COLD"
        reason = "PRISTINE_AVD_CACHE_MISS"
    elif config.get("global_kill_switch"):
        route = "GITHUB_ACTIONS_COLD"
        reason = "GLOBAL_KILL_SWITCH"
    elif not admitted:
        route = "GITHUB_ACTIONS_COLD"
        reason = "REPOSITORY_NOT_ADMITTED"
    else:
        route = "GITHUB_ACTIONS_COLD"
        reason = "RUNTIME_PROFILE_NOT_ADMITTED"

    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "record_type": "WARM_RUNTIME_ROUTE_V59E",
        "authority": "ORCHESTRATION_ONLY",
        "repository": repository,
        "route": route,
        "reason": reason,
        "warm_runtime_admitted": warm,
        "cache_hit": bool(cache_hit),
        "api_level": int(api_level),
        "emulator_profile": profile,
        "github_actions_fallback": True,
        "coverage_reduction_enabled": False,
        "trusted_verifier_authority_unchanged": True,
        "certification_authority_unchanged": True,
    }


def self_test() -> None:
    cfg = {
        "enabled": True,
        "global_kill_switch": False,
        "repositories": {
            "owner/app": {
                "enabled": True,
                "api_level": 35,
                "emulator_profile": "pixel_7_pro",
            }
        },
    }
    warm = evaluate(
        repository="owner/app", cache_hit=True, config=cfg,
        api_level=35, profile="pixel_7_pro",
    )
    assert warm["route"] == "WARM_TRUSTED_AVD"
    cold = evaluate(
        repository="owner/app", cache_hit=False, config=cfg,
        api_level=35, profile="pixel_7_pro",
    )
    assert cold["route"] == "GITHUB_ACTIONS_COLD"
    other = evaluate(
        repository="owner/other", cache_hit=True, config=cfg,
        api_level=35, profile="pixel_7_pro",
    )
    assert other["route"] == "GITHUB_ACTIONS_COLD"
    cfg["global_kill_switch"] = True
    killed = evaluate(
        repository="owner/app", cache_hit=True, config=cfg,
        api_level=35, profile="pixel_7_pro",
    )
    assert killed["route"] == "GITHUB_ACTIONS_COLD"
    print("AppLab v5.9E warm runtime route self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default="")
    parser.add_argument("--cache-hit", default="false")
    parser.add_argument("--config", default="config/warm-runtime-production.json")
    parser.add_argument("--api-level", type=int, default=35)
    parser.add_argument("--emulator-profile", default="pixel_7_pro")
    parser.add_argument("--output", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    payload = evaluate(
        repository=args.repository,
        cache_hit=str(args.cache_hit).lower() == "true",
        config=load_config(Path(args.config)),
        api_level=args.api_level,
        profile=args.emulator_profile,
    )
    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"route={payload['route']}\n")
            handle.write(
                "warm_runtime_admitted="
                + str(payload["warm_runtime_admitted"]).lower()
                + "\n"
            )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
