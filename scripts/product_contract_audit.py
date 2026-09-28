#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from product_review_common import bounded_text_files, load_json, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.1.0"

ALIASES = {
    "authentication": ("authentication", "auth", "login", "sign in", "account"),
    "local_persistence": ("local persistence", "offline-first", "offline first", "database", "room", "sqlite", "drift"),
    "network_api": ("network api", "api", "backend", "server"),
    "background_execution": ("background", "workmanager", "foreground service"),
    "notifications": ("notification", "notifications", "reminder", "push"),
    "monetization": ("premium", "subscription", "revenuecat", "billing", "iap", "admob"),
    "ai_or_ml": ("ai", "artificial intelligence", "llm", "machine learning", "gemini", "openai"),
    "export_or_backup": ("export", "backup", "restore"),
    "maps_or_location": ("maps", "map", "location", "gps", "geolocation"),
    "cloud_or_sync": ("sync", "cloud", "firebase", "supabase"),
}

EXCLUDED_PATTERNS = (
    r"\bno\b.{0,35}\b{term}\b",
    r"\bwithout\b.{0,35}\b{term}\b",
    r"\bsenza\b.{0,35}\b{term}\b",
    r"\bnon\b.{0,35}\b{term}\b",
    r"\bexclude(?:d|s)?\b.{0,35}\b{term}\b",
    r"\besclud\w*\b.{0,35}\b{term}\b",
    r"\bremove(?:d)?\b.{0,35}\b{term}\b",
    r"\brimos\w*\b.{0,35}\b{term}\b",
    r"\bout of scope\b.{0,35}\b{term}\b",
    r"\bfuori scope\b.{0,35}\b{term}\b",
)

FUTURE_MARKERS = (
    "future", "planned", "later", "roadmap", "todo", "to add", "will add",
    "next version", "next step", "futuro", "previsto", "più avanti",
    "prossimo step", "da aggiungere", "da valutare", "valutare",
)

PROMISE_MARKERS = (
    "supports", "supporta", "includes", "include", "available", "disponibile",
    "implemented", "implementato", "completed", "completato", "feature",
    "funzione", "funzionalità", "[x]",
)


def docs(root: Path) -> list[tuple[Path, str]]:
    names = [
        "README.md", "ROADMAP.md", "PRODUCT_BIBLE.md", "PRODUCT_BIBLE.txt",
        "FEATURES.md", "FEATURES.txt", "PROJECT_STATE.md",
    ]
    return bounded_text_files(root, names)


def alias_terms(label: str) -> tuple[str, ...]:
    return ALIASES.get(label, (label.replace("_", " "), label))


def line_mentions(line: str, label: str) -> bool:
    lower = line.lower()
    return any(re.search(rf"\b{re.escape(term.lower())}\b", lower) for term in alias_terms(label))


def excluded_line(line: str, label: str) -> bool:
    lower = line.lower()
    for term in alias_terms(label):
        escaped = re.escape(term.lower())
        if any(re.search(pattern.format(term=escaped), lower) for pattern in EXCLUDED_PATTERNS):
            return True
    return False


def classify_claim(line: str, label: str) -> str:
    lower = line.lower().strip()
    if excluded_line(line, label):
        return "EXCLUDED"
    if any(marker in lower for marker in FUTURE_MARKERS):
        return "FUTURE"
    if re.match(r"^\s*[-*]\s*\[[xX]\]\s+", line):
        return "PROMISED"
    if any(marker in lower for marker in PROMISE_MARKERS):
        return "PROMISED"
    return "MENTION_ONLY"


