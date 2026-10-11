#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
LAB_VERSION = "5.1.0"
RECORD_TYPE = "DESIGN_SYSTEM_UI_LIBRARY_ADVISOR"
AUTHORITY = "APPLAB_DESIGN_SYSTEM_ADVISOR_ADVISORY"
CLASSIFICATION = "DESIGN SYSTEM ADVISORY"
ALLOWED_RECOMMENDATIONS = {"KEEP", "ADAPT", "REPLACE_CANDIDATE", "EVIDENCE_INCOMPLETE"}
ALLOWED_DIMENSION_STATES = {"FIT", "REVIEW", "EVIDENCE_INCOMPLETE", "NOT_APPLICABLE"}
IGNORED_DIRS = {".git", ".dart_tool", ".gradle", ".idea", ".vscode", "build", "dist", "node_modules", "Pods", ".next", "coverage", "vendor"}
TEXT_SUFFIXES = {".dart", ".kt", ".kts", ".java", ".swift", ".ts", ".tsx", ".js", ".jsx", ".css", ".scss", ".html", ".yaml", ".yml", ".json", ".toml", ".md", ".txt", ".xml", ".gradle"}

@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    size: int

def clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def digest_payload(report: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(report))
    clone.pop("generated_at", None)
    clone["record_digest_sha256"] = ""
    return clone

def report_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(digest_payload(report))).hexdigest()

def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None

def evidence_identity(graph: dict[str, Any]) -> dict[str, str]:
    if graph.get("schema_version") != 2 or clean(graph.get("graph_version")) != "2.0":
        raise ValueError("Evidence Graph schema/version is invalid")
    identity = graph.get("identity") if isinstance(graph.get("identity"), dict) else {}
    roots = graph.get("root_nodes") if isinstance(graph.get("root_nodes"), dict) else {}
    artifact_id = clean(roots.get("build_artifact"))
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    artifact = next((row for row in nodes if isinstance(row, dict) and clean(row.get("id")) == artifact_id and clean(row.get("type")) == "BuildArtifact"), None)
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

def tracked_paths(root: Path) -> list[Path]:
    try:
        run = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=20)
    except (OSError, subprocess.SubprocessError):
        run = None
    if run is not None and run.returncode == 0 and run.stdout:
        result = []
        for raw in run.stdout.split(b"\0"):
            if not raw:
                continue
            rel = raw.decode("utf-8", errors="ignore")
            if any(part in IGNORED_DIRS for part in Path(rel).parts):
                continue
            path = root / rel
            if path.is_file():
                result.append(path)
        return sorted(result)
    return sorted(path for path in root.rglob("*") if path.is_file() and not any(part in IGNORED_DIRS for part in path.relative_to(root).parts))

def load_sources(root: Path, max_files: int, max_file_bytes: int) -> tuple[list[SourceFile], dict[str, Any]]:
    sources: list[SourceFile] = []
    skipped = 0
    truncated = False
    for path in tracked_paths(root):
        if len(sources) >= max_files:
            truncated = True
            break
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_file_bytes or path.suffix.lower() not in TEXT_SUFFIXES:
            skipped += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        sources.append(SourceFile(path.relative_to(root).as_posix(), text, size))
    return sources, {"scanned_files": len(sources), "skipped_binary_or_large": skipped, "max_files": max_files, "max_file_bytes": max_file_bytes, "truncated": truncated}

def matching_files(sources: Iterable[SourceFile], patterns: Iterable[str], limit: int = 10, path_only: bool = False) -> list[str]:
    compiled = [re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in patterns]
    result: list[str] = []
    for item in sources:
        target = item.path if path_only else f"{item.path}\n{item.text}"
        if any(pattern.search(target) for pattern in compiled):
            result.append(item.path)
            if len(result) >= limit:
                break
    return result

