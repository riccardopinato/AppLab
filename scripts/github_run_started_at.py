#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime


def valid_started_at(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return raw


def fetch_started_at() -> str:
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not repository or not run_id or not token:
        return ""
    url = f"{api}/repos/{repository}/actions/runs/{run_id}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AppLab/0.9.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except Exception:
        return ""
    return valid_started_at(str(payload.get("run_started_at", "")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert valid_started_at("2026-09-27T08:00:00Z")
        assert valid_started_at("not-a-date") == ""
        print("AppLab workflow timing helper self-test PASS")
        return 0
    print(fetch_started_at())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
