#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LAB_VERSION = "1.4.0"
ALLOWED_SENTIMENTS = {"positive", "negative", "mixed", "neutral", "unknown"}


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def clean_text(value: object) -> str:
    return str(value or "").strip()


def normalize_key(value: object) -> str:
    text = clean_text(value).lower()
    result: list[str] = []
    underscore = False
    for char in text:
        if char.isalnum():
            result.append(char)
            underscore = False
        elif not underscore and result:
            result.append("_")
            underscore = True
    return "".join(result).strip("_")


def require_source_url(value: object, context: str) -> str:
    url = clean_text(value)
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"{context} requires an http(s) source_url")
    return url


def validate_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"market evidence schema_version must be {SCHEMA_VERSION}")

    competitors = payload.get("competitors")
    if not isinstance(competitors, list) or not competitors:
        raise ValueError("market evidence requires at least one competitor")

    normalized_competitors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(competitors):
        if not isinstance(raw, dict):
            raise ValueError(f"competitors[{index}] must be an object")

        name = clean_text(raw.get("name"))
        competitor_id = normalize_key(raw.get("id") or name)
        if not name or not competitor_id:
            raise ValueError(f"competitors[{index}] requires name/id")
        if competitor_id in seen_ids:
            raise ValueError(f"duplicate competitor id: {competitor_id}")
        seen_ids.add(competitor_id)

        source_urls_raw = raw.get("source_urls", [])
        if not isinstance(source_urls_raw, list) or not source_urls_raw:
            raise ValueError(f"competitor {competitor_id} requires source_urls")
        source_urls = [
            require_source_url(url, f"competitor {competitor_id}")
            for url in source_urls_raw
        ]

        features_raw = raw.get("features", [])
        if not isinstance(features_raw, list):
            raise ValueError(f"competitor {competitor_id} features must be a list")
        features: list[dict[str, str]] = []
        feature_keys: set[str] = set()
        for feature_index, feature in enumerate(features_raw):
            if not isinstance(feature, dict):
                raise ValueError(
                    f"competitor {competitor_id} feature[{feature_index}] must be an object"
                )
            key = normalize_key(feature.get("key") or feature.get("label"))
            label = clean_text(feature.get("label") or key.replace("_", " "))
            source_url = require_source_url(
                feature.get("source_url"),
                f"competitor {competitor_id} feature {key or feature_index}",
            )
            if not key:
                raise ValueError(f"competitor {competitor_id} feature requires key")
            if key in feature_keys:
                continue
            feature_keys.add(key)
            features.append(
                {
                    "key": key,
                    "label": label,
                    "source_url": source_url,
                    "evidence": clean_text(feature.get("evidence")),
                }
            )

        pricing = raw.get("pricing") or {}
        if not isinstance(pricing, dict):
            raise ValueError(f"competitor {competitor_id} pricing must be an object")
        normalized_pricing: dict[str, Any] = {
            "model": normalize_key(pricing.get("model") or "unknown") or "unknown",
            "currency": clean_text(pricing.get("currency")).upper(),
            "monthly": pricing.get("monthly"),
            "yearly": pricing.get("yearly"),
            "lifetime": pricing.get("lifetime"),
            "source_url": "",
        }
        if any(
            normalized_pricing.get(field) not in (None, "")
            for field in ("monthly", "yearly", "lifetime")
        ) or normalized_pricing["model"] != "unknown":
            normalized_pricing["source_url"] = require_source_url(
                pricing.get("source_url"),
                f"competitor {competitor_id} pricing",
            )

        themes_raw = raw.get("review_themes", [])
        if not isinstance(themes_raw, list):
            raise ValueError(f"competitor {competitor_id} review_themes must be a list")
        themes: list[dict[str, Any]] = []
        for theme_index, theme in enumerate(themes_raw):
            if not isinstance(theme, dict):
                raise ValueError(
                    f"competitor {competitor_id} review_theme[{theme_index}] must be an object"
                )
            key = normalize_key(theme.get("key") or theme.get("theme"))
            label = clean_text(theme.get("theme") or key.replace("_", " "))
            sentiment = normalize_key(theme.get("sentiment") or "unknown")
            if sentiment not in ALLOWED_SENTIMENTS:
                raise ValueError(
                    f"competitor {competitor_id} theme {key} has invalid sentiment"
                )
            count_raw = theme.get("count", 1)
            try:
                count = max(1, int(count_raw))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"competitor {competitor_id} theme {key} count must be an integer"
                ) from exc
            source_url = require_source_url(
                theme.get("source_url"),
                f"competitor {competitor_id} review theme {key or theme_index}",
            )
            if not key:
                raise ValueError(
                    f"competitor {competitor_id} review theme requires key"
                )
            themes.append(
                {
                    "key": key,
                    "theme": label,
                    "sentiment": sentiment,
                    "count": count,
                    "source_url": source_url,
                    "evidence": clean_text(theme.get("evidence")),
                }
            )

        rating = raw.get("rating") or {}
        if not isinstance(rating, dict):
            raise ValueError(f"competitor {competitor_id} rating must be an object")
        normalized_rating: dict[str, Any] = {}
        if rating:
            normalized_rating = {
                "value": rating.get("value"),
                "count": rating.get("count"),
                "source_url": require_source_url(
                    rating.get("source_url"),
                    f"competitor {competitor_id} rating",
                ),
            }

        normalized_competitors.append(
            {
                "id": competitor_id,
                "name": name,
                "source_urls": source_urls,
                "observed_at": clean_text(raw.get("observed_at")),
                "features": features,
                "pricing": normalized_pricing,
                "rating": normalized_rating,
                "review_themes": themes,
                "notes": clean_text(raw.get("notes")),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "project": payload.get("project") if isinstance(payload.get("project"), dict) else {},
        "observed_at": clean_text(payload.get("observed_at")),
        "competitors": normalized_competitors,
    }


def project_signals(app_intelligence: dict[str, Any] | None) -> set[str]:
    if not app_intelligence:
        return set()
    product = app_intelligence.get("product")
    if not isinstance(product, dict):
        return set()
    signals = product.get("feature_signals")
    if not isinstance(signals, list):
        return set()
    result: set[str] = set()
    for item in signals:
        if not isinstance(item, dict):
            continue
        if clean_text(item.get("status")).upper() != "PRESENT":
            continue
        key = normalize_key(item.get("label"))
        if key:
            result.add(key)
    return result


def capability_matrix(
    competitors: list[dict[str, Any]],
    present_project_signals: set[str],
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for competitor in competitors:
        for feature in competitor["features"]:
            item = by_key.setdefault(
                feature["key"],
                {
                    "key": feature["key"],
                    "label": feature["label"],
                    "competitors": [],
                    "sources": [],
                },
            )
            item["competitors"].append(competitor["id"])
            item["sources"].append(feature["source_url"])

    total = len(competitors)
    result: list[dict[str, Any]] = []
    all_keys = set(by_key) | present_project_signals
    for key in sorted(all_keys):
        market = by_key.get(
            key,
            {"key": key, "label": key.replace("_", " "), "competitors": [], "sources": []},
        )
        count = len(set(market["competitors"]))
        share = count / total if total else 0.0
        project_signal = key in present_project_signals

        if project_signal and count == 0:
            classification = "PROJECT_ONLY_SIGNAL"
        elif project_signal and share < 0.5:
            classification = "PROJECT_DIFFERENTIATOR_SIGNAL"
        elif project_signal:
            classification = "MARKET_PARITY_SIGNAL"
        elif share >= 0.5:
            classification = "COMMON_MARKET_GAP_REVIEW"
        else:
            classification = "NICHE_MARKET_GAP_REVIEW"

        result.append(
            {
                "key": key,
                "label": market["label"],
                "project_source_signal": project_signal,
                "competitor_count": count,
                "competitor_total": total,
                "market_share_signal": round(share, 4),
                "classification": classification,
                "competitors": sorted(set(market["competitors"])),
                "source_urls": sorted(set(market["sources"])),
            }
        )

    order = {
        "COMMON_MARKET_GAP_REVIEW": 0,
        "PROJECT_DIFFERENTIATOR_SIGNAL": 1,
        "MARKET_PARITY_SIGNAL": 2,
        "NICHE_MARKET_GAP_REVIEW": 3,
        "PROJECT_ONLY_SIGNAL": 4,
    }
    return sorted(result, key=lambda item: (order[item["classification"]], item["key"]))


def pricing_landscape(competitors: list[dict[str, Any]]) -> dict[str, Any]:
    models = Counter()
    numeric: dict[tuple[str, str], list[float]] = defaultdict(list)
    evidence: list[dict[str, Any]] = []

    for competitor in competitors:
        pricing = competitor["pricing"]
        model = pricing.get("model", "unknown")
        models[model] += 1
        currency = clean_text(pricing.get("currency"))
        evidence.append(
            {
                "competitor": competitor["id"],
                "model": model,
                "currency": currency,
                "monthly": pricing.get("monthly"),
                "yearly": pricing.get("yearly"),
                "lifetime": pricing.get("lifetime"),
                "source_url": pricing.get("source_url", ""),
            }
        )
        for period in ("monthly", "yearly", "lifetime"):
            value = pricing.get(period)
            if value in (None, "") or not currency:
                continue
            try:
                numeric[(currency, period)].append(float(value))
            except (TypeError, ValueError):
                continue

    ranges: list[dict[str, Any]] = []
    for (currency, period), values in sorted(numeric.items()):
        ranges.append(
            {
                "currency": currency,
                "period": period,
                "samples": len(values),
                "min": min(values),
                "max": max(values),
            }
        )

    return {
        "models": dict(sorted(models.items())),
        "ranges": ranges,
        "evidence": evidence,
        "note": "Ranges are descriptive only. AppLab does not convert currencies or recommend a price.",
    }


def review_landscape(competitors: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate: dict[str, dict[str, Any]] = {}
    for competitor in competitors:
        for theme in competitor["review_themes"]:
            item = aggregate.setdefault(
                theme["key"],
                {
                    "key": theme["key"],
                    "theme": theme["theme"],
                    "mentions": 0,
                    "competitors": set(),
                    "sentiment": Counter(),
                    "sources": set(),
                },
            )
            item["mentions"] += int(theme["count"])
            item["competitors"].add(competitor["id"])
            item["sentiment"][theme["sentiment"]] += int(theme["count"])
            item["sources"].add(theme["source_url"])

    rows: list[dict[str, Any]] = []
    pain_signals: list[dict[str, Any]] = []
    for key in sorted(aggregate):
        item = aggregate[key]
        sentiments = dict(sorted(item["sentiment"].items()))
        row = {
            "key": key,
            "theme": item["theme"],
            "mentions": item["mentions"],
            "competitor_count": len(item["competitors"]),
            "competitors": sorted(item["competitors"]),
            "sentiment_counts": sentiments,
            "source_urls": sorted(item["sources"]),
        }
        rows.append(row)
        negative = sentiments.get("negative", 0)
        if negative > 0 and len(item["competitors"]) >= 2:
            pain_signals.append(
                {
                    **row,
                    "classification": "RECURRING_MARKET_PAIN_SIGNAL",
                }
            )

    pain_signals.sort(key=lambda item: (-item["competitor_count"], -item["mentions"], item["key"]))
    rows.sort(key=lambda item: (-item["mentions"], item["key"]))
    return {
        "themes": rows,
        "recurring_pain_signals": pain_signals,
        "note": "Review themes must be supplied with source evidence; AppLab does not infer sentiment from raw reviews in v1.4.",
    }


def source_audit(competitors: list[dict[str, Any]]) -> dict[str, Any]:
    urls: set[str] = set()
    missing_observed_at: list[str] = []
    for competitor in competitors:
        urls.update(competitor["source_urls"])
        if not competitor.get("observed_at"):
            missing_observed_at.append(competitor["id"])
        for feature in competitor["features"]:
            urls.add(feature["source_url"])
        pricing_url = competitor["pricing"].get("source_url")
        if pricing_url:
            urls.add(pricing_url)
        rating_url = competitor["rating"].get("source_url") if competitor["rating"] else ""
        if rating_url:
            urls.add(rating_url)
        for theme in competitor["review_themes"]:
            urls.add(theme["source_url"])
    return {
        "unique_source_urls": len(urls),
        "competitors_without_observed_at": missing_observed_at,
        "traceable": bool(urls),
    }


def build_report(
    evidence: dict[str, Any],
    app_intelligence: dict[str, Any] | None,
) -> dict[str, Any]:
    competitors = evidence["competitors"]
    signals = project_signals(app_intelligence)
    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "project": evidence.get("project", {}),
        "observed_at": evidence.get("observed_at", ""),
        "competitor_count": len(competitors),
        "project_source_signals": sorted(signals),
        "capabilities": capability_matrix(competitors, signals),
        "pricing": pricing_landscape(competitors),
        "reviews": review_landscape(competitors),
        "sources": source_audit(competitors),
        "competitors": competitors,
        "guardrails": {
            "external_evidence_layer": True,
            "non_blocking": True,
            "no_ranked_winner": True,
            "no_opaque_score": True,
            "no_web_scraping_in_trusted_verifier": True,
            "no_runtime_certification_effect": True,
            "principle": "External market evidence informs product review only; it never changes trusted verification.",
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AppLab Competitor & Market Lab",
        "",
        f"- Lab version: **{report['lab_version']}**",
        f"- Competitors with evidence: **{report['competitor_count']}**",
        f"- Unique source URLs: **{report['sources']['unique_source_urls']}**",
        "",
        "## Capability landscape",
        "",
        "| Capability | Project source signal | Competitors | Classification |",
        "|---|---:|---:|---|",
    ]
    for item in report["capabilities"]:
        lines.append(
            f"| {item['label']} | "
            f"{'yes' if item['project_source_signal'] else 'not detected'} | "
            f"{item['competitor_count']}/{item['competitor_total']} | "
            f"{item['classification']} |"
        )

    lines.extend(["", "## Pricing evidence", ""])
    if report["pricing"]["ranges"]:
        lines.extend(
            [
                "| Currency | Period | Samples | Min | Max |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for item in report["pricing"]["ranges"]:
            lines.append(
                f"| {item['currency']} | {item['period']} | {item['samples']} | "
                f"{item['min']} | {item['max']} |"
            )
    else:
        lines.append("No comparable numeric pricing range was supplied.")

    lines.extend(["", "## Recurring review pain signals", ""])
    pains = report["reviews"]["recurring_pain_signals"]
    if pains:
        for item in pains:
            lines.append(
                f"- **{item['theme']}** — negative evidence across "
                f"{item['competitor_count']} competitors; {item['mentions']} supplied mentions."
            )
    else:
        lines.append("No recurring cross-competitor negative theme was established by the supplied evidence.")

    lines.extend(
        [
            "",
            "## Interpretation rules",
            "",
            "- COMMON_MARKET_GAP_REVIEW means competitors commonly expose a capability for which the bounded project scan found no source signal; it is not proof the project lacks it.",
            "- PROJECT_DIFFERENTIATOR_SIGNAL means the project scan found a capability that appears in fewer than half of the supplied competitors.",
            "- MARKET_PARITY_SIGNAL is descriptive, not an endorsement.",
            "- Market evidence is advisory and cannot affect PASS/FAIL or CERTIFICATION.",
            "- Every competitor fact in the input must carry traceable source evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "market-intelligence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "market-intelligence.md").write_text(
        markdown(report),
        encoding="utf-8",
    )


def self_test() -> None:
    evidence = validate_evidence(
        {
            "schema_version": 1,
            "project": {"name": "Demo"},
            "observed_at": "2026-09-27",
            "competitors": [
                {
                    "id": "alpha",
                    "name": "Alpha",
                    "source_urls": ["https://example.com/alpha"],
                    "observed_at": "2026-09-27",
                    "features": [
                        {
                            "key": "authentication",
                            "label": "Authentication",
                            "source_url": "https://example.com/alpha/auth",
                        },
                        {
                            "key": "export_or_backup",
                            "label": "Export",
                            "source_url": "https://example.com/alpha/export",
                        },
                    ],
                    "pricing": {
                        "model": "subscription",
                        "currency": "EUR",
                        "monthly": 4.99,
                        "source_url": "https://example.com/alpha/pricing",
                    },
                    "review_themes": [
                        {
                            "key": "sync_reliability",
                            "theme": "Sync reliability",
                            "sentiment": "negative",
                            "count": 4,
                            "source_url": "https://example.com/alpha/reviews",
                        }
                    ],
                },
                {
                    "id": "beta",
                    "name": "Beta",
                    "source_urls": ["https://example.com/beta"],
                    "observed_at": "2026-09-27",
                    "features": [
                        {
                            "key": "export_or_backup",
                            "label": "Export",
                            "source_url": "https://example.com/beta/export",
                        }
                    ],
                    "pricing": {
                        "model": "subscription",
                        "currency": "EUR",
                        "monthly": 6.99,
                        "source_url": "https://example.com/beta/pricing",
                    },
                    "review_themes": [
                        {
                            "key": "sync_reliability",
                            "theme": "Sync reliability",
                            "sentiment": "negative",
                            "count": 2,
                            "source_url": "https://example.com/beta/reviews",
                        }
                    ],
                },
            ],
        }
    )
    app = {
        "product": {
            "feature_signals": [
                {"label": "authentication", "status": "PRESENT"},
                {"label": "local_persistence", "status": "PRESENT"},
            ]
        }
    }
    report = build_report(evidence, app)
    by_key = {item["key"]: item for item in report["capabilities"]}
    assert by_key["authentication"]["classification"] == "MARKET_PARITY_SIGNAL"
    assert by_key["export_or_backup"]["classification"] == "COMMON_MARKET_GAP_REVIEW"
    assert by_key["local_persistence"]["classification"] == "PROJECT_ONLY_SIGNAL"
    assert report["pricing"]["ranges"][0]["min"] == 4.99
    assert report["pricing"]["ranges"][0]["max"] == 6.99
    assert report["reviews"]["recurring_pain_signals"][0]["key"] == "sync_reliability"

    with tempfile.TemporaryDirectory() as raw:
        out = Path(raw)
        write_outputs(report, out)
        assert (out / "market-intelligence.json").is_file()
        assert (out / "market-intelligence.md").is_file()

    print("AppLab Competitor & Market Lab self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence")
    parser.add_argument("--app-intelligence")
    parser.add_argument("--output-dir", default="applab-market")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.evidence:
        raise SystemExit("--evidence is required unless --self-test is used")

    evidence = validate_evidence(load_json(Path(args.evidence)))
    app_intelligence = (
        load_json(Path(args.app_intelligence))
        if args.app_intelligence
        else None
    )
    report = build_report(evidence, app_intelligence)
    write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "lab_version": report["lab_version"],
                "competitors": report["competitor_count"],
                "sources": report["sources"]["unique_source_urls"],
                "output_dir": str(Path(args.output_dir)),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