def present_capabilities(app: dict[str, Any]) -> set[str]:
    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    rows = product.get("feature_signals") if isinstance(product.get("feature_signals"), list) else []
    return {clean(row.get("label")) for row in rows if isinstance(row, dict) and clean(row.get("status")).upper() == "PRESENT" and clean(row.get("label"))}

def infer_product_context(app: dict[str, Any], sources: list[SourceFile]) -> dict[str, Any]:
    capabilities = present_capabilities(app)
    text = "\n".join(item.text[:12000] for item in sources[:800]).casefold()
    category, interaction, reasons = "GENERAL_UTILITY", "TASK_FOCUSED", []
    if "maps_or_location" in capabilities:
        category, interaction, reasons = "MAP_OUTDOOR", "MAP_FIRST", ["maps/location capability is present"]
    elif "media_capture" in capabilities and re.search(r"\b(canvas|sketch|editor|drawing|camera|photo)\b", text):
        category, interaction, reasons = "MEDIA_CREATIVE", "CREATIVE_OR_MEDIA", ["media capture plus creative/editor signals are present"]
    elif re.search(r"\b(note|task|planner|project|workspace|calendar)\b", text):
        category, interaction, reasons = "PRODUCTIVITY", "DENSE_PRODUCTIVITY", ["notes/tasks/planner/workspace signals are present"]
    elif re.search(r"\b(diary|journal|memory|mood|relationship)\b", text):
        category, interaction, reasons = "JOURNAL_LIFESTYLE", "CONTENT_AND_REFLECTION", ["diary/journal/lifestyle signals are present"]
    elif re.search(r"\b(dashboard|admin|developer|diagnostic|inspector|monitoring)\b", text):
        category, interaction, reasons = "DEVELOPER_OR_PRO_TOOL", "DENSE_INFORMATION", ["dashboard/developer/diagnostic signals are present"]
    if not reasons:
        reasons.append("no stronger bounded product-category signal was detected")
    return {"category": category, "interaction_style": interaction, "capabilities": sorted(capabilities), "evidence": reasons}

SYSTEM_RULES = (
    ("FLUTTER_MATERIAL3", "MATERIAL", (r"\bMaterialApp\b", r"\bThemeData\b", r"useMaterial3\s*:\s*true", r"package:flutter/material\.dart")),
    ("FLUTTER_CUPERTINO", "CUPERTINO", (r"\bCupertinoApp\b", r"package:flutter/cupertino\.dart", r"\bCupertino[A-Z]\w+")),
    ("COMPOSE_MATERIAL3", "MATERIAL", (r"androidx\.compose\.material3", r"\bMaterialTheme\b")),
    ("ANDROID_MATERIAL", "MATERIAL", (r"com\.google\.android\.material", r"Theme\.Material3", r"Theme\.MaterialComponents")),
    ("WEB_MUI", "THIRD_PARTY", (r"@mui/material", r"from\s+[\"']@mui")),
    ("WEB_ANT_DESIGN", "THIRD_PARTY", (r"\bantd\b", r"from\s+[\"']antd")),
    ("WEB_CHAKRA", "THIRD_PARTY", (r"@chakra-ui",)),
    ("WEB_MANTINE", "THIRD_PARTY", (r"@mantine/",)),
    ("WEB_RADIX_SHADCN", "THIRD_PARTY", (r"@radix-ui", r"\bshadcn\b", r"components/ui/")),
    ("TAILWIND", "UTILITY_CSS", (r"\btailwindcss\b", r"@tailwind\s")),
    ("BOOTSTRAP", "THIRD_PARTY", (r"\bbootstrap\b", r"react-bootstrap")),
)

