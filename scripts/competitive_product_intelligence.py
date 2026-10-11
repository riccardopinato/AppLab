#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import market_intelligence
import product_contract_audit

SCHEMA_VERSION = 1
LAB_VERSION = "5.2.0"
RECORD_TYPE = "COMPETITIVE_PRODUCT_INTELLIGENCE"
AUTHORITY = "APPLAB_COMPETITIVE_PRODUCT_INTELLIGENCE_ADVISORY"
CLASSIFICATION = "COMPETITIVE PRODUCT INTELLIGENCE"
ALLOWED_STATES = {"READY", "EVIDENCE_INCOMPLETE", "STALE_EVIDENCE"}
ALLOWED_ROUTES = {"REVIEW", "CONSIDER", "PROTECT_DIFFERENTIATOR", "NO_ACTION"}
EXTENDED_DIMENSIONS = ("workflows", "onboarding", "visual_patterns")
TARGET_USER_MARKERS = (
    "target user", "target users", "target audience", "audience", "persona",
    "utente target", "utenti target", "pubblico target", "destinatari",
)
DOC_NAMES = (
    "PRODUCT_BIBLE.md", "PRODUCT_BIBLE.txt", "README.md", "ROADMAP.md",
    "FEATURES.md", "FEATURES.txt", "PROJECT_STATE.md",
)

def clean(value: object) -> str:
    return str(value or "").strip()

def normalize_key(value: object) -> str:
    return market_intelligence.normalize_key(value)

def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def digest_payload(record: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(record))
    clone.pop("generated_at", None)
    clone["record_digest_sha256"] = ""
    return clone

def record_digest(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(digest_payload(record))).hexdigest()

def evidence_identity(graph: dict[str, Any]) -> dict[str, str]:
    if graph.get("schema_version") != 2 or clean(graph.get("graph_version")) != "2.0":
        raise ValueError("Evidence Graph schema/version is invalid")
    identity = graph.get("identity") if isinstance(graph.get("identity"), dict) else {}
    roots = graph.get("root_nodes") if isinstance(graph.get("root_nodes"), dict) else {}
    artifact_id = clean(roots.get("build_artifact"))
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    artifact = next(
        (
            row for row in nodes
            if isinstance(row, dict)
            and clean(row.get("id")) == artifact_id
            and clean(row.get("type")) == "BuildArtifact"
        ),
        None,
    )
    if not artifact:
        raise ValueError("Evidence Graph canonical build artifact is missing")
    attrs = artifact.get("attributes") if isinstance(artifact.get("attributes"), dict) else {}
    out = {
        "repository": clean(identity.get("repository")),
        "resolved_sha": clean(identity.get("resolved_sha")).lower(),
        "run_id": clean(identity.get("run_id")),
        "package_id": clean(identity.get("package_id")),
        "artifact_sha256": clean(attrs.get("apk_sha256")).lower(),
        "version_name": clean(attrs.get("version_name")),
        "version_code": clean(attrs.get("version_code")),
    }
    if not out["repository"] or "/" not in out["repository"]:
        raise ValueError("Evidence Graph repository identity is missing")
    if len(out["resolved_sha"]) != 40 or any(ch not in "0123456789abcdef" for ch in out["resolved_sha"]):
        raise ValueError("Evidence Graph resolved SHA is invalid")
    if not out["run_id"].isdigit():
        raise ValueError("Evidence Graph trusted workflow run identity is invalid")
    if not out["package_id"] or clean(attrs.get("package_id")) != out["package_id"]:
        raise ValueError("Evidence Graph package identity is inconsistent")
    if len(out["artifact_sha256"]) != 64 or any(ch not in "0123456789abcdef" for ch in out["artifact_sha256"]):
        raise ValueError("Evidence Graph artifact SHA-256 is invalid")
    if not out["version_name"] or not out["version_code"]:
        raise ValueError("Evidence Graph artifact version identity is incomplete")
    return out

def parse_date(value: object) -> date | None:
    text = clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None