def collect_claims(documents: list[tuple[Path, str]], label: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    for path, text in documents:
        for number, line in enumerate(text.splitlines(), start=1):
            if not line_mentions(line, label):
                continue
            claims.append(
                {
                    "path": str(path),
                    "line": str(number),
                    "classification": classify_claim(line, label),
                    "text": line.strip()[:300],
                }
            )
            if len(claims) >= 30:
                return claims
    return claims


def contract_status(claims: list[dict[str, str]]) -> str:
    classes = {row["classification"] for row in claims}
    if "PROMISED" in classes and ("EXCLUDED" in classes or "FUTURE" in classes):
        return "CONTRADICTORY"
    if "PROMISED" in classes:
        return "PROMISED"
    if "EXCLUDED" in classes:
        return "EXCLUDED"
    if "FUTURE" in classes:
        return "FUTURE"
    if "MENTION_ONLY" in classes:
        return "MENTION_ONLY"
    return "UNMENTIONED"


def runtime_verification(label: str, behavioral: dict[str, Any], states: dict[str, Any]) -> str:
    state_map = states.get("states") if isinstance(states.get("states"), dict) else {}
    if label in {"network_api", "cloud_or_sync"}:
        return str((state_map.get("offline") or {}).get("status", "NOT_OBSERVED"))
    if label == "authentication":
        return str((state_map.get("auth") or {}).get("status", "NOT_OBSERVED"))
    if label == "background_execution":
        return str((state_map.get("background") or {}).get("status", "NOT_OBSERVED"))
    if label == "notifications":
        return str((state_map.get("permissions") or {}).get("status", "NOT_OBSERVED"))
    return str(behavioral.get("runtime_evidence_state", "NOT_OBSERVED"))


def build_report(
    root: Path,
    app: dict[str, Any],
    behavioral: dict[str, Any] | None,
    states: dict[str, Any] | None,
) -> dict[str, Any]:
    documents = docs(root)
    truth = app.get("feature_truth") if isinstance(app.get("feature_truth"), dict) else {}
    caps = truth.get("capabilities") if isinstance(truth.get("capabilities"), list) else []
    behavioral = behavioral or {}
    states = states or {}

    hierarchy_text = " ".join(
        " ".join(str(x) for x in row.get("matched_tokens", []))
        for row in behavioral.get("runtime_matched_surfaces", [])
        if isinstance(row, dict)
    ).lower()

    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for cap in caps:
        if not isinstance(cap, dict):
            continue
        label = str(cap.get("capability", "")).strip()
        if not label:
            continue

        claims = collect_claims(documents, label)
        status = contract_status(claims)
        implementation = str(cap.get("truth", "NOT_DETECTED"))
        reachable = any(term.lower() in hierarchy_text for term in alias_terms(label))
        verified = runtime_verification(label, behavioral, states)
        evidence = [
            f"{row['path']}:{row['line']} [{row['classification']}] {row['text']}"
            for row in claims[:10]
        ]

        row = {
            "capability": label,
            "contract_status": status,
            "promised": status == "PROMISED",
            "implementation": implementation,
            "runtime_reachable": "OBSERVED" if reachable else "NOT_OBSERVED",
            "runtime_verified": verified,
            "claims": claims,
            "contract_evidence": evidence,
        }
        rows.append(row)

        if status == "CONTRADICTORY":
            findings.append(
                {
                    "kind": "CONTRADICTORY_PRODUCT_CONTRACT",
                    "severity": "REVIEW",
                    "capability": label,
                    "message": "Product documentation contains conflicting promised/future/excluded claims for this capability.",
                    "evidence": evidence,
                }
            )
        elif status == "PROMISED" and implementation not in {"CODE_CONFIRMED", "CONFIG_SIGNAL"}:
            findings.append(
                {
                    "kind": "PROMISED_WITHOUT_IMPLEMENTATION_EVIDENCE",
                    "severity": "HIGH_REVIEW" if implementation == "NOT_DETECTED" else "REVIEW",
                    "capability": label,
                    "message": "The product contract promises this capability without strong bounded implementation evidence.",
                    "evidence": evidence,
                }
            )
        elif status == "EXCLUDED" and implementation == "CODE_CONFIRMED":
            findings.append(
                {
                    "kind": "IMPLEMENTED_BUT_EXCLUDED_BY_CONTRACT",
                    "severity": "REVIEW",
                    "capability": label,
                    "message": "Code evidence exists for a capability explicitly excluded by the bounded product contract.",
                    "evidence": evidence,
                }
            )
        elif implementation == "CODE_CONFIRMED" and status == "UNMENTIONED" and documents:
            provenance = cap.get("provenance") if isinstance(cap.get("provenance"), dict) else {}
            findings.append(
                {
                    "kind": "IMPLEMENTED_WITHOUT_PRODUCT_CONTRACT",
                    "severity": "INFO",
                    "capability": label,
                    "message": "Implementation evidence exists but the bounded product contract does not mention the capability.",
                    "evidence": provenance.get("CODE", []) if isinstance(provenance.get("CODE"), list) else [],
                }
            )

        if (
            implementation == "CODE_CONFIRMED"
            and status in {"PROMISED", "CONTRADICTORY"}
            and verified == "NOT_OBSERVED"
        ):
            findings.append(
                {
                    "kind": "PROMISED_IMPLEMENTATION_NOT_RUNTIME_VERIFIED",
                    "severity": "REVIEW",
                    "capability": label,
                    "message": "Promised implementation evidence exists, but no matching bounded runtime verification was observed.",
                    "evidence": evidence,
                }
            )

    completed: list[dict[str, str]] = []
    for path, text in documents:
        for line in text.splitlines():
            if re.match(r"\s*[-*]\s*\[[xX]\]\s+", line):
                completed.append(
                    {
                        "path": str(path),
                        "claim": re.sub(r"^\s*[-*]\s*\[[xX]\]\s+", "", line).strip()[:240],
                    }
                )
                if len(completed) >= 80:
                    break
        if len(completed) >= 80:
            break

    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "documents": [str(path) for path, _ in documents],
        "capabilities": rows,
        "completed_roadmap_claims": completed,
        "findings": findings,
        "summary": {
            "documents": len(documents),
            "capabilities": len(rows),
            "promised": sum(1 for x in rows if x["contract_status"] == "PROMISED"),
            "excluded": sum(1 for x in rows if x["contract_status"] == "EXCLUDED"),
            "future": sum(1 for x in rows if x["contract_status"] == "FUTURE"),
            "contradictory": sum(1 for x in rows if x["contract_status"] == "CONTRADICTORY"),
            "code_confirmed": sum(1 for x in rows if x["implementation"] == "CODE_CONFIRMED"),
            "runtime_verified": sum(
                1 for x in rows if str(x["runtime_verified"]).startswith("OBSERVED")
            ),
            "review_signals": sum(
                1 for x in findings if x["severity"] in {"REVIEW", "HIGH_REVIEW"}
            ),
        },
        "guardrails": {
            "documentation_is_claim_evidence_not_truth": True,
            "negative_claims_are_not_promises": True,
            "future_claims_are_not_promises": True,
            "mention_only_is_not_promise": True,
            "not_observed_is_not_missing": True,
            "checked_roadmap_items_are_not_auto_passed": True,
            "no_certification_override": True,
        },
    }