def detect_systems(sources: list[SourceFile]) -> list[dict[str, Any]]:
    found = []
    for system_id, family, patterns in SYSTEM_RULES:
        evidence = matching_files(sources, patterns)
        if evidence:
            found.append({"id": system_id, "family": family, "evidence": evidence})
    token_evidence = matching_files(sources, (r"\b(App|Design|Theme)(Colors|Typography|Spacing|Radii|Radius|Elevation|Motion|Tokens)\b", r"--(color|space|radius|font)-", r"\bDesignTokens\b"))
    component_evidence = matching_files(sources, (r"(components|widgets|design_system|design-system|ui/components)", r"class\s+\w+(Button|Card|Field|Dialog|Sheet)\b"))
    if token_evidence or component_evidence:
        found.append({"id": "CUSTOM_DESIGN_LAYER", "family": "CUSTOM", "evidence": sorted(set(token_evidence + component_evidence))[:12]})
    return sorted(found, key=lambda row: row["id"])

def engine(app: dict[str, Any]) -> str:
    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    stack = product.get("stack") if isinstance(product.get("stack"), dict) else {}
    return clean(stack.get("engine")) or "unknown"

def dimension(identifier: str, state: str, rationale: str, evidence: list[str]) -> dict[str, Any]:
    if state not in ALLOWED_DIMENSION_STATES:
        raise ValueError(f"invalid dimension state: {state}")
    return {"id": identifier, "state": state, "rationale": rationale, "evidence": sorted(set(evidence))[:12]}

def evaluate_dimensions(sources: list[SourceFile], context: dict[str, Any], scan: dict[str, Any]) -> list[dict[str, Any]]:
    ui_files = [item for item in sources if re.search(r"\.(dart|kt|java|swift|tsx|ts|jsx|js|css|scss)$", item.path, re.I) and re.search(r"(ui|screen|page|view|widget|component|theme|style|app|main)", item.path, re.I)]
    checks = {
        "hierarchy": (r"\b(TextTheme|typography|headline|titleLarge|displayMedium|h1\b|h2\b|font-size)\b", "Explicit hierarchy/typographic-role signals were detected.", "No bounded hierarchy-role signal was detected."),
        "typography": (r"\b(TextTheme|Typography|fontFamily|font-family|fontSize|font-size)\b", "Typography theme/style signals are present.", "Typography centralization was not clearly detected."),
        "spacing": (r"\b(Spacing|EdgeInsets|padding|gap\s*:|margin\s*:|--space-)\b", "Spacing/layout primitives are present.", "No clear spacing convention was detected."),
        "component_consistency": (r"\b(ButtonTheme|CardTheme|InputDecorationTheme|component[s]?/|widgets/|design_system|design-system)\b", "Reusable component/theme-layer evidence is present.", "Reusable component/theme-layer evidence is weak."),
        "feedback": (r"\b(SnackBar|Toast|ProgressIndicator|CircularProgress|loading|success|error|feedback|status)\b", "Action/status feedback primitives are present.", "Feedback/status primitives were not clearly detected."),
        "empty_loading_error_states": (r"\b(empty|loading|error|retry|skeleton|shimmer|progress)\b", "Empty/loading/error-state signals are present.", "State coverage appears incomplete."),
        "interaction_affordances": (r"\b(IconButton|Button|onPressed|onTap|clickable|role=.button|cursor:\s*pointer)\b", "Interactive affordance signals are present.", "Interactive affordance evidence is incomplete."),
        "accessibility": (r"\b(Semantics|contentDescription|accessibility(Label|Hint)?|aria-label|aria-describedby|tooltip)\b", "Accessibility semantic signals are present.", "Accessibility semantic evidence is incomplete."),
        "responsive": (r"\b(LayoutBuilder|MediaQuery|NavigationRail|breakpoint|Responsive|adaptive|@media|WindowSizeClass)\b", "Responsive/adaptive evidence is present.", "Responsive/adaptive evidence is incomplete."),
        "dark_mode": (r"\b(darkTheme|ThemeMode|dark mode|prefers-color-scheme|isSystemInDarkTheme|night)\b", "Dark/system-theme evidence is present.", "Dark/system-theme evidence is incomplete."),
        "localization": (r"\b(AppLocalizations|localizationsDelegates|supportedLocales|Locale|i18n|l10n|intl|strings\.xml)\b", "Localization infrastructure is present.", "Localization infrastructure evidence is incomplete."),
    }
    rows = []
    for identifier, (pattern, ok, missing) in checks.items():
        evidence = matching_files(ui_files, (pattern,))
        if not ui_files or (scan.get("truncated") and len(ui_files) < 5):
            rows.append(dimension(identifier, "EVIDENCE_INCOMPLETE", "The bounded UI scan is insufficient to assess this dimension.", evidence))
        elif evidence:
            rows.append(dimension(identifier, "FIT", ok, evidence))
        else:
            rows.append(dimension(identifier, "REVIEW", missing, evidence))
    density_evidence = matching_files(ui_files, (r"\b(dense|visualDensity|compact|DataTable|ListTile|grid|table|dashboard)\b",))
    dense = context["interaction_style"] in {"DENSE_PRODUCTIVITY", "DENSE_INFORMATION"}
    density_state = "FIT" if (not dense or density_evidence) else "REVIEW"
    density_reason = "Density evidence fits the inferred interaction style." if density_state == "FIT" else "The product appears information-dense, but compact/density-aware layout evidence is weak."
    rows.insert(3, dimension("density", density_state, density_reason, density_evidence))
    return rows

