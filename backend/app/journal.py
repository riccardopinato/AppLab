from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionJournal:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("APPLAB_HISTORY_PATH", "/tmp/applab-history.jsonl"))
        self._lock = threading.Lock()

    def append(
        self,
        action: str,
        status: str,
        *,
        package_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "status": status,
            "package_id": package_id or "",
            "details": details or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()

        entries: list[dict[str, Any]] = []
        for line in lines[-max(1, min(limit, 200)):]:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                entries.append(value)
        entries.reverse()
        return entries
