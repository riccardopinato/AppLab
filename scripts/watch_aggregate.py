#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not root.exists():
        return results
    for path in sorted(root.rglob("result.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict):
            payload["_artifact_path"] = str(path.relative_to(root))
            results.append(payload)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--history-file", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    current = read_results(Path(args.results_dir))
    history_path = Path(args.history_file)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    previous: list[dict[str, Any]] = []
    if history_path.exists():
        for line in history_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                previous.append(item)

    additions: list[dict[str, Any]] = []
    for result in current:
        additions.append(
            {
                "recorded_at": now,
                "watcher_run_id": args.run_id,
                "watcher_run_url": args.run_url,
                **{k: v for k, v in result.items() if not k.startswith("_")},
            }
        )

    combined = (previous + additions)[-1000:]
    history_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in combined),
        encoding="utf-8",
    )

    lines = [
        "# AppLab Repo Watcher",
        "",
        f"- Run: {args.run_url}",
        f"- New verification results: {len(current)}",
        f"- Central history records: {len(combined)}",
        "",
    ]

    if current:
        lines.extend(
            [
                "| Repository | SHA | Result | Maestro |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in current:
            repository = str(item.get("repository", "unknown"))
            sha = str(item.get("resolved_sha", ""))
            short_sha = sha[:8] if sha else "—"
            result = str(item.get("result", "UNKNOWN"))
            maestro = str(item.get("maestro", "—"))
            lines.append(f"| {repository} | \`{short_sha}\` | **{result}** | {maestro} |")
    else:
        lines.append("No new repository commits required AppLab verification in this run.")

    lines.append("")
    Path(args.summary_output).write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
