#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

IGNORED_DIRS = {
    ".git", ".dart_tool", ".gradle", ".idea", ".vscode", "build",
    "node_modules", "dist", "coverage", ".next", ".venv", "venv",
}
TEXT_SUFFIXES = {
    ".dart", ".kt", ".kts", ".java", ".xml", ".gradle", ".properties",
    ".yaml", ".yml", ".json", ".md", ".txt", ".py", ".ts", ".tsx", ".js",
    ".jsx", ".swift", ".m", ".mm", ".plist",
}
DEFAULT_MAX_FILES = 3500
DEFAULT_MAX_FILE_BYTES = 512_000
SCHEMA_VERSION = 1
LAB_VERSION = "2.3.0"


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    size: int


def tracked_paths(root: Path) -> list[Path]:
    try:
        run = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        run = None
    if run is not None and run.returncode == 0 and run.stdout:
        result: list[Path] = []
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
    result = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        result.append(path)
    return sorted(result)


def load_sources(
    root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> tuple[list[SourceFile], dict]:
    sources: list[SourceFile] = []
    skipped_binary_or_large = 0
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
            skipped_binary_or_large += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        sources.append(
            SourceFile(path=path.relative_to(root).as_posix(), text=text, size=size)
        )
    return sources, {
        "scanned_files": len(sources),
        "skipped_binary_or_large": skipped_binary_or_large,
        "max_files": max_files,
        "max_file_bytes": max_file_bytes,
        "truncated": truncated,
    }


def first_file(sources: Iterable[SourceFile], names: set[str]) -> str:
    for item in sources:
        if Path(item.path).name in names:
            return item.path
    return ""


def matching_files(
    sources: Iterable[SourceFile],
    patterns: Iterable[str],
    *,
    limit: int = 8,
    path_only: bool = False,
) -> list[str]:
    compiled = [re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in patterns]
    result: list[str] = []
    for item in sources:
        target = item.path if path_only else f"{item.path}\n{item.text}"
        if any(pattern.search(target) for pattern in compiled):
            result.append(item.path)
            if len(result) >= limit:
                break
    return result


def signal(
    sources: Iterable[SourceFile],
    patterns: Iterable[str],
    *,
    label: str,
    limit: int = 8,
    path_only: bool = False,
) -> dict:
    evidence = matching_files(sources, patterns, limit=limit, path_only=path_only)
    return {
        "label": label,
        "status": "PRESENT" if evidence else "NOT_DETECTED",
        "evidence": evidence,
    }


def count_by_path_regex(sources: Iterable[SourceFile], pattern: str) -> tuple[int, list[str]]:
    rx = re.compile(pattern, re.IGNORECASE)
    files = [item.path for item in sources if rx.search(item.path)]
    return len(files), files[:12]


def detect_stack(sources: list[SourceFile]) -> dict:
    paths = {item.path for item in sources}
    languages = Counter()
    suffix_map = {
        ".dart": "Dart",
        ".kt": "Kotlin",
        ".kts": "Kotlin",
        ".java": "Java",
        ".swift": "Swift",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".py": "Python",
    }
    for item in sources:
        lang = suffix_map.get(Path(item.path).suffix.lower())
        if lang:
            languages[lang] += 1

    engine = "unknown"
    if any(path.endswith("pubspec.yaml") for path in paths):
        engine = "flutter"
    elif any(Path(path).name in {"settings.gradle", "settings.gradle.kts"} for path in paths):
        engine = "native_android"
    elif any(path.endswith("package.json") for path in paths):
        engine = "web_or_hybrid"

    return {
        "engine": engine,
        "languages": [{"name": name, "files": count} for name, count in languages.most_common()],
        "entry_hints": {
            "pubspec": first_file(sources, {"pubspec.yaml"}),
            "gradle_settings": first_file(sources, {"settings.gradle", "settings.gradle.kts"}),
            "package_json": first_file(sources, {"package.json"}),
            "android_manifest": first_file(sources, {"AndroidManifest.xml"}),
        },
    }


def product_analysis(sources: list[SourceFile]) -> dict:
    feature_signals = [
        signal(sources, [r"firebase_auth", r"FirebaseAuth", r"supabase\.auth", r"google_sign_in", r"CredentialManager"], label="authentication"),
        signal(sources, [r"room\b", r"RoomDatabase", r"drift", r"sqflite", r"hive\b", r"DataStore", r"SharedPreferences"], label="local_persistence"),
        signal(sources, [r"retrofit", r"okhttp", r"dio\b", r"ktor", r"package:http", r"URLSession"], label="network_api"),
        signal(sources, [r"WorkManager", r"workmanager", r"ForegroundService", r"startForeground", r"BGTaskScheduler"], label="background_execution"),
        signal(sources, [r"firebase_messaging", r"FirebaseMessaging", r"NotificationManager", r"flutter_local_notifications", r"UNUserNotificationCenter"], label="notifications"),
        signal(sources, [r"revenuecat", r"purchases_flutter", r"BillingClient", r"google_mobile_ads", r"AdMob", r"in_app_purchase"], label="monetization"),
        signal(sources, [r"firebase_analytics", r"Analytics\b", r"Amplitude", r"Mixpanel", r"PostHog"], label="analytics"),
        signal(sources, [r"openai", r"gemini", r"anthropic", r"embedding", r"llm", r"generative"], label="ai_or_ml"),
        signal(sources, [r"export", r"share_plus", r"ShareCompat", r"csv\b", r"pdf\b", r"backup"], label="export_or_backup"),
        signal(sources, [r"camera", r"image_picker", r"CameraX", r"AVCapture", r"audio", r"microphone"], label="media_capture"),
        signal(sources, [r"google_maps", r"mapbox", r"osm", r"flutter_map", r"geolocator", r"LocationManager"], label="maps_or_location"),
        signal(sources, [r"firebase", r"supabase", r"Firestore", r"cloud", r"sync"], label="cloud_or_sync"),
    ]

    screen_count, screen_files = count_by_path_regex(
        sources, r"(screen|page|view|route|activity|fragment)\.(dart|kt|java|tsx|ts|swift)$"
    )
    test_count, test_files = count_by_path_regex(
        sources, r"(^|/)(test|tests|androidTest|integration_test|e2e)(/|_)"
    )
    docs = matching_files(
        sources,
        [r"PRODUCT_BIBLE", r"README", r"ROADMAP", r"ARCHITECTURE", r"DESIGN_SYSTEM"],
        limit=12,
        path_only=True,
    )
    return {
        "stack": detect_stack(sources),
        "feature_signals": feature_signals,
        "surface": {
            "screen_like_files": screen_count,
            "screen_examples": screen_files,
            "test_like_files": test_count,
            "test_examples": test_files,
            "product_docs": docs,
        },
        "interpretation": (
            "Signals are deterministic source evidence. NOT_DETECTED means AppLab did not "
            "find bounded static evidence; it does not prove the capability is absent."
        ),
    }


def ux_analysis(sources: list[SourceFile]) -> dict:
    ui_files = [
        item for item in sources
        if re.search(r"\.(dart|kt|java|tsx|jsx|swift)$", item.path, re.IGNORECASE)
        and re.search(r"(ui|screen|page|view|activity|fragment|widget|component|route)", item.path, re.IGNORECASE)
    ]
    ui_text = "\n".join(item.text for item in ui_files[:600])
    patterns = {
        "loading_state": r"loading|progress(indicator|bar)?|circularprogress|shimmer",
        "error_state": r"error|failure|retry|try again|riprova",
        "empty_state": r"empty|no items|nothing here|nessun|vuoto",
        "confirmation": r"confirm|confirmation|AlertDialog|showDialog|are you sure|sei sicur",
        "accessibility": r"Semantics|contentDescription|accessibility(Label|Hint)?|aria-label",
        "onboarding": r"onboarding|welcome|intro|firstRun|first_run",
        "search": r"search|SearchBar|SearchView|TextField.*query",
        "undo": r"undo|Snackbar.*undo|annulla",
    }
    coverage = {
        name: bool(re.search(pattern, ui_text, re.IGNORECASE | re.MULTILINE))
        for name, pattern in patterns.items()
    }

    delete_files = matching_files(
        ui_files,
        [r"delete", r"remove", r"elimina", r"trash"],
        limit=12,
    )
    lifecycle_files = matching_files(
        sources,
        [r"softDelete", r"deletedAt", r"trash", r"archive", r"restore", r"riprist"],
        limit=12,
    )
    cancel_side_effects = matching_files(
        sources,
        [r"cancel.*notification", r"notification.*cancel", r"WorkManager.*cancel", r"cancelUniqueWork", r"delete.*attachment", r"remove.*file"],
        limit=12,
    )

    nav_count, nav_files = count_by_path_regex(
        ui_files, r"(router|route|navigation|navgraph|navigator|app\.tsx|main\.dart)"
    )

    findings: list[dict] = []
    if delete_files and not coverage["confirmation"] and not lifecycle_files:
        findings.append({
            "kind": "DESTRUCTIVE_FLOW_GAP_SIGNAL",
            "severity": "REVIEW",
            "message": "Delete/remove signals exist but no bounded confirmation/trash/restore evidence was detected.",
            "evidence": delete_files[:6],
        })
    if len(ui_files) >= 8 and not coverage["accessibility"]:
        findings.append({
            "kind": "ACCESSIBILITY_EVIDENCE_GAP",
            "severity": "REVIEW",
            "message": "UI surface is non-trivial but accessibility annotations were not detected in the bounded scan.",
            "evidence": [item.path for item in ui_files[:6]],
        })
    if len(ui_files) >= 8 and not coverage["error_state"]:
        findings.append({
            "kind": "ERROR_STATE_EVIDENCE_GAP",
            "severity": "REVIEW",
            "message": "UI surface is non-trivial but explicit error/retry states were not detected.",
            "evidence": [item.path for item in ui_files[:6]],
        })

    return {
        "ui_files_scanned": len(ui_files),
        "navigation": {"signal_count": nav_count, "evidence": nav_files},
        "state_coverage": coverage,
        "lifecycle": {
            "delete_or_remove_evidence": delete_files,
            "trash_archive_restore_evidence": lifecycle_files,
            "side_effect_cleanup_evidence": cancel_side_effects,
        },
        "findings": findings,
        "policy": (
            "UX findings are review signals, not automatic defects. AppLab does not fail "
            "verification from static product/UX heuristics."
        ),
    }


def architecture_analysis(sources: list[SourceFile]) -> dict:
    patterns = {
        "repositories": r"(Repository|repository)\.(dart|kt|java|swift|ts|tsx|py)$",
        "view_models": r"(ViewModel|view_model|Bloc|Cubit|Controller)\.(dart|kt|java|swift|ts|tsx|py)$",
        "services": r"(Service|service|Client|client)\.(dart|kt|java|swift|ts|tsx|py)$",
        "models": r"(Model|Entity|Dto|DTO|model|entity)\.(dart|kt|java|swift|ts|tsx|py)$",
        "database": r"(Database|Dao|DAO|database|dao)\.(dart|kt|java|swift|ts|tsx|py)$",
    }
    structure = {}
    for name, pattern in patterns.items():
        count, evidence = count_by_path_regex(sources, pattern)
        structure[name] = {"count": count, "evidence": evidence}

    ui_files = [
        item for item in sources
        if re.search(r"(screen|page|view|activity|fragment|widget|component).*\.(dart|kt|java|tsx|jsx|swift)$", item.path, re.IGNORECASE)
    ]
    direct_remote_ui = []
    for item in ui_files:
        if re.search(
            r"FirebaseFirestore|FirebaseAuth|Supabase|Retrofit|OkHttpClient|Dio\(|http\.(get|post|put|delete)|URLSession",
            item.text,
            re.IGNORECASE,
        ):
            direct_remote_ui.append(item.path)
            if len(direct_remote_ui) >= 12:
                break

    persistence = signal(
        sources,
        [r"RoomDatabase", r"drift", r"sqflite", r"hive\b", r"DataStore", r"SharedPreferences", r"CoreData"],
        label="persistent_local_store",
    )
    sync = signal(
        sources,
        [r"Firestore", r"supabase", r"sync", r"cloud", r"FirebaseDatabase"],
        label="sync_or_remote_store",
    )
    offline = signal(
        sources,
        [r"offline", r"cache", r"connectivity", r"NetworkCapabilities", r"Reachability"],
        label="offline_handling",
    )
    secrets = matching_files(
        sources,
        [
            r"sk-[A-Za-z0-9_-]{20,}",
            r"AIza[0-9A-Za-z_-]{20,}",
            r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
        ],
        limit=8,
    )
    premium_scatter = matching_files(
        ui_files,
        [r"isPremium", r"isPro", r"premium\s*[=!]=?", r"subscription.*active"],
        limit=20,
    )

    findings: list[dict] = []
    if direct_remote_ui:
        findings.append({
            "kind": "UI_DIRECT_REMOTE_DEPENDENCY",
            "severity": "REVIEW",
            "message": "Direct remote/network SDK usage was detected in UI-like files; verify separation of concerns.",
            "evidence": direct_remote_ui,
        })
    if secrets:
        findings.append({
            "kind": "POSSIBLE_EMBEDDED_SECRET",
            "severity": "HIGH_REVIEW",
            "message": "Secret-like material was detected in tracked text. Verify immediately; false positives are possible.",
            "evidence": secrets,
        })
    if len(premium_scatter) >= 5:
        findings.append({
            "kind": "PREMIUM_POLICY_SCATTER",
            "severity": "REVIEW",
            "message": "Premium checks appear in several UI-like files; verify entitlement logic is centralized.",
            "evidence": premium_scatter[:10],
        })

    local_first_status = "UNKNOWN"
    if persistence["status"] == "PRESENT" and offline["status"] == "PRESENT":
        local_first_status = "SUPPORTED_BY_SIGNALS"
    elif persistence["status"] == "PRESENT":
        local_first_status = "LOCAL_PERSISTENCE_ONLY"
    elif sync["status"] == "PRESENT":
        local_first_status = "REMOTE_SIGNALS_WITHOUT_LOCAL_STORE_EVIDENCE"

    return {
        "structure": structure,
        "data": {
            "local_persistence": persistence,
            "sync_or_remote": sync,
            "offline_handling": offline,
            "local_first_assessment": local_first_status,
        },
        "findings": findings,
        "interpretation": (
            "Architecture findings are deterministic heuristics. They identify review targets "
            "and never replace source-level architectural review."
        ),
    }



def deep_product_model(sources: list[SourceFile], product: dict) -> dict:
    """Build a bounded, evidence-first model of product entities and surfaces."""
    entity_candidates: dict[str, set[str]] = {}
    declaration_rx = re.compile(
        r"\b(?:data\s+class|class|struct|interface|enum)\s+([A-Z][A-Za-z0-9_]{2,48})\b"
    )
    entity_path_rx = re.compile(
        r"(model|models|entity|entities|domain|database|db|schema|dto|data)",
        re.IGNORECASE,
    )
    ignored_names = {
        "State", "Event", "Result", "Response", "Request", "Error", "Theme",
        "Color", "Route", "Screen", "Page", "View", "Widget", "Activity",
        "Fragment", "Controller", "Service", "Repository", "Database",
    }
    for item in sources:
        if not entity_path_rx.search(item.path):
            continue
        for match in declaration_rx.finditer(item.text):
            name = match.group(1)
            if name in ignored_names or name.endswith(
                ("Screen", "Page", "View", "Widget", "Activity", "Fragment",
                 "Controller", "Service", "Repository", "Database", "Dao", "DTO")
            ):
                continue
            entity_candidates.setdefault(name, set()).add(item.path)
            if len(entity_candidates) >= 40:
                break
        if len(entity_candidates) >= 40:
            break

    action_patterns = {
        "create": ("create", "insert", "add", "save", "upsert"),
        "update": ("update", "edit", "patch", "modify"),
        "delete": ("delete", "remove", "erase"),
        "archive": ("archive", "trash", "softdelete", "deletedat"),
        "restore": ("restore", "recover", "undelete", "riprist"),
        "share_or_owner": ("share", "owner", "member", "permission", "acl"),
    }
    entities: list[dict] = []
    lifecycle_findings: list[dict] = []
    for name in sorted(entity_candidates):
        needle = re.escape(name)
        evidence = sorted(entity_candidates[name])[:8]
        lifecycle: dict[str, dict] = {}
        for action, verbs in action_patterns.items():
            patterns = [
                rf"\b(?:{'|'.join(verbs)})[A-Za-z0-9_]*{needle}\b",
                rf"\b{needle}[A-Za-z0-9_]*(?:{'|'.join(verbs)})\b",
            ]
            files = matching_files(sources, patterns, limit=8)
            lifecycle[action] = {
                "status": "PRESENT" if files else "NOT_DETECTED",
                "evidence": files,
            }
        mutable = any(
            lifecycle[key]["status"] == "PRESENT" for key in ("create", "update")
        )
        reversible_delete = any(
            lifecycle[key]["status"] == "PRESENT" for key in ("archive", "restore")
        )
        if mutable and lifecycle["delete"]["status"] != "PRESENT" and not reversible_delete:
            lifecycle_findings.append({
                "kind": "ENTITY_LIFECYCLE_DELETE_GAP",
                "severity": "REVIEW",
                "entity": name,
                "message": (
                    f"{name} has create/update evidence but no bounded delete, "
                    "archive or restore evidence."
                ),
                "evidence": evidence,
            })
        entities.append({
            "name": name,
            "declaration_evidence": evidence,
            "lifecycle": lifecycle,
        })

    screen_rows = []
    for item in sources:
        if not re.search(
            r"(screen|page|view|activity|fragment|route)\.(dart|kt|java|tsx|ts|swift)$",
            item.path,
            re.IGNORECASE,
        ):
            continue
        lower = item.path.lower()
        roles = [
            role for role, token in (
                ("onboarding", "onboard"),
                ("home", "home"),
                ("search", "search"),
                ("settings", "setting"),
                ("profile", "profile"),
                ("detail", "detail"),
                ("editor", "editor"),
            )
            if token in lower
        ]
        screen_rows.append({"path": item.path, "roles": roles or ["general"]})
        if len(screen_rows) >= 80:
            break

    docs = [
        item for item in sources
        if re.search(r"(README|PRODUCT_BIBLE|ROADMAP|FEATURE|ARCHITECTURE)", item.path, re.IGNORECASE)
    ][:80]
    doc_text = "\n".join(item.text for item in docs)
    drift: list[dict] = []
    capability_terms = {
        "authentication": r"\b(auth|login|sign[ -]?in|account)\b",
        "local_persistence": r"\b(offline|local[- ]first|database|room|sqlite|drift)\b",
        "network_api": r"\b(api|network|backend|server)\b",
        "background_execution": r"\b(background|workmanager|foreground service)\b",
        "notifications": r"\b(notification|push|reminder)\b",
        "monetization": r"\b(premium|subscription|revenuecat|admob|billing|iap)\b",
        "ai_or_ml": r"\b(ai|artificial intelligence|llm|machine learning|gemini|openai)\b",
        "export_or_backup": r"\b(export|backup|restore)\b",
        "maps_or_location": r"\b(map|maps|location|gps|geolocat)\b",
        "cloud_or_sync": r"\b(sync|cloud|firebase|supabase)\b",
    }
    signal_map = {
        str(row.get("label")): row
        for row in product.get("feature_signals", [])
        if isinstance(row, dict)
    }
    for key, pattern in capability_terms.items():
        claimed = bool(re.search(pattern, doc_text, re.IGNORECASE))
        detected = signal_map.get(key, {}).get("status") == "PRESENT"
        if claimed and not detected:
            drift.append({
                "kind": "DOC_CLAIM_WITHOUT_SOURCE_SIGNAL",
                "severity": "REVIEW",
                "capability": key,
                "message": (
                    f"Documentation mentions {key}, but the bounded source scan "
                    "did not detect matching implementation evidence."
                ),
                "evidence": [item.path for item in docs[:8]],
            })
        elif detected and docs and not claimed:
            drift.append({
                "kind": "SOURCE_SIGNAL_WITHOUT_DOC_CLAIM",
                "severity": "INFO",
                "capability": key,
                "message": (
                    f"Source evidence for {key} exists, but bounded product "
                    "documentation does not mention it."
                ),
                "evidence": signal_map.get(key, {}).get("evidence", [])[:6],
            })

    return {
        "entity_count": len(entities),
        "entities": entities,
        "surface_count": len(screen_rows),
        "surfaces": screen_rows,
        "lifecycle_findings": lifecycle_findings,
        "documentation_drift": drift,
        "summary": {
            "lifecycle_review_signals": len(lifecycle_findings),
            "documentation_drift_signals": sum(
                1 for item in drift if item.get("severity") == "REVIEW"
            ),
        },
        "interpretation": (
            "The Deep Product Model is a bounded static reconstruction. Entity "
            "and lifecycle gaps are review targets, not proof of missing behavior."
        ),
    }



def classify_evidence_path(path: str) -> str:
    lower = path.lower()
    name = Path(lower).name
    if re.search(r"(^|/)(test|tests|androidtest|integration_test|e2e)(/|_)", lower):
        return "TEST"
    if Path(lower).suffix in {".md", ".txt", ".rst"} or re.search(
        r"(^|/)(docs?|documentation)(/|$)", lower
    ):
        return "DOCUMENTATION"
    if (
        name in {
            "pubspec.yaml", "package.json", "androidmanifest.xml",
            "settings.gradle", "settings.gradle.kts", "build.gradle",
            "build.gradle.kts", "gradle.properties",
        }
        or Path(lower).suffix in {".yaml", ".yml", ".json", ".xml", ".properties", ".gradle"}
    ):
        return "CONFIGURATION"
    return "CODE"


def feature_truth(product: dict) -> dict:
    rows = (
        product.get("feature_signals")
        if isinstance(product.get("feature_signals"), list)
        else []
    )
    capabilities: list[dict] = []
    summary = Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        evidence = [
            str(path) for path in row.get("evidence", [])
            if isinstance(path, str) and path
        ]
        provenance: dict[str, list[str]] = {}
        for path in evidence:
            provenance.setdefault(classify_evidence_path(path), []).append(path)
        if provenance.get("CODE"):
            truth = "CODE_CONFIRMED"
        elif provenance.get("CONFIGURATION"):
            truth = "CONFIG_SIGNAL"
        elif provenance.get("TEST"):
            truth = "TEST_ONLY_SIGNAL"
        elif provenance.get("DOCUMENTATION"):
            truth = "DOC_ONLY_SIGNAL"
        else:
            truth = "NOT_DETECTED"
        summary[truth] += 1
        capabilities.append({
            "capability": str(row.get("label", "")),
            "truth": truth,
            "provenance": provenance,
            "evidence_count": len(evidence),
        })
    return {
        "capabilities": capabilities,
        "summary": dict(sorted(summary.items())),
        "interpretation": (
            "Feature Truth classifies the provenance of existing bounded source "
            "signals. CODE_CONFIRMED is stronger evidence than configuration, "
            "test or documentation-only signals; none proves behavioral correctness."
        ),
    }


def product_flow_graph(sources: list[SourceFile], deep: dict) -> dict:
    surfaces = (
        deep.get("surfaces") if isinstance(deep.get("surfaces"), list) else []
    )
    source_by_path = {item.path: item for item in sources}
    nodes: list[dict] = []
    aliases: dict[str, set[str]] = {}
    for row in surfaces[:80]:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path", ""))
        if not path:
            continue
        stem = Path(path).stem
        canonical = re.sub(
            r"(screen|page|view|activity|fragment|route)$", "", stem,
            flags=re.IGNORECASE,
        ).strip("_-") or stem
        tokens = {stem.lower(), canonical.lower()}
        # Camel/Pascal class-like alias and filename alias.
        tokens.add(re.sub(r"[^a-z0-9]", "", stem.lower()))
        aliases[path] = {token for token in tokens if len(token) >= 3}
        nodes.append({
            "id": path,
            "label": canonical,
            "roles": row.get("roles", ["general"]),
        })

    edges: list[dict] = []
    incoming = Counter()
    outgoing = Counter()
    for source in nodes:
        item = source_by_path.get(source["id"])
        if item is None:
            continue
        text_lower = item.text.lower()
        compact = re.sub(r"[^a-z0-9]", "", text_lower)
        for target in nodes:
            if target["id"] == source["id"]:
                continue
            matched = False
            for alias in aliases.get(target["id"], set()):
                if alias in text_lower or alias in compact:
                    matched = True
                    break
            if not matched:
                continue
            edges.append({
                "from": source["id"],
                "to": target["id"],
                "evidence": source["id"],
            })
            incoming[target["id"]] += 1
            outgoing[source["id"]] += 1
            if len(edges) >= 300:
                break
        if len(edges) >= 300:
            break

    orphan_candidates: list[dict] = []
    entry_terms = ("main", "home", "onboard", "launch", "root")
    for node in nodes:
        path_lower = node["id"].lower()
        if incoming[node["id"]] == 0 and not any(term in path_lower for term in entry_terms):
            orphan_candidates.append({
                "surface": node["id"],
                "reason": "No bounded incoming surface reference detected.",
            })

    route_literals: list[str] = []
    route_rx = re.compile(
        r"""(?:(?:route|path|navigate|pushNamed|go|replace)[A-Za-z0-9_]*\s*[:=(,]\s*)["']([^"']{1,80})["']""",
        re.IGNORECASE,
    )
    for item in sources:
        if not re.search(r"(route|router|nav|navigation|screen|page|app\.)", item.path, re.IGNORECASE):
            continue
        for match in route_rx.finditer(item.text):
            token = match.group(1).strip()
            if token and token not in route_literals:
                route_literals.append(token)
                if len(route_literals) >= 100:
                    break
        if len(route_literals) >= 100:
            break

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "route_literals": route_literals,
        "orphan_surface_candidates": orphan_candidates[:30],
        "summary": {
            "orphan_surface_candidates": len(orphan_candidates),
            "bounded": len(edges) >= 300 or len(nodes) >= 80,
        },
        "interpretation": (
            "The flow graph uses bounded static references between detected product "
            "surfaces. Missing edges or orphan candidates require review and do not "
            "prove that a screen is unreachable at runtime."
        ),
    }