def markdown(r: dict[str, Any]) -> str:
    lines = [
        "# AppLab Product Contract Audit",
        "",
        f"- Product documents: **{r['summary']['documents']}**",
        f"- Capabilities mapped: **{r['summary']['capabilities']}**",
        f"- Promised / excluded / future: **{r['summary']['promised']} / {r['summary']['excluded']} / {r['summary']['future']}**",
        f"- Contradictory: **{r['summary']['contradictory']}**",
        f"- Runtime verified: **{r['summary']['runtime_verified']}**",
        f"- Review signals: **{r['summary']['review_signals']}**",
        "",
    ]
    for row in r["capabilities"]:
        lines.append(
            f"- **{row['capability']}** · contract={row['contract_status']} · "
            f"implementation={row['implementation']} · reachable={row['runtime_reachable']} · "
            f"verified={row['runtime_verified']}"
        )
    return "\n".join(lines)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "README.md").write_text(
            "Authentication is implemented.\nAI is excluded from v1.0.\nCloud sync is planned for a future version.",
            encoding="utf-8",
        )
        app = {
            "feature_truth": {
                "capabilities": [
                    {"capability": "authentication", "truth": "CODE_CONFIRMED", "provenance": {"CODE": ["auth.dart"]}},
                    {"capability": "ai_or_ml", "truth": "NOT_DETECTED", "provenance": {}},
                    {"capability": "cloud_or_sync", "truth": "DOC_ONLY_SIGNAL", "provenance": {"DOCUMENTATION": ["README.md"]}},
                ]
            }
        }
        r = build_report(
            root,
            app,
            {"runtime_matched_surfaces": [], "runtime_evidence_state": "OBSERVED_PASS"},
            {"states": {"auth": {"status": "OBSERVED"}, "offline": {"status": "NOT_OBSERVED"}}},
        )
        by_cap = {row["capability"]: row["contract_status"] for row in r["capabilities"]}
        assert by_cap["authentication"] == "PROMISED"
        assert by_cap["ai_or_ml"] == "EXCLUDED"
        assert by_cap["cloud_or_sync"] == "FUTURE"
        assert not any(
            x["kind"] == "PROMISED_WITHOUT_IMPLEMENTATION_EVIDENCE"
            and x["capability"] == "ai_or_ml"
            for x in r["findings"]
        )
    print("AppLab Product Contract Audit self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root")
    p.add_argument("--app-intelligence")
    p.add_argument("--behavioral")
    p.add_argument("--state-edge")
    p.add_argument("--output-dir", default="applab-product-contract")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if not a.repo_root or not a.app_intelligence:
        raise SystemExit("--repo-root and --app-intelligence are required")
    app = load_json(Path(a.app_intelligence))
    if app is None:
        raise SystemExit("invalid app intelligence")
    r = build_report(
        Path(a.repo_root),
        app,
        load_json(Path(a.behavioral)) if a.behavioral else None,
        load_json(Path(a.state_edge)) if a.state_edge else None,
    )
    write_report(Path(a.output_dir), "product-contract-audit", r, markdown(r))
    print(json.dumps({"lab_version": LAB_VERSION, **r["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
