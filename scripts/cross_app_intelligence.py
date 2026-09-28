#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LAB_VERSION = "1.5.0"


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def report_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_key(value: object) -> str:
    text = str(value or "").strip().lower()
    result: list[str] = []
    underscore = False
    for char in text:
        if char.isalnum():
            result.append(char)
            underscore = False
        elif result and not underscore:
            result.append("_")
            underscore = True
    return "".join(result).strip("_")


def project_record(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise ValueError(f"{path} is not a supported App Intelligence report")

    project_id = normalize_key(
        payload.get("project_id")
        or payload.get("root_name")
        or path.parent.name
        or path.stem
    )
    if not project_id:
        raise ValueError(f"Cannot derive project id from {path}")

    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    ux = payload.get("ux_product") if isinstance(payload.get("ux_product"), dict) else {}
    architecture = (
        payload.get("architecture_data")
        if isinstance(payload.get("architecture_data"), dict)
        else {}
    )

    capabilities: set[str] = set()
    for item in product.get("feature_signals", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).upper() != "PRESENT":
            continue
        key = normalize_key(item.get("label"))
        if key:
            capabilities.add(key)

    ux_findings: set[str] = set()
    for item in ux.get("findings", []):
        if isinstance(item, dict):
            key = normalize_key(item.get("kind"))
            if key:
                ux_findings.add(key)

    architecture_findings: set[str] = set()
    for item in architecture.get("findings", []):
        if isinstance(item, dict):
            key = normalize_key(item.get("kind"))
            if key:
                architecture_findings.add(key)

    stack = product.get("stack") if isinstance(product.get("stack"), dict) else {}
    data = architecture.get("data") if isinstance(architecture.get("data"), dict) else {}

    return {
        "project_id": project_id,
        "report_path": path.as_posix(),
        "report_sha256": report_hash(path),
        "scan_confidence": str(
            (payload.get("scan") or {}).get("confidence", "UNKNOWN")
            if isinstance(payload.get("scan"), dict)
            else "UNKNOWN"
        ),
        "engine": str(stack.get("engine", "unknown")),
        "capabilities": sorted(capabilities),
        "ux_findings": sorted(ux_findings),
        "architecture_findings": sorted(architecture_findings),
        "local_first_assessment": str(data.get("local_first_assessment", "UNKNOWN")),
    }


def discover_reports(corpus_dir: Path) -> list[Path]:
    if not corpus_dir.is_dir():
        raise ValueError(f"Corpus directory does not exist: {corpus_dir}")
    return sorted(corpus_dir.rglob("app-intelligence.json"))


def build_report(
    projects: list[dict[str, Any]],
    *,
    min_projects: int = 2,
) -> dict[str, Any]:
    if len(projects) < 2:
        raise ValueError("Cross-App Intelligence requires at least two project reports")
    if min_projects < 2:
        raise ValueError("min_projects must be >= 2")
    if min_projects > len(projects):
        min_projects = len(projects)

    ids = [project["project_id"] for project in projects]
    duplicates = [item for item, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate project ids in corpus: {', '.join(sorted(duplicates))}")

    capability_projects: dict[str, set[str]] = defaultdict(set)
    ux_finding_projects: dict[str, set[str]] = defaultdict(set)
    architecture_finding_projects: dict[str, set[str]] = defaultdict(set)

    for project in projects:
        project_id = project["project_id"]
        for capability in project["capabilities"]:
            capability_projects[capability].add(project_id)
        for finding in project["ux_findings"]:
            ux_finding_projects[finding].add(project_id)
        for finding in project["architecture_findings"]:
            architecture_finding_projects[finding].add(project_id)

    reusable_patterns: list[dict[str, Any]] = []
    project_specific: list[dict[str, Any]] = []
    for key, owners in sorted(capability_projects.items()):
        row = {
            "key": key,
            "project_count": len(owners),
            "project_total": len(projects),
            "projects": sorted(owners),
        }
        if len(owners) >= min_projects:
            reusable_patterns.append(
                {
                    **row,
                    "classification": "REPEATED_CAPABILITY_PATTERN",
                    "interpretation": (
                        "Observed across multiple projects; candidate for reusable design/"
                        "engineering review, not automatic extraction."
                    ),
                }
            )
        elif len(owners) == 1:
            project_specific.append(
                {
                    **row,
                    "classification": "PROJECT_SPECIFIC_SIGNAL",
                    "interpretation": (
                        "Observed in one project only; keep project-scoped unless further "
                        "evidence supports reuse."
                    ),
                }
            )

    recurrent_risks: list[dict[str, Any]] = []
    for domain, mapping in (
        ("ux_product", ux_finding_projects),
        ("architecture_data", architecture_finding_projects),
    ):
        for key, owners in sorted(mapping.items()):
            if len(owners) >= min_projects:
                recurrent_risks.append(
                    {
                        "domain": domain,
                        "key": key,
                        "project_count": len(owners),
                        "project_total": len(projects),
                        "projects": sorted(owners),
                        "classification": "RECURRENT_REVIEW_SIGNAL",
                    }
                )

    engine_distribution = Counter(project["engine"] for project in projects)
    local_first_distribution = Counter(
        project["local_first_assessment"] for project in projects
    )
    confidence_distribution = Counter(project["scan_confidence"] for project in projects)

    reusable_patterns.sort(key=lambda x: (-x["project_count"], x["key"]))
    project_specific.sort(key=lambda x: x["key"])
    recurrent_risks.sort(key=lambda x: (-x["project_count"], x["domain"], x["key"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "project_count": len(projects),
        "minimum_recurrence": min_projects,
        "projects": sorted(projects, key=lambda x: x["project_id"]),
        "portfolio_profile": {
            "engine_distribution": dict(sorted(engine_distribution.items())),
            "local_first_distribution": dict(sorted(local_first_distribution.items())),
            "scan_confidence_distribution": dict(sorted(confidence_distribution.items())),
        },
        "reusable_pattern_candidates": reusable_patterns,
        "project_specific_signals": project_specific,
        "recurrent_review_signals": recurrent_risks,
        "guardrails": {
            "advisory_only": True,
            "project_evidence_remains_authoritative": True,
            "no_automatic_code_reuse": True,
            "no_automatic_feature_transfer": True,
            "no_opaque_score": True,
            "principle": (
                "Cross-project recurrence may propose a pattern for review, but cannot "
                "override project-specific evidence or scope."
            ),
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AppLab Cross-App Intelligence",
        "",
        f"- Lab version: **{report['lab_version']}**",
        f"- Projects: **{report['project_count']}**",
        f"- Recurrence threshold: **{report['minimum_recurrence']} projects**",
        "",
        "## Reusable pattern candidates",
        "",
    ]

    patterns = report["reusable_pattern_candidates"]
    if patterns:
        for item in patterns:
            lines.append(
                f"- **{item['key']}** — {item['project_count']}/{item['project_total']} "
                f"projects: {', '.join(item['projects'])}"
            )
    else:
        lines.append("No repeated capability pattern meets the recurrence threshold.")

    lines.extend(["", "## Recurrent review signals", ""])
    risks = report["recurrent_review_signals"]
    if risks:
        for item in risks:
            lines.append(
                f"- **{item['domain']} · {item['key']}** — "
                f"{item['project_count']}/{item['project_total']} projects"
            )
    else:
        lines.append("No review signal recurs across enough projects.")

    lines.extend(["", "## Project-specific signals", ""])
    specific = report["project_specific_signals"]
    if specific:
        for item in specific:
            lines.append(
                f"- **{item['key']}** — keep scoped to {item['projects'][0]} pending further evidence."
            )
    else:
        lines.append("No capability appears exclusively in one project.")

    lines.extend(
        [
            "",
            "## Portfolio profile",
            "",
            f"- Engines: `{json.dumps(report['portfolio_profile']['engine_distribution'], sort_keys=True)}`",
            f"- Local-first assessments: `{json.dumps(report['portfolio_profile']['local_first_distribution'], sort_keys=True)}`",
            "",
            "## Guardrails",
            "",
            "- Recurrence is evidence for review, not permission to copy code or features.",
            "- Project-specific evidence remains authoritative.",
            "- Cross-App Intelligence does not alter runtime PASS/FAIL or CERTIFICATION.",
            "- No portfolio score or winner ranking is generated.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cross-app-intelligence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "cross-app-intelligence.md").write_text(
        markdown(report),
        encoding="utf-8",
    )


def self_test() -> None:
    def app_report(name: str, caps: list[str], ux: list[str], arch: list[str]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "root_name": name,
            "scan": {"confidence": "HIGH"},
            "product": {
                "stack": {"engine": "flutter"},
                "feature_signals": [
                    {"label": cap, "status": "PRESENT"} for cap in caps
                ],
            },
            "ux_product": {
                "findings": [{"kind": item} for item in ux],
            },
            "architecture_data": {
                "data": {"local_first_assessment": "SUPPORTED_BY_SIGNALS"},
                "findings": [{"kind": item} for item in arch],
            },
        }

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        data = [
            app_report(
                "alpha",
                ["local_persistence", "notifications"],
                ["ACCESSIBILITY_EVIDENCE_GAP"],
                ["UI_DIRECT_REMOTE_DEPENDENCY"],
            ),
            app_report(
                "beta",
                ["local_persistence", "export_or_backup"],
                ["ACCESSIBILITY_EVIDENCE_GAP"],
                [],
            ),
            app_report(
                "gamma",
                ["local_persistence"],
                [],
                ["UI_DIRECT_REMOTE_DEPENDENCY"],
            ),
        ]
        projects: list[dict[str, Any]] = []
        for index, payload in enumerate(data):
            folder = root / f"p{index}"
            folder.mkdir()
            path = folder / "app-intelligence.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            projects.append(project_record(path, payload))

        report = build_report(projects, min_projects=2)
        patterns = {item["key"]: item for item in report["reusable_pattern_candidates"]}
        assert patterns["local_persistence"]["project_count"] == 3
        risks = {(item["domain"], item["key"]) for item in report["recurrent_review_signals"]}
        assert ("ux_product", "accessibility_evidence_gap") in risks
        assert ("architecture_data", "ui_direct_remote_dependency") in risks

        out = root / "out"
        write_outputs(report, out)
        assert (out / "cross-app-intelligence.json").is_file()
        assert (out / "cross-app-intelligence.md").is_file()

    print("AppLab Cross-App Intelligence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-dir")
    parser.add_argument("--output-dir", default="applab-cross-app")
    parser.add_argument("--min-projects", type=int, default=2)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.corpus_dir:
        raise SystemExit("--corpus-dir is required unless --self-test is used")

    paths = discover_reports(Path(args.corpus_dir))
    if len(paths) < 2:
        raise SystemExit("At least two app-intelligence.json reports are required")

    projects = [project_record(path, load_json(path)) for path in paths]
    report = build_report(projects, min_projects=args.min_projects)
    write_outputs(report, Path(args.output_dir))
    print(
        json.dumps(
            {
                "lab_version": report["lab_version"],
                "projects": report["project_count"],
                "patterns": len(report["reusable_pattern_candidates"]),
                "recurrent_signals": len(report["recurrent_review_signals"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
