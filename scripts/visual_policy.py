#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PROFILE_THRESHOLDS: dict[str, dict[str, float]] = {
    "strict": {
        "error_mean": 34.0,
        "error_ratio": 0.44,
        "warn_mean": 12.0,
        "warn_ratio": 0.18,
        "error_text_similarity": 0.55,
        "error_node_delta": 0.45,
        "error_interactive_delta": 0.55,
        "warn_text_similarity": 0.78,
        "warn_node_delta": 0.22,
        "warn_interactive_delta": 0.30,
    },
    "standard": {
        "error_mean": 45.0,
        "error_ratio": 0.55,
        "warn_mean": 20.0,
        "warn_ratio": 0.30,
        "error_text_similarity": 0.45,
        "error_node_delta": 0.60,
        "error_interactive_delta": 0.75,
        "warn_text_similarity": 0.70,
        "warn_node_delta": 0.35,
        "warn_interactive_delta": 0.50,
    },
    "dynamic": {
        "error_mean": 65.0,
        "error_ratio": 0.72,
        "warn_mean": 32.0,
        "warn_ratio": 0.50,
        "error_text_similarity": 0.30,
        "error_node_delta": 0.85,
        "error_interactive_delta": 1.00,
        "warn_text_similarity": 0.52,
        "warn_node_delta": 0.60,
        "warn_interactive_delta": 0.80,
    },
}

THRESHOLD_KEYS = frozenset(next(iter(PROFILE_THRESHOLDS.values())).keys())
MAX_MASKS = 32
MAX_REGEX = 24
MAX_REGEX_LENGTH = 240


def _number(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    result = float(value)
    if result < 0:
        raise ValueError(f"{key} cannot be negative")
    return result


def _mask(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError("visual mask must be an object")
    result = {
        key: _number(raw.get(key), f"mask.{key}")
        for key in ("x", "y", "width", "height")
    }
    if result["width"] <= 0 or result["height"] <= 0:
        raise ValueError("visual mask width/height must be positive")
    if result["x"] > 1 or result["y"] > 1:
        raise ValueError("visual mask x/y must be normalized to 0..1")
    if result["width"] > 1 or result["height"] > 1:
        raise ValueError("visual mask width/height must be normalized to 0..1")
    if result["x"] + result["width"] > 1.000001:
        raise ValueError("visual mask extends beyond the screen width")
    if result["y"] + result["height"] > 1.000001:
        raise ValueError("visual mask extends beyond the screen height")
    return result


def _regexes(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_REGEX:
        raise ValueError("ignore_text_regex must be a bounded array")
    result: list[str] = []
    for value in raw:
        if not isinstance(value, str) or len(value) > MAX_REGEX_LENGTH:
            raise ValueError("ignore_text_regex contains an invalid expression")
        re.compile(value)
        result.append(value)
    return result


def _partial(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("visual policy must be an object")

    unknown = set(raw) - {
        "profile",
        "auto_mask_dynamic_views",
        "masks",
        "ignore_text_regex",
        "thresholds",
    }
    if unknown:
        raise ValueError(f"unknown visual policy keys: {sorted(unknown)}")

    result: dict[str, Any] = {}
    if "profile" in raw:
        profile = str(raw["profile"])
        if profile not in PROFILE_THRESHOLDS:
            raise ValueError(f"unknown visual profile: {profile}")
        result["profile"] = profile

    if "auto_mask_dynamic_views" in raw:
        if not isinstance(raw["auto_mask_dynamic_views"], bool):
            raise ValueError("auto_mask_dynamic_views must be boolean")
        result["auto_mask_dynamic_views"] = raw["auto_mask_dynamic_views"]

    if "masks" in raw:
        masks = raw["masks"]
        if not isinstance(masks, list) or len(masks) > MAX_MASKS:
            raise ValueError("masks must be a bounded array")
        result["masks"] = [_mask(item) for item in masks]

    if "ignore_text_regex" in raw:
        result["ignore_text_regex"] = _regexes(raw["ignore_text_regex"])

    if "thresholds" in raw:
        thresholds = raw["thresholds"]
        if not isinstance(thresholds, dict):
            raise ValueError("thresholds must be an object")
        unknown_thresholds = set(thresholds) - THRESHOLD_KEYS
        if unknown_thresholds:
            raise ValueError(
                f"unknown visual threshold keys: {sorted(unknown_thresholds)}"
            )
        result["thresholds"] = {
            key: _number(value, f"thresholds.{key}")
            for key, value in thresholds.items()
        }
    return result


def validate_config(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {"schema_version": 1, "defaults": {}, "checkpoints": {}}
    if not isinstance(payload, dict):
        raise ValueError("visual config must be a JSON object")

    unknown = set(payload) - {"schema_version", "defaults", "checkpoints"}
    if unknown:
        raise ValueError(f"unknown visual config keys: {sorted(unknown)}")

    schema = int(payload.get("schema_version", 1))
    if schema != 1:
        raise ValueError(f"unsupported visual config schema: {schema}")

    defaults = _partial(payload.get("defaults", {}))
    raw_checkpoints = payload.get("checkpoints", {})
    if not isinstance(raw_checkpoints, dict):
        raise ValueError("visual config checkpoints must be an object")

    checkpoints: dict[str, Any] = {}
    for name, raw in raw_checkpoints.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name
        ):
            raise ValueError(f"invalid checkpoint policy name: {name!r}")
        checkpoints[name] = _partial(raw)

    return {
        "schema_version": 1,
        "defaults": defaults,
        "checkpoints": checkpoints,
    }


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return validate_config(None)
    return validate_config(json.loads(path.read_text(encoding="utf-8")))


def policy_for(config: dict[str, Any], checkpoint: str) -> dict[str, Any]:
    defaults = config.get("defaults", {})
    specific = config.get("checkpoints", {}).get(checkpoint, {})

    profile = specific.get("profile", defaults.get("profile", "standard"))
    if profile not in PROFILE_THRESHOLDS:
        raise ValueError(f"unknown visual profile: {profile}")

    thresholds = dict(PROFILE_THRESHOLDS[profile])
    thresholds.update(defaults.get("thresholds", {}))
    thresholds.update(specific.get("thresholds", {}))

    masks = [
        *defaults.get("masks", []),
        *specific.get("masks", []),
    ]
    regexes = [
        *defaults.get("ignore_text_regex", []),
        *specific.get("ignore_text_regex", []),
    ]

    return {
        "profile": profile,
        "auto_mask_dynamic_views": specific.get(
            "auto_mask_dynamic_views",
            defaults.get("auto_mask_dynamic_views", True),
        ),
        "masks": masks,
        "ignore_text_regex": regexes,
        "thresholds": thresholds,
    }


def self_test() -> None:
    config = validate_config(
        {
            "schema_version": 1,
            "defaults": {
                "profile": "standard",
                "ignore_text_regex": [r"^\\d{2}:\\d{2}$"],
            },
            "checkpoints": {
                "map": {
                    "profile": "dynamic",
                    "masks": [
                        {"x": 0.0, "y": 0.1, "width": 1.0, "height": 0.6}
                    ],
                }
            },
        }
    )
    policy = policy_for(config, "map")
    assert policy["profile"] == "dynamic"
    assert len(policy["masks"]) == 1
    assert policy["ignore_text_regex"]
    assert policy_for(config, "other")["profile"] == "standard"

    try:
        validate_config({"defaults": {"profile": "unknown"}})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown profile must fail")
    print("AppLab Visual Policy self-test PASS")


if __name__ == "__main__":
    self_test()