def product_consistency(
    product: dict,
    truth: dict,
    deep: dict,
    flow: dict,
    ux: dict,
    architecture: dict,
) -> dict:
    """Normalize cross-plane product evidence into traceable review findings."""
    findings: list[dict] = []
    seen: set[str] = set()

    def add(
        *,
        domain: str,
        kind: str,
        severity: str,
        message: str,
        evidence: Iterable[str] = (),
        subject: str = "",
        confidence: str = "MEDIUM",
    ) -> None:
        evidence_rows = []
        for item in evidence:
            value = str(item).strip()
            if value and value not in evidence_rows:
                evidence_rows.append(value)
            if len(evidence_rows) >= 10:
                break
        key = "|".join([domain, kind, subject, message])
        if key in seen:
            return
        seen.add(key)
        findings.append({
            "id": re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:120],
            "domain": domain,
            "kind": kind,
            "severity": severity,
            "confidence": confidence,
            "subject": subject,
            "message": message,
            "evidence": evidence_rows,
        })

    for item in deep.get("lifecycle_findings", []):
        if not isinstance(item, dict):
            continue
        add(
            domain="lifecycle",
            kind=str(item.get("kind", "ENTITY_LIFECYCLE_REVIEW")),
            severity="REVIEW",
            confidence="MEDIUM",
            subject=str(item.get("entity", "")),
            message=str(item.get("message", "Entity lifecycle requires review.")),
            evidence=item.get("evidence", []),
        )

    for item in deep.get("documentation_drift", []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity", "INFO")).upper()
        if severity == "REVIEW":
            add(
                domain="product_truth",
                kind=str(item.get("kind", "DOCUMENTATION_DRIFT")),
                severity="REVIEW",
                confidence="MEDIUM",
                subject=str(item.get("capability", "")),
                message=str(item.get("message", "Documentation/source drift requires review.")),
                evidence=item.get("evidence", []),
            )

    truth_rows = (
        truth.get("capabilities")
        if isinstance(truth.get("capabilities"), list)
        else []
    )
    for item in truth_rows:
        if not isinstance(item, dict):
            continue
        value = str(item.get("truth", "NOT_DETECTED"))
        if value not in {"DOC_ONLY_SIGNAL", "TEST_ONLY_SIGNAL"}:
            continue
        provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else {}
        evidence: list[str] = []
        for rows in provenance.values():
            if isinstance(rows, list):
                evidence.extend(str(row) for row in rows)
        add(
            domain="product_truth",
            kind="WEAK_CAPABILITY_EVIDENCE",
            severity="REVIEW",
            confidence="HIGH",
            subject=str(item.get("capability", "")),
            message=(
                f"Capability {item.get('capability', '')} is currently supported by "
                f"{value.lower().replace('_', ' ')} rather than implementation-code evidence."
            ),
            evidence=evidence,
        )

    for item in flow.get("orphan_surface_candidates", []):
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface", ""))
        add(
            domain="product_flow",
            kind="ORPHAN_SURFACE_CANDIDATE",
            severity="REVIEW",
            confidence="LOW",
            subject=surface,
            message=str(
                item.get(
                    "reason",
                    "No bounded incoming surface reference was detected.",
                )
            ),
            evidence=[surface] if surface else [],
        )

    for item in ux.get("findings", []):
        if not isinstance(item, dict):
            continue
        add(
            domain="ux",
            kind=str(item.get("kind", "UX_REVIEW")),
            severity="REVIEW",
            confidence="MEDIUM",
            message=str(item.get("message", "UX evidence requires review.")),
            evidence=item.get("evidence", []),
        )

    for item in architecture.get("findings", []):
        if not isinstance(item, dict):
            continue
        source_severity = str(item.get("severity", "REVIEW")).upper()
        severity = "HIGH_REVIEW" if source_severity == "HIGH_REVIEW" else "REVIEW"
        add(
            domain="architecture",
            kind=str(item.get("kind", "ARCHITECTURE_REVIEW")),
            severity=severity,
            confidence="MEDIUM",
            message=str(item.get("message", "Architecture evidence requires review.")),
            evidence=item.get("evidence", []),
        )

    product_surface = (
        product.get("surface") if isinstance(product.get("surface"), dict) else {}
    )
    screen_like = int(product_surface.get("screen_like_files", 0) or 0)
    flow_nodes = int(flow.get("node_count", 0) or 0)
    if screen_like >= 3 and flow_nodes == 0:
        add(
            domain="coverage",
            kind="FLOW_MODEL_COVERAGE_GAP",
            severity="REVIEW",
            confidence="HIGH",
            message=(
                "Multiple screen-like files were detected but the bounded product "
                "flow model produced no surface nodes."
            ),
            evidence=product_surface.get("screen_examples", []),
        )

    data = (
        architecture.get("data")
        if isinstance(architecture.get("data"), dict)
        else {}
    )
    local_first = str(data.get("local_first_assessment", "UNKNOWN"))
    if local_first == "REMOTE_SIGNALS_WITHOUT_LOCAL_STORE_EVIDENCE":
        add(
            domain="data",
            kind="REMOTE_WITHOUT_LOCAL_STORE_EVIDENCE",
            severity="INFO",
            confidence="MEDIUM",
            message=(
                "Remote/sync signals exist without bounded local persistence evidence. "
                "This is informational unless the product contract requires local-first behavior."
            ),
            evidence=(
                (data.get("sync_or_remote") or {}).get("evidence", [])
                if isinstance(data.get("sync_or_remote"), dict)
                else []
            ),
        )

    order = {"HIGH_REVIEW": 0, "REVIEW": 1, "INFO": 2}
    findings.sort(
        key=lambda row: (
            order.get(str(row.get("severity", "INFO")), 9),
            str(row.get("domain", "")),
            str(row.get("kind", "")),
            str(row.get("subject", "")),
        )
    )
    by_domain = Counter(str(row.get("domain", "unknown")) for row in findings)
    by_severity = Counter(str(row.get("severity", "INFO")) for row in findings)
    return {
        "findings": findings,
        "summary": {
            "total": len(findings),
            "high_review": by_severity.get("HIGH_REVIEW", 0),
            "review": by_severity.get("REVIEW", 0),
            "info": by_severity.get("INFO", 0),
            "by_domain": dict(sorted(by_domain.items())),
        },
        "guardrails": {
            "advisory_only": True,
            "no_generated_score": True,
            "no_automatic_feature_requests": True,
            "no_runtime_verdict_override": True,
        },
        "interpretation": (
            "Product Consistency consolidates deterministic review signals across "
            "product truth, lifecycle, flow, UX and architecture. A finding is a "
            "traceable review target, not an automatic defect verdict."
        ),
    }


def build_report(root: Path, max_files: int, max_file_bytes: int) -> dict:
    sources, scan = load_sources(
        root, max_files=max_files, max_file_bytes=max_file_bytes
    )
    confidence = "HIGH"
    if scan["truncated"]:
        confidence = "MEDIUM"
    if scan["scanned_files"] < 3:
        confidence = "LOW"
    product = product_analysis(sources)
    truth = feature_truth(product)
    deep = deep_product_model(sources, product)
    flow = product_flow_graph(sources, deep)
    ux = ux_analysis(sources)
    architecture = architecture_analysis(sources)
    consistency = product_consistency(product, truth, deep, flow, ux, architecture)
    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "root_name": root.name,
        "scan": {**scan, "confidence": confidence},
        "product": product,
        "feature_truth": truth,
        "deep_product_model": deep,
        "product_flow_graph": flow,
        "ux_product": ux,
        "architecture_data": architecture,
        "product_consistency": consistency,
        "guardrails": {
            "non_blocking": True,
            "no_generated_score": True,
            "no_ai_required": True,
            "bounded_static_scan": True,
            "principle": "Evidence first; uncertainty broadens review instead of inventing certainty.",
        },
    }