def freshness(raw: dict[str, Any], normalized: dict[str, Any], as_of: date, max_age_days: int) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    root_date = parse_date(raw.get("observed_at"))
    if root_date:
        observations.append({"scope": "set", "observed_at": root_date.isoformat(), "age_days": max(0, (as_of - root_date).days)})
    for row in normalized.get("competitors", []):
        observed = parse_date(row.get("observed_at"))
        observations.append({
            "scope": f"competitor:{row.get('id')}",
            "observed_at": observed.isoformat() if observed else "",
            "age_days": max(0, (as_of - observed).days) if observed else None,
        })
    known = [int(row["age_days"]) for row in observations if isinstance(row.get("age_days"), int)]
    missing = sum(1 for row in observations if row.get("age_days") is None)
    if not known:
        state = "EVIDENCE_INCOMPLETE"
    elif min(known) > max_age_days:
        state = "STALE_EVIDENCE"
    elif max(known) > max_age_days or missing:
        state = "PARTIAL_STALE"
    else:
        state = "FRESH"
    return {
        "state": state,
        "as_of": as_of.isoformat(),
        "max_age_days": max_age_days,
        "oldest_age_days": max(known) if known else None,
        "newest_age_days": min(known) if known else None,
        "missing_observed_at": missing,
        "observations": observations,
    }

