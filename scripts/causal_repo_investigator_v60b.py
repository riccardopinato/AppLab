#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "causal-repo-investigator-v1.json"
)

PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)"
)
CANDIDATE_SUFFIXES = {
    ".dart", ".py", ".kt", ".java", ".kts", ".gradle", ".xml", ".json",
    ".yaml", ".yml", ".sql", ".sh", ".js", ".jsx", ".ts", ".tsx", ".css",
    ".html", ".swift", ".m", ".mm", ".cpp", ".c", ".h", ".hpp", ".toml",
    ".properties",
}
PROTECTED_PREFIXES = (
    ".github/workflows/",
    ".github/actions/",
    "integration/orchestration/contracts/",
)
LAB_PATH_SIGNALS = {
    "system": ("manifest", "permission", "platform", "android", "native", "system"),
    "performance": ("performance", "render", "startup", "image", "list", "screen", "view", "widget"),
    "network": ("network", "http", "api", "client", "remote", "sync", "dio", "socket"),
    "persistence": ("database", "db", "dao", "store", "repository", "sqlite", "room", "drift", "hive"),
    "configuration": ("lifecycle", "activity", "configuration", "orientation", "theme", "locale", "screen"),
    "resource_pressure": ("memory", "cache", "resource", "process", "image"),
    "background": ("background", "worker", "service", "scheduler", "alarm", "notification", "job"),
    "storage": ("storage", "file", "media", "backup", "export", "import", "asset"),
    "upgrade": ("migration", "schema", "upgrade", "version", "database", "db"),
}
CLASS_SIGNALS = {
    "APP_VISUAL_FAILURE": ("ui", "screen", "widget", "view", "theme", "style", "layout", "visual"),
    "BUILD_OR_QUALITY_FAILURE": ("test", "lint", "build", "config", "gradle", "pubspec", "script"),
}


class InvestigatorError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise InvestigatorError("unsupported causal investigator contract version")
    if payload.get("contract_name") != "APPLAB_CAUSAL_REPO_INVESTIGATOR":
        raise InvestigatorError("unexpected causal investigator contract")
    if payload.get("authority") != "PROPOSAL_ONLY":
        raise InvestigatorError("causal investigator must remain proposal-only")
    return payload