def markdown(report: dict) -> str:
    product = report["product"]
    ux = report["ux_product"]
    architecture = report["architecture_data"]
    lines = [
        "# AppLab App Intelligence",
        "",
        f"- Lab version: **{report['lab_version']}**",
        f"- Scan confidence: **{report['scan']['confidence']}**",
        f"- Scanned text files: **{report['scan']['scanned_files']}**",
        f"- Truncated: **{report['scan']['truncated']}**",
        "",
        "## Product Analysis",
        "",
        f"- Engine: **{product['stack']['engine']}**",
        f"- Screen-like files: **{product['surface']['screen_like_files']}**",
        f"- Test-like files: **{product['surface']['test_like_files']}**",
        "",
        "| Capability | Signal | Evidence |",
        "|---|---|---|",
    ]
    for item in product["feature_signals"]:
        evidence = ", ".join(item["evidence"][:4]) or "—"
        lines.append(f"| {item['label']} | {item['status']} | {evidence} |")

    consistency = report.get("product_consistency", {})
    consistency_summary = (
        consistency.get("summary")
        if isinstance(consistency.get("summary"), dict)
        else {}
    )
    lines.extend(["", "## Product Consistency", ""])
    lines.append(f"- Total review evidence: **{consistency_summary.get('total', 0)}**")
    lines.append(f"- High review: **{consistency_summary.get('high_review', 0)}**")
    lines.append(f"- Review: **{consistency_summary.get('review', 0)}**")
    for finding in consistency.get("findings", [])[:20]:
        if isinstance(finding, dict):
            subject = f" · {finding.get('subject')}" if finding.get("subject") else ""
            lines.append(
                f"- **{finding.get('severity', 'INFO')} / {finding.get('domain', 'unknown')} / "
                f"{finding.get('kind', 'REVIEW')}**{subject} — {finding.get('message', '')}"
            )

    deep = report.get("deep_product_model", {})
    truth = report.get("feature_truth", {})
    flow = report.get("product_flow_graph", {})
    lines.extend(["", "## Feature Truth", ""])
    for key, value in sorted((truth.get("summary") or {}).items()):
        lines.append(f"- {key}: **{value}**")
    lines.extend(["", "## Product Flow Graph", ""])
    lines.append(f"- Surface nodes: **{flow.get('node_count', 0)}**")
    lines.append(f"- Bounded edges: **{flow.get('edge_count', 0)}**")
    lines.append(
        f"- Orphan surface candidates: **{(flow.get('summary') or {}).get('orphan_surface_candidates', 0)}**"
    )
    for item in flow.get("orphan_surface_candidates", [])[:12]:
        if isinstance(item, dict):
            lines.append(f"- **ORPHAN REVIEW** — {item.get('surface', '')}")

    lines.extend(["", "## Deep Product Model", ""])
    lines.append(f"- Detected entities: **{deep.get('entity_count', 0)}**")
    lines.append(f"- Detected surfaces: **{deep.get('surface_count', 0)}**")
    summary = deep.get("summary", {}) if isinstance(deep.get("summary"), dict) else {}
    lines.append(
        f"- Lifecycle review signals: **{summary.get('lifecycle_review_signals', 0)}**"
    )
    lines.append(
        f"- Documentation drift review signals: **{summary.get('documentation_drift_signals', 0)}**"
    )
    for finding in deep.get("lifecycle_findings", [])[:12]:
        if isinstance(finding, dict):
            lines.append(
                f"- **{finding.get('kind', 'REVIEW')}** · "
                f"{finding.get('entity', 'entity')} — {finding.get('message', '')}"
            )
    for finding in deep.get("documentation_drift", [])[:12]:
        if isinstance(finding, dict) and finding.get("severity") == "REVIEW":
            lines.append(
                f"- **{finding.get('kind', 'REVIEW')}** · "
                f"{finding.get('capability', 'capability')} — {finding.get('message', '')}"
            )

    lines.extend(["", "## UX & Product Lab", ""])
    for name, value in ux["state_coverage"].items():
        lines.append(f"- {name}: **{'DETECTED' if value else 'NOT_DETECTED'}**")
    if ux["findings"]:
        lines.extend(["", "### Review signals", ""])
        for finding in ux["findings"]:
            lines.append(f"- **{finding['kind']}** — {finding['message']}")

    lines.extend(["", "## Architecture & Data Intelligence", ""])
    lines.append(
        f"- Local-first assessment: **{architecture['data']['local_first_assessment']}**"
    )
    for name, value in architecture["structure"].items():
        lines.append(f"- {name}: **{value['count']}**")
    if architecture["findings"]:
        lines.extend(["", "### Review signals", ""])
        for finding in architecture["findings"]:
            lines.append(f"- **{finding['kind']}** — {finding['message']}")

    lines.extend([
        "",
        "## Guardrails",
        "",
        "- Static findings are advisory and never convert runtime FAIL into PASS.",
        "- Missing evidence is reported as unknown/not detected, not invented.",
        "- No opaque product score is generated.",
        "- The lab works without external AI services.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(report: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "app-intelligence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "app-intelligence.md").write_text(markdown(report), encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "lib" / "ui").mkdir(parents=True)
        (root / "lib" / "data").mkdir(parents=True)
        (root / "pubspec.yaml").write_text(
            "name: demo\ndependencies:\n  flutter:\n    sdk: flutter\n  drift: any\n",
            encoding="utf-8",
        )
        (root / "lib" / "ui" / "home_screen.dart").write_text(
            "class HomeScreen {}\n"
            "void deleteItem() {}\n"
            "const loading = true;\n"
            "const contentDescription = 'home';\n",
            encoding="utf-8",
        )
        (root / "lib" / "data" / "app_database.dart").write_text(
            "class AppDatabase extends GeneratedDatabase {}\n"
            "// offline cache\n",
            encoding="utf-8",
        )
        (root / "lib" / "data" / "task_entity.dart").write_text(
            "class TaskEntity {}\n"
            "void createTaskEntity() {}\n"
            "void updateTaskEntity() {}\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            "Demo app with login, notifications and cloud sync.\n",
            encoding="utf-8",
        )
        report = build_report(root, 100, 100_000)
        assert report["product"]["stack"]["engine"] == "flutter"
        assert report["product"]["surface"]["screen_like_files"] >= 1
        assert report["architecture_data"]["data"]["local_persistence"]["status"] == "PRESENT"
        assert report["architecture_data"]["data"]["local_first_assessment"] == "SUPPORTED_BY_SIGNALS"
        assert report["feature_truth"]["capabilities"]
        assert report["product_flow_graph"]["node_count"] >= 1
        assert "product_consistency" in report
        assert report["product_consistency"]["guardrails"]["advisory_only"] is True
        assert report["product_consistency"]["summary"]["total"] >= 1
        assert report["deep_product_model"]["entity_count"] >= 1
        assert any(
            item.get("kind") == "ENTITY_LIFECYCLE_DELETE_GAP"
            for item in report["deep_product_model"]["lifecycle_findings"]
        )
        assert any(
            item.get("kind") == "DOC_CLAIM_WITHOUT_SOURCE_SIGNAL"
            for item in report["deep_product_model"]["documentation_drift"]
        )
        with tempfile.TemporaryDirectory() as out:
            write_outputs(report, Path(out))
            assert (Path(out) / "app-intelligence.json").is_file()
            assert (Path(out) / "app-intelligence.md").is_file()
    print("AppLab App Intelligence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--output-dir", default="applab-intelligence")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.repo_root:
        raise SystemExit("--repo-root is required unless --self-test is used")

    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Repository root does not exist: {root}")
    if args.max_files < 1 or args.max_file_bytes < 1024:
        raise SystemExit("Invalid scan bounds")

    report = build_report(root, args.max_files, args.max_file_bytes)
    write_outputs(report, Path(args.output_dir))
    print(json.dumps({
        "lab_version": report["lab_version"],
        "confidence": report["scan"]["confidence"],
        "scanned_files": report["scan"]["scanned_files"],
        "output_dir": str(Path(args.output_dir)),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