def system_fit_notes(current_engine: str, context: dict[str, Any], systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for system in systems:
        fit = "COMPATIBLE"
        rationale = "No concrete product-fit conflict was detected."
        if current_engine == "flutter" and system["family"] == "MATERIAL":
            rationale = "Material is a strong Flutter baseline; adapt tokens/components before considering replacement."
        if context["category"] == "MEDIA_CREATIVE" and system["family"] == "MATERIAL":
            fit, rationale = "ADAPT_LIKELY", "Creative/media products may benefit from a more expressive visual layer; adapt the current system before replacement."
        if context["interaction_style"] in {"DENSE_PRODUCTIVITY", "DENSE_INFORMATION"} and system["family"] == "CUPERTINO":
            fit, rationale = "REVIEW", "Verify that the Cupertino-heavy layer supports compact, efficient multi-pane/productivity interaction before standardizing further."
        if system["family"] == "CUSTOM":
            rationale = "A custom token/component layer can express product identity if it remains coherent, accessible and maintainable."
        rows.append({"system": system["id"], "family": system["family"], "fit": fit, "rationale": rationale, "evidence": system["evidence"][:8]})
    return rows

def choose_recommendation(scan: dict[str, Any], systems: list[dict[str, Any]], dimensions: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> tuple[str, str]:
    if scan.get("scanned_files", 0) < 3 or not systems:
        return "EVIDENCE_INCOMPLETE", "Not enough bounded UI-system evidence exists to recommend a library change safely."
    incomplete = sum(row["state"] == "EVIDENCE_INCOMPLETE" for row in dimensions)
    review = sum(row["state"] == "REVIEW" for row in dimensions)
    families = {row["family"] for row in systems if row["id"] != "CUSTOM_DESIGN_LAYER"}
    explicit_mismatch = any(row["fit"] == "REVIEW" for row in comparisons)
    if incomplete >= 4:
        return "EVIDENCE_INCOMPLETE", "Too many visual-system dimensions lack bounded evidence; style churn would be unjustified."
    if explicit_mismatch and review >= 4 and len(families) >= 3:
        return "REPLACE_CANDIDATE", "Fragmented UI families plus a concrete product-fit concern justify evaluating consolidation/replacement as a candidate, not an automatic migration."
    if review >= 3 or any(row["fit"] == "ADAPT_LIKELY" for row in comparisons):
        return "ADAPT", "Targeted token/component/state adaptations have a concrete product-fit benefit without requiring a library rewrite."
    return "KEEP", "No concrete mismatch justifies replacement; preserve the current system and avoid style churn."

def build_report(repo_root: Path, evidence_dir: Path, max_files: int = 4000, max_file_bytes: int = 512000) -> dict[str, Any]:
    graph = load_json(evidence_dir / "evidence-graph.json")
    app = load_json(evidence_dir / "app-intelligence.json") or {}
    simulated = load_json(evidence_dir / "simulated-human-qa.json") or {}
    if not graph:
        raise ValueError("evidence-graph.json is required for Design System Advisor")
    identity = evidence_identity(graph)
    sources, scan = load_sources(repo_root, max_files, max_file_bytes)
    context = infer_product_context(app, sources)
    systems = detect_systems(sources)
    dimensions = evaluate_dimensions(sources, context, scan)
    comparisons = system_fit_notes(engine(app), context, systems)
    decision, rationale = choose_recommendation(scan, systems, dimensions, comparisons)
    findings = []
    for row in dimensions:
        if row["state"] in {"REVIEW", "EVIDENCE_INCOMPLETE"}:
            findings.append({"kind": "VISUAL_DIMENSION_REVIEW" if row["state"] == "REVIEW" else "VISUAL_EVIDENCE_INCOMPLETE", "subject": row["id"], "state": row["state"], "message": row["rationale"], "evidence": row["evidence"], "route": "IMPROVE" if row["state"] == "REVIEW" else "VERIFY_NEXT"})
    for row in comparisons:
        if row["fit"] in {"REVIEW", "ADAPT_LIKELY"}:
            findings.append({"kind": "UI_LIBRARY_PRODUCT_FIT_REVIEW", "subject": row["system"], "state": "REVIEW", "message": row["rationale"], "evidence": row["evidence"], "route": "IMPROVE"})
    counts = Counter(row["state"] for row in dimensions)
    report = {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "record_type": RECORD_TYPE,
        "authority": AUTHORITY,
        "classification": CLASSIFICATION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "source_scan": scan,
        "product_context": context,
        "ui_system": {"engine": engine(app), "primary_detected": systems[0]["id"] if systems else "UNKNOWN", "detected": systems, "comparisons": comparisons},
        "dimensions": dimensions,
        "recommendation": {"decision": decision, "rationale": rationale, "replacement_is_not_default": True},
        "findings": findings[:40],
        "source_evidence": {"app_intelligence_present": (evidence_dir / "app-intelligence.json").is_file(), "simulated_human_present": (evidence_dir / "simulated-human-qa.json").is_file(), "simulated_human_state": clean(simulated.get("state")) or "NOT_AVAILABLE", "evidence_graph_present": True},
        "summary": {"detected_systems": len(systems), "fit_dimensions": counts["FIT"], "review_dimensions": counts["REVIEW"], "evidence_incomplete_dimensions": counts["EVIDENCE_INCOMPLETE"], "not_applicable_dimensions": counts["NOT_APPLICABLE"], "findings": len(findings), "recommendation": decision},
        "guardrails": {"advisory_only": True, "no_release_verdict": True, "cannot_override_fast_full_certification": True, "no_numeric_aesthetic_score": True, "no_automatic_library_replacement": True, "different_library_is_not_automatically_better": True, "recommendations_require_observed_evidence": True, "missing_evidence_fails_closed": True, "source_evidence_remains_authoritative": True},
        "record_digest_sha256": "",
    }
    report["record_digest_sha256"] = report_digest(report)
    return report

def markdown(report: dict[str, Any]) -> str:
    identity, context, ui, rec = report["identity"], report["product_context"], report["ui_system"], report["recommendation"]
    lines = [
        "# AppLab v5.1 — Design System & UI Library Advisor", "",
        f"- Classification: **{CLASSIFICATION}**",
        f"- Project: **{identity['repository']}@{identity['resolved_sha']}**",
        f"- Package: **{identity['package_id']}** · {identity['version_name']} ({identity['version_code']})",
        f"- Product context: **{context['category']}**",
        f"- Interaction style: **{context['interaction_style']}**",
        f"- Primary detected UI system: **{ui['primary_detected']}**",
        f"- Recommendation: **{rec['decision']}**",
        f"- Rationale: {rec['rationale']}", "",
        "## Visual-system dimensions", "", "| Dimension | State | Rationale |", "|---|---|---|",
    ]
    lines.extend(f"| {row['id']} | {row['state']} | {row['rationale']} |" for row in report["dimensions"])
    lines.extend(["", "## Detected systems / product fit", ""])
    lines.extend([f"- **{row['system']} / {row['fit']}** — {row['rationale']}" for row in ui["comparisons"]] or ["- No bounded UI-system evidence detected."])
    lines.extend(["", "## Advisory findings", ""])
    lines.extend([f"- **{row['route']} / {row['kind']} / {row['subject']}** — {row['message']}" for row in report["findings"]] or ["- None."])
    lines.extend(["", "## Authority boundary", "", "- Advisory product/design review only; it is not a release or certification verdict.", "- KEEP / ADAPT / REPLACE_CANDIDATE never override FAST, FULL or CERTIFICATION.", "- Library replacement is never recommended merely because another library exists.", "- Missing visual evidence becomes EVIDENCE_INCOMPLETE, not a false green state.", ""])
    return "\n".join(lines)

def write_report(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "design-system-advisor.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "design-system-advisor.md").write_text(markdown(report), encoding="utf-8")

def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        repo, evidence = root / "repo", root / "evidence"
        (repo / "lib").mkdir(parents=True)
        evidence.mkdir()
        (repo / "pubspec.yaml").write_text("name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
        (repo / "lib" / "main.dart").write_text("import 'package:flutter/material.dart';\nvoid main()=>runApp(MaterialApp(theme: ThemeData(useMaterial3:true),darkTheme:ThemeData.dark(useMaterial3:true),home:Semantics(label:'Home',child:LayoutBuilder(builder:(_,__)=>Scaffold(body:Padding(padding:EdgeInsets.all(16),child:FilledButton(onPressed:(){},child:Text('Continue'))))))));\n", encoding="utf-8")
        graph = {"schema_version": 2, "graph_version": "2.0", "identity": {"repository": "owner/demo", "resolved_sha": "a"*40, "run_id": "123", "package_id": "com.example.demo"}, "root_nodes": {"build_artifact": "artifact:demo"}, "nodes": [{"id": "artifact:demo", "type": "BuildArtifact", "attributes": {"package_id": "com.example.demo", "apk_sha256": "b"*64, "version_name": "1.0.0", "version_code": "1"}}]}
        (evidence / "evidence-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (evidence / "app-intelligence.json").write_text(json.dumps({"product": {"stack": {"engine": "flutter"}, "feature_signals": [{"label": "local_persistence", "status": "PRESENT"}]}}), encoding="utf-8")
        report = build_report(repo, evidence)
        assert report["recommendation"]["decision"] in ALLOWED_RECOMMENDATIONS
        assert len(report["dimensions"]) == 12
        assert report["guardrails"]["no_automatic_library_replacement"] is True
        assert report["record_digest_sha256"] == report_digest(report)
        stale = json.loads(json.dumps(graph))
        stale["nodes"][0]["attributes"]["package_id"] = "other.package"
        (evidence / "evidence-graph.json").write_text(json.dumps(stale), encoding="utf-8")
        try:
            build_report(repo, evidence)
        except ValueError as exc:
            assert "package identity is inconsistent" in str(exc)
        else:
            raise AssertionError("mismatched Evidence Graph identity must fail closed")
    print("AppLab Design System Advisor self-test PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--max-files", type=int, default=4000)
    parser.add_argument("--max-file-bytes", type=int, default=512000)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.repo_root or not args.evidence_dir:
        parser.error("--repo-root and --evidence-dir are required unless --self-test is used")
    output_dir = Path(args.output_dir) if args.output_dir else Path(args.evidence_dir)
    report = build_report(Path(args.repo_root), Path(args.evidence_dir), args.max_files, args.max_file_bytes)
    write_report(output_dir, report)
    print(json.dumps({"lab_version": LAB_VERSION, **report["summary"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab Design System Advisor failed: {exc}") from exc