def _safe_rel(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = re.sub(r"/+", "/", text).strip("/")
    if not text:
        return ""
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        return ""
    return path.as_posix()


def _is_candidate_path(path: str) -> bool:
    if not path:
        return False
    name = Path(path).name
    return Path(path).suffix.lower() in CANDIDATE_SUFFIXES or name in {
        "Dockerfile", "Makefile", "pubspec.yaml", "build.gradle", "build.gradle.kts",
    }


def _inventory(repo_root: Path, max_files: int) -> tuple[list[str], bool]:
    tracked: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        tracked = [
            _safe_rel(raw.decode("utf-8", errors="ignore"))
            for raw in proc.stdout.split(b"\0")
            if raw
        ]
    except (OSError, subprocess.SubprocessError):
        tracked = [
            _safe_rel(path.relative_to(repo_root).as_posix())
            for path in repo_root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        ]
    tracked = sorted({path for path in tracked if path and _is_candidate_path(path)})
    return tracked[:max_files], len(tracked) > max_files


def _diagnostic_text(triage: dict[str, Any], diagnostics: str) -> str:
    parts = [diagnostics]
    for key in ("root_cause_hypotheses", "likely_surfaces"):
        values = triage.get(key)
        if isinstance(values, list):
            parts.extend(str(value) for value in values if str(value).strip())
    return "\n".join(parts)


def _diagnostic_paths(text: str) -> set[str]:
    return {_safe_rel(match.group(1)) for match in PATH_RE.finditer(text) if _safe_rel(match.group(1))}


def _graph_file_states(graph: dict[str, Any] | None) -> dict[str, set[str]]:
    states = {"changed": set(), "impacted": set()}
    if not isinstance(graph, dict):
        return states
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return states
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "File":
            continue
        attrs = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
        path = _safe_rel(attrs.get("path") or node.get("key") or node.get("label"))
        if not path:
            continue
        if attrs.get("changed") is True or str(attrs.get("change_state", "")).upper() == "CHANGED":
            states["changed"].add(path)
        if attrs.get("dependency_impacted") is True or str(attrs.get("change_state", "")).upper() == "DEPENDENCY_IMPACT":
            states["impacted"].add(path)
    return states


def _prior_fix_paths(history: dict[str, Any] | None) -> set[str]:
    result: set[str] = set()
    if not isinstance(history, dict):
        return result
    rows = history.get("successful_repairs")
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        for raw in row.get("files", []) if isinstance(row.get("files"), list) else []:
            path = _safe_rel(raw)
            if path:
                result.add(path)
    return result


def _surface_tokens(triage: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    values = triage.get("likely_surfaces")
    if not isinstance(values, list):
        return tokens
    ignored = {"change", "category", "domain", "runtime", "current", "surface"}
    for value in values:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", str(value).lower()):
            if token not in ignored:
                tokens.add(token)
    return tokens


def _changed_paths(plan: dict[str, Any]) -> set[str]:
    result = {
        _safe_rel(value)
        for value in plan.get("changed_files", [])
        if isinstance(value, str) and _safe_rel(value)
    }
    changes = plan.get("changes")
    if isinstance(changes, list):
        for row in changes:
            if not isinstance(row, dict):
                continue
            for field in ("path", "previous_path"):
                path = _safe_rel(row.get(field))
                if path:
                    result.add(path)
    return result


def _impacted_paths(plan: dict[str, Any]) -> set[str]:
    return {
        _safe_rel(value)
        for value in plan.get("impacted_files", [])
        if isinstance(value, str) and _safe_rel(value)
    }


def _paired_tests(path: str, inventory: set[str]) -> list[str]:
    candidate = Path(path)
    stem = candidate.stem
    results: list[str] = []
    if path.startswith("lib/") and candidate.suffix == ".dart":
        exact = "test/" + path[4:]
        exact = re.sub(r"\.dart$", "_test.dart", exact)
        if exact in inventory:
            results.append(exact)
    for item in sorted(inventory):
        lower = item.lower()
        if not (
            lower.startswith(("test/", "tests/"))
            or "/src/test/" in f"/{lower}"
            or "/src/androidtest/" in f"/{lower}"
        ):
            continue
        item_stem = Path(item).stem.lower()
        if stem.lower() in item_stem or item_stem in {stem.lower(), f"{stem.lower()}_test"}:
            results.append(item)
        if len(results) >= 5:
            break
    return list(dict.fromkeys(results))


def _candidate_kind(path: str) -> str:
    lower = path.lower()
    if lower.startswith(("test/", "tests/")) or "/src/test/" in f"/{lower}" or "/src/androidtest/" in f"/{lower}":
        return "TEST"
    if lower.startswith(PROTECTED_PREFIXES):
        return "PROTECTED"
    if Path(lower).suffix in {".yaml", ".yml", ".json", ".toml", ".properties", ".gradle", ".kts"}:
        return "CONFIG"
    return "SOURCE"


def build_investigation(
    triage: dict[str, Any],
    plan: dict[str, Any],
    repo_root: Path,
    *,
    diagnostics: str = "",
    evidence_graph: dict[str, Any] | None = None,
    history: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_contract()
    classification = str(triage.get("classification", "UNKNOWN_FAILURE"))
    base = {
        "schema_version": 1,
        "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
        "authority": "PROPOSAL_ONLY",
        "repository": str(triage.get("repository") or plan.get("repository") or ""),
        "resolved_sha": str(triage.get("resolved_sha") or plan.get("head_sha") or ""),
        "baseline_sha": str(triage.get("baseline_sha") or plan.get("baseline_sha") or ""),
        "classification": classification,
        "repository_mutation_performed": False,
        "verification_authority": "UNCHANGED",
        "certification_authority": "UNCHANGED",
    }

    if classification in set(contract["non_editable_failure_classes"]):
        return {
            **base,
            "state": "NON_CODE_FAILURE",
            "edit_recommendation": "DENY_AUTONOMOUS_EDIT",
            "ranked_candidate_files": [],
            "required_regression_targets": list(
                dict.fromkeys(str(x) for x in triage.get("required_regression_evidence", []) if str(x))
            ),
            "unresolved_uncertainty": [
                f"{classification} is not eligible for deterministic code repair localization"
            ],
            "evidence_summary": {
                "inventory_truncated": False,
                "analysis_truncated": bool(plan.get("analysis_truncated")),
                "diagnostic_path_count": 0,
            },
        }

    if classification not in set(contract["deterministic_failure_classes"]):
        raise InvestigatorError(f"unsupported failure classification: {classification}")

    inventory_list, inventory_truncated = _inventory(
        repo_root, int(contract["max_repository_files"])
    )
    inventory = set(inventory_list)
    changed = _changed_paths(plan)
    impacted = _impacted_paths(plan)
    for path in sorted(changed | impacted):
        if _is_candidate_path(path) and (repo_root / path).is_file():
            inventory.add(path)

    diagnostic_text = _diagnostic_text(triage, diagnostics)
    diagnostic_lower = diagnostic_text.lower()
    diagnostic_paths = _diagnostic_paths(diagnostic_text)
    graph_states = _graph_file_states(evidence_graph)
    prior = _prior_fix_paths(history)
    surface_tokens = _surface_tokens(triage)
    failed_labs = {
        str(value)
        for value in triage.get("failed_labs", [])
        if str(value) in LAB_PATH_SIGNALS
    }
    class_tokens = CLASS_SIGNALS.get(classification, ())
    weights = contract["score_weights"]

    ranked: list[dict[str, Any]] = []
    for path in sorted(inventory):
        score = 0
        signals: list[dict[str, Any]] = []
        lower = path.lower()
        basename = Path(path).name.lower()

        def add(kind: str, weight_key: str, detail: str) -> None:
            nonlocal score
            weight = int(weights[weight_key])
            score += weight
            signals.append({"kind": kind, "weight": weight, "detail": detail})

        if path in changed:
            add("CHANGED_FILE", "changed_file", path)
        if path in impacted:
            add("DEPENDENCY_IMPACT", "dependency_impacted", path)
        if path in diagnostic_paths:
            add("EXACT_DIAGNOSTIC_PATH", "exact_diagnostic_path", path)
        if len(basename) >= 5 and basename in diagnostic_lower:
            add("DIAGNOSTIC_BASENAME", "diagnostic_basename", basename)

        lab_matches: list[str] = []
        for lab in sorted(failed_labs):
            if any(token in lower for token in LAB_PATH_SIGNALS[lab]):
                lab_matches.append(lab)
        if lab_matches:
            add(
                "FAILED_LAB_PATH_SIGNAL",
                "failed_lab_path_signal",
                ",".join(lab_matches),
            )

        matching_surface = sorted(token for token in surface_tokens if token in lower)
        if matching_surface or any(token in lower for token in class_tokens):
            details = matching_surface or [token for token in class_tokens if token in lower]
            add("SURFACE_PATH_SIGNAL", "surface_path_signal", ",".join(details[:6]))

        if path in graph_states["changed"]:
            add("EVIDENCE_GRAPH_CHANGED", "evidence_graph_changed", path)
        if path in graph_states["impacted"]:
            add("EVIDENCE_GRAPH_IMPACTED", "evidence_graph_impacted", path)
        if path in prior:
            add("PRIOR_SUCCESSFUL_FIX", "prior_fix_path", path)
        if path in changed and (
            path in diagnostic_paths or (len(basename) >= 5 and basename in diagnostic_lower)
        ):
            add(
                "CHANGED_DIAGNOSTIC_CONVERGENCE",
                "changed_plus_diagnostic_bonus",
                path,
            )

        if score < int(contract["candidate_threshold"]):
            continue
        confidence = min(0.99, 0.35 + (score / 180.0))
        if bool(plan.get("analysis_truncated")):
            confidence = max(0.05, confidence - 0.20)
        if inventory_truncated:
            confidence = max(0.05, confidence - 0.10)
        ranked.append(
            {
                "path": path,
                "kind": _candidate_kind(path),
                "score": score,
                "confidence": round(confidence, 3),
                "signals": signals,
                "paired_tests": _paired_tests(path, inventory),
            }
        )

    ranked.sort(key=lambda row: (-int(row["score"]), row["path"]))
    ranked = ranked[: int(contract["max_candidates"])]

    uncertainty: list[str] = []
    if bool(plan.get("analysis_truncated")):
        uncertainty.append("impact analysis is truncated")
    if inventory_truncated:
        uncertainty.append("repository candidate inventory exceeded bounded scan limit")
    if ranked and len(ranked) > 1:
        margin = int(ranked[0]["score"]) - int(ranked[1]["score"])
        if margin < 15:
            uncertainty.append("top causal candidates are closely scored")
    if not diagnostic_paths:
        uncertainty.append("diagnostics contain no explicit repository path")

    regressions = [
        str(value)
        for value in triage.get("required_regression_evidence", [])
        if str(value).strip()
    ]
    for candidate in ranked[:3]:
        regressions.extend(candidate["paired_tests"])
    regressions = list(dict.fromkeys(regressions))

    if not ranked:
        state = "INSUFFICIENT_EVIDENCE"
        recommendation = "DENY_AUTONOMOUS_EDIT"
        uncertainty.append("no repository file reached the causal evidence threshold")
    else:
        state = "LOCALIZED"
        top = ranked[0]
        protected = top["kind"] == "PROTECTED"
        recommendation = (
            "ELIGIBLE_FOR_BOUNDED_REPAIR"
            if float(top["confidence"]) >= 0.65
            and not bool(plan.get("analysis_truncated"))
            and not protected
            else "HUMAN_OR_DEEPER_INVESTIGATION_REQUIRED"
        )
        if protected:
            uncertainty.append("top candidate is protected by the repair authority boundary")

    return {
        **base,
        "state": state,
        "edit_recommendation": recommendation,
        "ranked_candidate_files": ranked,
        "required_regression_targets": regressions,
        "unresolved_uncertainty": list(dict.fromkeys(uncertainty)),
        "evidence_summary": {
            "inventory_file_count": len(inventory),
            "inventory_truncated": inventory_truncated,
            "analysis_truncated": bool(plan.get("analysis_truncated")),
            "changed_file_count": len(changed),
            "impacted_file_count": len(impacted),
            "diagnostic_path_count": len(diagnostic_paths),
            "graph_changed_count": len(graph_states["changed"]),
            "graph_impacted_count": len(graph_states["impacted"]),
            "prior_fix_path_count": len(prior),
        },
        "guardrails": {
            "automatic_code_change": False,
            "automatic_retry": False,
            "automatic_merge": False,
            "automatic_release": False,
            "candidate_scores_are_advisory": True,
        },
    }


def read_json(path: str) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvestigatorError(f"JSON root must be an object: {path}")
    return payload


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "lib/network").mkdir(parents=True)
        (root / "test/network").mkdir(parents=True)
        (root / "lib/ui").mkdir(parents=True)
        (root / "lib/network/client.dart").write_text("class ApiClient {}\n", encoding="utf-8")
        (root / "test/network/client_test.dart").write_text("void main() {}\n", encoding="utf-8")
        (root / "lib/ui/home_screen.dart").write_text("class HomeScreen {}\n", encoding="utf-8")

        triage = {
            "repository": "owner/app",
            "resolved_sha": "b" * 40,
            "baseline_sha": "a" * 40,
            "classification": "APP_RUNTIME_FAILURE",
            "failed_labs": ["network"],
            "likely_surfaces": ["network client", "sync/connectivity"],
            "root_cause_hypotheses": ["lib/network/client.dart:42 reconnect failed"],
            "required_regression_evidence": ["focused regression for network"],
        }
        plan = {
            "repository": "owner/app",
            "head_sha": "b" * 40,
            "baseline_sha": "a" * 40,
            "changed_files": ["lib/network/client.dart"],
            "impacted_files": ["lib/ui/home_screen.dart"],
            "analysis_truncated": False,
        }
        graph = {
            "nodes": [
                {
                    "type": "File",
                    "key": "lib/network/client.dart",
                    "attributes": {
                        "path": "lib/network/client.dart",
                        "changed": True,
                        "change_state": "CHANGED",
                    },
                }
            ]
        }
        history = {
            "successful_repairs": [
                {"files": ["lib/network/client.dart"], "signature": "network-reconnect"}
            ]
        }
        report = build_investigation(
            triage,
            plan,
            root,
            diagnostics="stack at lib/network/client.dart:42\nclient.dart reconnect",
            evidence_graph=graph,
            history=history,
        )
        assert report["state"] == "LOCALIZED", report
        assert report["edit_recommendation"] == "ELIGIBLE_FOR_BOUNDED_REPAIR", report
        top = report["ranked_candidate_files"][0]
        assert top["path"] == "lib/network/client.dart", top
        assert top["confidence"] >= 0.9, top
        assert "test/network/client_test.dart" in report["required_regression_targets"]
        kinds = {signal["kind"] for signal in top["signals"]}
        assert {"CHANGED_FILE", "EXACT_DIAGNOSTIC_PATH", "FAILED_LAB_PATH_SIGNAL"} <= kinds

        unknown = build_investigation(
            {**triage, "classification": "UNKNOWN_FAILURE"},
            plan,
            root,
        )
        assert unknown["state"] == "NON_CODE_FAILURE"
        assert unknown["ranked_candidate_files"] == []
        assert unknown["edit_recommendation"] == "DENY_AUTONOMOUS_EDIT"

        truncated = build_investigation(
            triage,
            {**plan, "analysis_truncated": True},
            root,
        )
        assert truncated["edit_recommendation"] != "ELIGIBLE_FOR_BOUNDED_REPAIR"
        assert "impact analysis is truncated" in truncated["unresolved_uncertainty"]

        visual = build_investigation(
            {
                **triage,
                "classification": "APP_VISUAL_FAILURE",
                "failed_labs": [],
                "likely_surfaces": ["home screen layout"],
                "root_cause_hypotheses": ["home_screen.dart visual mismatch"],
            },
            {
                **plan,
                "changed_files": ["lib/ui/home_screen.dart"],
                "impacted_files": [],
            },
            root,
        )
        assert visual["ranked_candidate_files"][0]["path"] == "lib/ui/home_screen.dart"

    print("AppLab v6.0B causal repo investigator self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--triage", default="")
    parser.add_argument("--plan", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--diagnostics", default="")
    parser.add_argument("--evidence-graph", default="")
    parser.add_argument("--history", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.triage or not args.plan:
        raise SystemExit("--triage and --plan are required")
    diagnostics = ""
    if args.diagnostics:
        diagnostics = Path(args.diagnostics).read_text(encoding="utf-8", errors="ignore")
    report = build_investigation(
        read_json(args.triage),
        read_json(args.plan),
        Path(args.repo_root).resolve(),
        diagnostics=diagnostics,
        evidence_graph=read_json(args.evidence_graph) if args.evidence_graph else None,
        history=read_json(args.history) if args.history else None,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