def normalize_extended(raw: dict[str, Any], normalized: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw_by_id = {
        normalize_key(row.get("id") or row.get("name")): row
        for row in raw.get("competitors", [])
        if isinstance(row, dict)
    }
    result: dict[str, list[dict[str, Any]]] = {key: [] for key in EXTENDED_DIMENSIONS}
    for competitor in normalized.get("competitors", []):
        competitor_id = clean(competitor.get("id"))
        source = raw_by_id.get(competitor_id, {})
        for dimension in EXTENDED_DIMENSIONS:
            rows = source.get(dimension, [])
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                raise ValueError(f"competitor {competitor_id} {dimension} must be a list")
            for index, item in enumerate(rows):
                if not isinstance(item, dict):
                    raise ValueError(f"competitor {competitor_id} {dimension}[{index}] must be an object")
                key = normalize_key(item.get("key") or item.get("label"))
                label = clean(item.get("label") or key.replace("_", " "))
                if not key:
                    raise ValueError(f"competitor {competitor_id} {dimension}[{index}] requires key")
                source_url = market_intelligence.require_source_url(
                    item.get("source_url"),
                    f"competitor {competitor_id} {dimension} {key}",
                )
                result[dimension].append({
                    "competitor": competitor_id,
                    "key": key,
                    "label": label,
                    "source_url": source_url,
                    "evidence": clean(item.get("evidence")),
                })
    return result

def dimension_matrix(rows: list[dict[str, Any]], competitor_total: int) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(row["key"], {"key": row["key"], "label": row["label"], "competitors": set(), "source_urls": set()})
        item["competitors"].add(row["competitor"])
        item["source_urls"].add(row["source_url"])
    output = []
    for key in sorted(grouped):
        item = grouped[key]
        count = len(item["competitors"])
        share = count / competitor_total if competitor_total else 0.0
        output.append({
            "key": key,
            "label": item["label"],
            "competitor_count": count,
            "competitor_total": competitor_total,
            "market_share_signal": round(share, 4),
            "classification": "COMMON_MARKET_EXPECTATION" if competitor_total >= 2 and share >= 0.5 else "NICHE_MARKET_PATTERN",
            "competitors": sorted(item["competitors"]),
            "source_urls": sorted(item["source_urls"]),
        })
    return sorted(output, key=lambda row: (-row["competitor_count"], row["key"]))

def read_product_docs(root: Path) -> list[tuple[Path, str]]:
    docs: list[tuple[Path, str]] = []
    for name in DOC_NAMES:
        path = root / name
        if path.is_file():
            try:
                docs.append((path, path.read_text(encoding="utf-8", errors="ignore")[:300000]))
            except OSError:
                pass
    return docs

def target_user_context(raw: dict[str, Any], docs: list[tuple[Path, str]]) -> dict[str, Any]:
    project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
    explicit = clean(project.get("target_user") or project.get("target_users") or project.get("audience"))
    evidence: list[str] = []
    if explicit:
        evidence.append("market-evidence.json:project.target_user")
    excerpts: list[str] = []
    for path, text in docs:
        for number, line in enumerate(text.splitlines(), 1):
            lower = line.casefold()
            if any(marker in lower for marker in TARGET_USER_MARKERS):
                excerpt = line.strip()[:280]
                if excerpt:
                    excerpts.append(f"{path.name}:{number}: {excerpt}")
            if len(excerpts) >= 8:
                break
        if len(excerpts) >= 8:
            break
    evidence.extend(excerpts)
    return {
        "state": "DECLARED" if evidence else "EVIDENCE_INCOMPLETE",
        "declared_value": explicit,
        "evidence": evidence,
    }

def contract_relevance(docs: list[tuple[Path, str]], key: str) -> dict[str, Any]:
    claims = product_contract_audit.collect_claims(docs, key)
    status = product_contract_audit.contract_status(claims)
    return {
        "status": status,
        "relevant": status in {"PROMISED", "FUTURE", "MENTION_ONLY", "CONTRADICTORY"},
        "evidence": [
            f"{Path(row['path']).name}:{row['line']} [{row['classification']}] {row['text']}"
            for row in claims[:8]
        ],
    }

def capability_expectations(
    market: dict[str, Any],
    docs: list[tuple[Path, str]],
    target_user: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    common: list[dict[str, Any]] = []
    parity: list[dict[str, Any]] = []
    differentiators: list[dict[str, Any]] = []
    for row in market.get("capabilities", []):
        if not isinstance(row, dict):
            continue
        classification = clean(row.get("classification"))
        share = float(row.get("market_share_signal", 0) or 0)
        relevance = contract_relevance(docs, clean(row.get("key")))
        if row.get("competitor_total", 0) >= 2 and share >= 0.5:
            common.append({
                "dimension": "capability",
                "key": row.get("key"),
                "label": row.get("label"),
                "competitor_count": row.get("competitor_count"),
                "competitor_total": row.get("competitor_total"),
                "source_urls": row.get("source_urls", []),
            })
        if classification == "COMMON_MARKET_GAP_REVIEW":
            if relevance["relevant"] and target_user["state"] == "DECLARED":
                state = "RELEVANT_PARITY_REVIEW"
                route = "REVIEW"
            elif not relevance["relevant"]:
                state = "NOT_PRODUCT_CONTRACT_RELEVANT"
                route = "NO_ACTION"
            else:
                state = "TARGET_USER_CONTEXT_INCOMPLETE"
                route = "CONSIDER"
            parity.append({
                "key": row.get("key"),
                "label": row.get("label"),
                "state": state,
                "route": route,
                "market_share_signal": share,
                "contract_status": relevance["status"],
                "contract_evidence": relevance["evidence"],
                "source_urls": row.get("source_urls", []),
            })
        if classification in {"PROJECT_DIFFERENTIATOR_SIGNAL", "PROJECT_ONLY_SIGNAL"}:
            differentiators.append({
                "key": row.get("key"),
                "label": row.get("label"),
                "classification": classification,
                "route": "PROTECT_DIFFERENTIATOR",
                "competitor_count": row.get("competitor_count"),
                "competitor_total": row.get("competitor_total"),
                "source_urls": row.get("source_urls", []),
            })
    return common, parity, differentiators

def market_weakness_opportunities(market: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = market.get("reviews") if isinstance(market.get("reviews"), dict) else {}
    pains = reviews.get("recurring_pain_signals") if isinstance(reviews.get("recurring_pain_signals"), list) else []
    result = []
    for row in pains:
        if not isinstance(row, dict):
            continue
        result.append({
            "key": row.get("key"),
            "theme": row.get("theme"),
            "classification": "MARKET_WEAKNESS_OPPORTUNITY",
            "route": "CONSIDER",
            "opportunity": "Avoid or simplify the recurring weakness; do not copy the competing implementation.",
            "competitor_count": int(row.get("competitor_count", 0) or 0),
            "mentions": int(row.get("mentions", 0) or 0),
            "source_urls": row.get("source_urls", []),
        })
    return result

def competitor_set(raw: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    project = raw.get("project") if isinstance(raw.get("project"), dict) else {}
    category = clean(project.get("category")) or "UNSPECIFIED"
    name = clean(project.get("name")) or "project"
    explicit_id = normalize_key(project.get("competitor_set_id") or raw.get("competitor_set_id"))
    set_id = explicit_id or normalize_key(f"{name}_{category}") or "default"
    source_urls = sorted({
        url
        for row in normalized.get("competitors", [])
        for url in row.get("source_urls", [])
        if clean(url)
    })
    return {
        "id": set_id,
        "category": category,
        "project_name": name,
        "competitor_count": len(normalized.get("competitors", [])),
        "competitors": [{"id": row.get("id"), "name": row.get("name")} for row in normalized.get("competitors", [])],
        "source_urls": source_urls,
    }

def build_report(
    repo_root: Path,
    evidence_dir: Path,
    market_evidence_path: Path | None,
    as_of: date,
    max_age_days: int,
) -> dict[str, Any]:
    graph = load_json(evidence_dir / "evidence-graph.json")
    if not graph:
        raise ValueError("evidence-graph.json is required for Competitive Product Intelligence")
    identity = evidence_identity(graph)
    docs = read_product_docs(repo_root)

    if market_evidence_path is None or not market_evidence_path.is_file():
        record = {
            "schema_version": SCHEMA_VERSION,
            "lab_version": LAB_VERSION,
            "record_type": RECORD_TYPE,
            "authority": AUTHORITY,
            "classification": CLASSIFICATION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "identity": identity,
            "state": "EVIDENCE_INCOMPLETE",
            "competitor_set": {"id": "NOT_PROVIDED", "category": "UNSPECIFIED", "competitor_count": 0, "competitors": [], "source_urls": []},
            "target_user_context": {"state": "EVIDENCE_INCOMPLETE", "declared_value": "", "evidence": []},
            "freshness": {"state": "EVIDENCE_INCOMPLETE", "as_of": as_of.isoformat(), "max_age_days": max_age_days, "missing_observed_at": 0, "observations": []},
            "comparison": {"capabilities": [], "workflows": [], "onboarding": [], "pricing": {}, "visual_patterns": [], "pain_points": []},
            "common_market_expectations": [],
            "relevant_parity_reviews": [],
            "differentiation_opportunities": [],
            "market_weakness_opportunities": [],
            "findings": [{"kind": "MARKET_EVIDENCE_NOT_PROVIDED", "route": "CONSIDER", "message": "No market-evidence.json was supplied for this target; competitive conclusions are withheld.", "evidence": []}],
            "summary": {"competitors": 0, "common_expectations": 0, "relevant_parity_reviews": 0, "differentiation_opportunities": 0, "market_weakness_opportunities": 0, "stale": False},
            "guardrails": {
                "advisory_only": True,
                "no_release_verdict": True,
                "no_auto_feature_addition": True,
                "no_competitor_feature_copying": True,
                "parity_requires_product_contract_and_target_user_context": True,
                "source_traceability_required": True,
                "freshness_required": True,
                "trusted_verifier_does_not_scrape_web": True,
            },
            "record_digest_sha256": "",
        }
        record["record_digest_sha256"] = record_digest(record)
        return record

    raw = load_json(market_evidence_path)
    if raw is None:
        raise ValueError("market evidence JSON is invalid")
    normalized = market_intelligence.validate_evidence(raw)
    app = load_json(evidence_dir / "app-intelligence.json") or {}
    market = market_intelligence.build_report(normalized, app)
    extended = normalize_extended(raw, normalized)
    target_user = target_user_context(raw, docs)
    fresh = freshness(raw, normalized, as_of, max_age_days)
    set_info = competitor_set(raw, normalized)

    workflows = dimension_matrix(extended["workflows"], set_info["competitor_count"])
    onboarding = dimension_matrix(extended["onboarding"], set_info["competitor_count"])
    visuals = dimension_matrix(extended["visual_patterns"], set_info["competitor_count"])
    common_caps, parity, differentiators = capability_expectations(market, docs, target_user)
    common_other = [
        {"dimension": dimension, **row}
        for dimension, rows in (("workflow", workflows), ("onboarding", onboarding), ("visual_pattern", visuals))
        for row in rows
        if row["classification"] == "COMMON_MARKET_EXPECTATION"
    ]
    weaknesses = market_weakness_opportunities(market)
    findings: list[dict[str, Any]] = []
    findings.extend({
        "kind": "RELEVANT_MARKET_PARITY_REVIEW",
        "route": row["route"],
        "subject": row["key"],
        "message": f"{row['label']} is a common competitor capability and is relevant to the product contract/target-user context.",
        "evidence": row["source_urls"] + row["contract_evidence"],
    } for row in parity if row["state"] == "RELEVANT_PARITY_REVIEW")
    findings.extend({
        "kind": "DIFFERENTIATION_OPPORTUNITY",
        "route": "PROTECT_DIFFERENTIATOR",
        "subject": row["key"],
        "message": "Current project evidence indicates a capability less common in the supplied competitor set.",
        "evidence": row["source_urls"],
    } for row in differentiators)
    findings.extend({
        "kind": "COMPETITOR_WEAKNESS_OPPORTUNITY",
        "route": "CONSIDER",
        "subject": row["key"],
        "message": row["opportunity"],
        "evidence": row["source_urls"],
    } for row in weaknesses)
    if fresh["state"] in {"STALE_EVIDENCE", "PARTIAL_STALE", "EVIDENCE_INCOMPLETE"}:
        findings.append({
            "kind": "MARKET_EVIDENCE_FRESHNESS_REVIEW",
            "route": "REVIEW",
            "subject": "market_evidence",
            "message": f"Market evidence freshness is {fresh['state']}; refresh stale/missing observations before acting on competitive conclusions.",
            "evidence": [f"as_of={fresh['as_of']}", f"max_age_days={fresh['max_age_days']}"],
        })

    state = "STALE_EVIDENCE" if fresh["state"] == "STALE_EVIDENCE" else "READY"
    record = {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "record_type": RECORD_TYPE,
        "authority": AUTHORITY,
        "classification": CLASSIFICATION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "state": state,
        "competitor_set": set_info,
        "target_user_context": target_user,
        "freshness": fresh,
        "comparison": {
            "capabilities": market.get("capabilities", []),
            "workflows": workflows,
            "onboarding": onboarding,
            "pricing": market.get("pricing", {}),
            "visual_patterns": visuals,
            "pain_points": (market.get("reviews") or {}).get("themes", []),
        },
        "common_market_expectations": common_caps + common_other,
        "relevant_parity_reviews": parity,
        "differentiation_opportunities": differentiators,
        "market_weakness_opportunities": weaknesses,
        "findings": findings[:60],
        "summary": {
            "competitors": set_info["competitor_count"],
            "common_expectations": len(common_caps) + len(common_other),
            "relevant_parity_reviews": sum(1 for row in parity if row["state"] == "RELEVANT_PARITY_REVIEW"),
            "parity_not_relevant": sum(1 for row in parity if row["state"] == "NOT_PRODUCT_CONTRACT_RELEVANT"),
            "parity_context_incomplete": sum(1 for row in parity if row["state"] == "TARGET_USER_CONTEXT_INCOMPLETE"),
            "differentiation_opportunities": len(differentiators),
            "market_weakness_opportunities": len(weaknesses),
            "stale": fresh["state"] in {"STALE_EVIDENCE", "PARTIAL_STALE"},
        },
        "guardrails": {
            "advisory_only": True,
            "no_release_verdict": True,
            "no_auto_feature_addition": True,
            "no_competitor_feature_copying": True,
            "parity_requires_product_contract_and_target_user_context": True,
            "source_traceability_required": True,
            "freshness_required": True,
            "trusted_verifier_does_not_scrape_web": True,
        },
        "record_digest_sha256": "",
    }
    record["record_digest_sha256"] = record_digest(record)
    return record

def markdown(record: dict[str, Any]) -> str:
    summary = record["summary"]
    lines = [
        "# AppLab v5.2 — Competitive Product Intelligence",
        "",
        f"- Classification: **{CLASSIFICATION}**",
        f"- State: **{record['state']}**",
        f"- Project: **{record['identity']['repository']}@{record['identity']['resolved_sha']}**",
        f"- Competitor set: **{record['competitor_set']['id']}** · category **{record['competitor_set']['category']}**",
        f"- Competitors: **{summary['competitors']}**",
        f"- Freshness: **{record['freshness']['state']}**",
        f"- Target-user context: **{record['target_user_context']['state']}**",
        "",
        "## Product signals",
        "",
        f"- Common market expectations: **{summary['common_expectations']}**",
        f"- Relevant parity reviews: **{summary['relevant_parity_reviews']}**",
        f"- Differentiation opportunities: **{summary['differentiation_opportunities']}**",
        f"- Competitor weakness opportunities: **{summary['market_weakness_opportunities']}**",
        "",
        "## Relevant parity reviews",
        "",
    ]
    relevant = [row for row in record["relevant_parity_reviews"] if row["state"] == "RELEVANT_PARITY_REVIEW"]
    lines.extend(
        f"- **{row['key']}** — {row['market_share_signal']:.0%} competitor share; contract {row['contract_status']}."
        for row in relevant
    )
    if not relevant:
        lines.append("- None established by current evidence.")
    lines.extend(["", "## Differentiation opportunities", ""])
    lines.extend(
        f"- **{row['key']}** — {row['classification']} · preserve/test before commoditizing."
        for row in record["differentiation_opportunities"]
    )
    if not record["differentiation_opportunities"]:
        lines.append("- None established by current evidence.")
    lines.extend(["", "## Competitor weakness opportunities", ""])
    lines.extend(
        f"- **{row['theme']}** — observed across {row['competitor_count']} competitors; {row['opportunity']}"
        for row in record["market_weakness_opportunities"]
    )
    if not record["market_weakness_opportunities"]:
        lines.append("- None established by current evidence.")
    lines.extend([
        "",
        "## Guardrails",
        "",
        "- Competitive evidence is advisory only and cannot change release/certification verdicts.",
        "- A competitor feature never becomes an automatic product requirement.",
        "- Missing parity is highlighted only when product-contract relevance and target-user context are both established.",
        "- Recurring competitor pain is an opportunity to simplify or improve, not a directive to copy implementation.",
        "- Trusted review consumes source-traceable evidence already present in the target repository; it does not scrape the web.",
        "",
    ])
    return "\n".join(lines)

def write_report(output_dir: Path, record: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "competitive-product-intelligence.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "competitive-product-intelligence.md").write_text(markdown(record), encoding="utf-8")

def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo = root / "repo"
        evidence = root / "evidence"
        repo.mkdir()
        evidence.mkdir()
        (repo / "PRODUCT_BIBLE.md").write_text(
            "# Demo\nTarget user: people who need reliable offline notes.\nFeatures: export or backup is planned.\n",
            encoding="utf-8",
        )
        graph = {
            "schema_version": 2,
            "graph_version": "2.0",
            "identity": {"repository": "owner/demo", "resolved_sha": "a"*40, "run_id": "123", "package_id": "com.example.demo"},
            "root_nodes": {"build_artifact": "artifact:demo"},
            "nodes": [{"id": "artifact:demo", "type": "BuildArtifact", "attributes": {"package_id": "com.example.demo", "apk_sha256": "b"*64, "version_name": "1.0.0", "version_code": "1"}}],
        }
        (evidence / "evidence-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (evidence / "app-intelligence.json").write_text(json.dumps({"product": {"feature_signals": [{"label": "local_persistence", "status": "PRESENT"}]}}), encoding="utf-8")
        market_path = repo / "market-evidence.json"
        market_path.write_text(json.dumps({
            "schema_version": 1,
            "project": {"name": "Demo", "category": "notes", "target_user": "people who need reliable offline notes", "competitor_set_id": "notes-core"},
            "observed_at": "2026-10-01",
            "competitors": [
                {
                    "id": "alpha", "name": "Alpha", "source_urls": ["https://example.com/alpha"], "observed_at": "2026-10-01",
                    "features": [{"key": "export_or_backup", "label": "Export / backup", "source_url": "https://example.com/alpha/export"}],
                    "workflows": [{"key": "quick_capture", "label": "Quick capture", "source_url": "https://example.com/alpha/workflow"}],
                    "onboarding": [{"key": "skip_account", "label": "Skip account", "source_url": "https://example.com/alpha/onboarding"}],
                    "visual_patterns": [{"key": "card_library", "label": "Card library", "source_url": "https://example.com/alpha/ui"}],
                    "pricing": {"model": "subscription", "currency": "EUR", "monthly": 4.99, "source_url": "https://example.com/alpha/pricing"},
                    "review_themes": [{"key": "sync_reliability", "theme": "Sync reliability", "sentiment": "negative", "count": 4, "source_url": "https://example.com/alpha/reviews"}],
                },
                {
                    "id": "beta", "name": "Beta", "source_urls": ["https://example.com/beta"], "observed_at": "2026-10-02",
                    "features": [{"key": "export_or_backup", "label": "Export / backup", "source_url": "https://example.com/beta/export"}],
                    "workflows": [{"key": "quick_capture", "label": "Quick capture", "source_url": "https://example.com/beta/workflow"}],
                    "onboarding": [{"key": "skip_account", "label": "Skip account", "source_url": "https://example.com/beta/onboarding"}],
                    "visual_patterns": [{"key": "card_library", "label": "Card library", "source_url": "https://example.com/beta/ui"}],
                    "pricing": {"model": "subscription", "currency": "EUR", "monthly": 6.99, "source_url": "https://example.com/beta/pricing"},
                    "review_themes": [{"key": "sync_reliability", "theme": "Sync reliability", "sentiment": "negative", "count": 2, "source_url": "https://example.com/beta/reviews"}],
                },
            ],
        }), encoding="utf-8")
        report = build_report(repo, evidence, market_path, date(2026, 10, 11), 120)
        assert report["state"] == "READY"
        assert report["competitor_set"]["id"] == "notes_core"
        assert report["summary"]["relevant_parity_reviews"] == 1
        assert report["summary"]["market_weakness_opportunities"] == 1
        assert any(row["dimension"] == "workflow" for row in report["common_market_expectations"])
        assert report["guardrails"]["no_auto_feature_addition"] is True
        assert report["record_digest_sha256"] == record_digest(report)

        missing = build_report(repo, evidence, None, date(2026, 10, 11), 120)
        assert missing["state"] == "EVIDENCE_INCOMPLETE"
        assert missing["summary"]["competitors"] == 0
    print("AppLab Competitive Product Intelligence v5.2 self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--evidence-dir")
    parser.add_argument("--market-evidence")
    parser.add_argument("--output-dir")
    parser.add_argument("--as-of")
    parser.add_argument("--max-age-days", type=int, default=120)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.evidence_dir:
        parser.error("--repo-root and --evidence-dir are required unless --self-test is used")
    as_of = parse_date(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    if not as_of:
        raise SystemExit("--as-of must be ISO-8601 compatible")
    market_path = Path(args.market_evidence) if args.market_evidence else None
    output = Path(args.output_dir) if args.output_dir else Path(args.evidence_dir)
    record = build_report(Path(args.repo_root), Path(args.evidence_dir), market_path, as_of, args.max_age_days)
    write_report(output, record)
    print(json.dumps({"lab_version": LAB_VERSION, "state": record["state"], **record["summary"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab Competitive Product Intelligence failed: {exc}") from exc
