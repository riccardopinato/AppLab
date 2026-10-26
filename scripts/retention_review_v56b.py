#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "integration/hardening/contracts/retention-v56b.json"
PIN_TOKENS = ("CERTIFICATION", "CERTIFIED", "PHYSICAL", "DISTRIBUTION", "STORE", "CROSS_APP", "CROSS-APP", "RELEASE")


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_contract() -> dict[str, Any]:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("mode") != "REVIEW_ONLY":
        raise ValueError("unsupported retention contract")
    if data.get("automatic_action") is not False:
        raise ValueError("v5.6B must remain review-only")
    return data


def load_store(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    db = sqlite3.connect(str(path))
    try:
        rows = db.execute("SELECT payload_json FROM evidence_refs ORDER BY created_at").fetchall()
    finally:
        db.close()
    out: list[dict[str, Any]] = []
    for (raw,) in rows:
        try:
            item = json.loads(raw)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def load_json_inventory(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("inventory must be a list")
    return [dict(x) for x in rows if isinstance(x, dict)]


def referenced_ids(path: Path | None) -> tuple[set[str], set[str]]:
    ids: set[str] = set()
    hashes: set[str] = set()
    if path is None or not path.is_file():
        return ids, hashes
    raw = path.read_text(encoding="utf-8", errors="ignore")
    rows: list[Any] = []
    try:
        payload = json.loads(raw)
        rows = payload if isinstance(payload, list) else payload.get("records", [payload]) if isinstance(payload, dict) else []
    except json.JSONDecodeError:
        for line in raw.splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for row in rows:
        if not isinstance(row, dict):
            continue
        for value in row.get("evidence_ref_ids", []) if isinstance(row.get("evidence_ref_ids"), list) else []:
            if str(value).strip():
                ids.add(str(value).strip())
        for value in row.get("content_sha256s", []) if isinstance(row.get("content_sha256s"), list) else []:
            if str(value).strip():
                hashes.add(str(value).strip())
        rid = str(row.get("evidence_ref_id", "")).strip()
        sha = str(row.get("content_sha256", "")).strip()
        if rid:
            ids.add(rid)
        if sha:
            hashes.add(sha)
    return ids, hashes


def classify(row: dict[str, Any], now: datetime, ids: set[str], hashes: set[str]) -> tuple[str, str]:
    retention = str(row.get("retention_class", "")).upper()
    category = str(row.get("evidence_class", "")).upper()
    rid = str(row.get("evidence_ref_id", "")).strip()
    sha = str(row.get("content_sha256", "")).strip()
    if retention == "RELEASE_CRITICAL":
        return "KEEP_PINNED", "RELEASE_CRITICAL"
    if any(token in category for token in PIN_TOKENS):
        return "KEEP_PINNED", "PROTECTED_CATEGORY"
    if rid in ids or sha in hashes:
        return "KEEP_PINNED", "REFERENCED_BY_RELEASE_HISTORY"
    expiry = parse_time(row.get("expires_at"))
    if expiry is None:
        return "KEEP_FAIL_CLOSED", "NO_VALID_EXPIRY"
    if expiry > now:
        return "KEEP_ACTIVE", "TTL_ACTIVE"
    return "EXPIRY_REVIEW", "TTL_EXPIRED_UNPINNED"


def build_report(rows: list[dict[str, Any]], now: datetime, ids: set[str], hashes: set[str]) -> dict[str, Any]:
    decisions = []
    for row in rows:
        state, reason = classify(row, now, ids, hashes)
        decisions.append({
            "evidence_ref_id": str(row.get("evidence_ref_id", "")),
            "repository": str(row.get("repository", "")),
            "resolved_sha": str(row.get("resolved_sha", "")),
            "retention_class": str(row.get("retention_class", "")),
            "evidence_class": str(row.get("evidence_class", "")),
            "storage_uri": str(row.get("storage_uri", "")),
            "expires_at": str(row.get("expires_at", "")),
            "state": state,
            "reason": reason,
        })
    return {
        "schema_version": 1,
        "mode": "REVIEW_ONLY",
        "automatic_action": False,
        "summary": {
            "records": len(decisions),
            "pinned": sum(x["state"] == "KEEP_PINNED" for x in decisions),
            "active": sum(x["state"] == "KEEP_ACTIVE" for x in decisions),
            "fail_closed": sum(x["state"] == "KEEP_FAIL_CLOSED" for x in decisions),
            "expiry_review": sum(x["state"] == "EXPIRY_REVIEW" for x in decisions),
        },
        "decisions": decisions,
        "boundaries": [
            "durable metadata remains append-only",
            "release-history references always pin matching records",
            "runtime physical distribution and certification classes remain distinct",
        ],
    }


def self_test() -> None:
    load_contract()
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    rows = [
        {"evidence_ref_id":"release","retention_class":"RELEASE_CRITICAL","evidence_class":"CERTIFICATION","expires_at":"2026-01-01T00:00:00Z"},
        {"evidence_ref_id":"physical","retention_class":"STANDARD","evidence_class":"PHYSICAL_DEVICE","expires_at":"2026-01-01T00:00:00Z"},
        {"evidence_ref_id":"history","content_sha256":"sha256:"+"c"*64,"retention_class":"STANDARD","evidence_class":"RUNTIME","expires_at":"2026-01-01T00:00:00Z"},
        {"evidence_ref_id":"expired","retention_class":"STANDARD","evidence_class":"RUNTIME","expires_at":"2026-01-01T00:00:00Z"},
        {"evidence_ref_id":"active","retention_class":"STANDARD","evidence_class":"RUNTIME","expires_at":"2027-01-01T00:00:00Z"},
        {"evidence_ref_id":"missing","retention_class":"STANDARD","evidence_class":"RUNTIME"},
    ]
    report = build_report(rows, now, {"history"}, set())
    states = {x["evidence_ref_id"]: x["state"] for x in report["decisions"]}
    assert states["release"] == "KEEP_PINNED"
    assert states["physical"] == "KEEP_PINNED"
    assert states["history"] == "KEEP_PINNED"
    assert states["expired"] == "EXPIRY_REVIEW"
    assert states["active"] == "KEEP_ACTIVE"
    assert states["missing"] == "KEEP_FAIL_CLOSED"
    assert report["automatic_action"] is False
    print("AppLab v5.6B retention review self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-json", default="")
    parser.add_argument("--durable-store", default="")
    parser.add_argument("--release-history", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    rows: list[dict[str, Any]] = []
    if args.inventory_json:
        rows.extend(load_json_inventory(Path(args.inventory_json)))
    if args.durable_store:
        rows.extend(load_store(Path(args.durable_store)))
    if not rows:
        raise SystemExit("retention inventory is required")
    ids, hashes = referenced_ids(Path(args.release_history) if args.release_history else None)
    report = build_report(rows, datetime.now(timezone.utc), ids, hashes)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
