#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from product_review_common import load_json, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "5.0.0"
RECORD_TYPE = "SIMULATED_HUMAN_QA"
AUTHORITY = "APPLAB_SIMULATED_HUMAN_QA_ADVISORY"
CLASSIFICATION = "SIMULATED USER REVIEW"

PERSONAS = (
    "beginner",
    "power_user",
    "older_user",
    "accessibility_focused",
    "privacy_conscious",
    "impatient",
    "offline_user",
)

ALLOWED_OUTCOMES = {
    "FRICTION_SIGNAL",
    "EVIDENCE_INCOMPLETE",
    "NO_STRONG_SIGNAL",
    "NOT_APPLICABLE",
}
ALLOWED_ROUTES = {"VERIFY_NEXT", "IMPROVE", "NO_ACTION"}
ADVISORY_STATES = {"REVIEW_REQUIRED", "EVIDENCE_INCOMPLETE", "NO_STRONG_SIGNAL"}

PERSONA_FOCUS: dict[str, set[str]] = {
    "beginner": {"discoverability", "clarity", "navigation", "recovery", "feedback"},
    "power_user": {"efficiency", "navigation", "feedback"},
    "older_user": {"clarity", "discoverability", "recovery", "accessibility"},
    "accessibility_focused": {"accessibility", "clarity", "feedback", "recovery"},
    "privacy_conscious": {"privacy", "permission", "auth", "storage", "clarity"},
    "impatient": {"efficiency", "feedback", "navigation", "discoverability"},
    "offline_user": {"offline", "network", "recovery", "feedback"},
}

PERSONA_TASKS: dict[str, tuple[dict[str, Any], ...]] = {
    "beginner": (
        {"id": "discover_core_path", "goal": "Discover and begin a core product path.", "tags": {"discoverability", "clarity", "navigation"}, "needs": {"journey"}},
        {"id": "recover_from_unclear_action", "goal": "Recover after an unclear or non-changing action.", "tags": {"feedback", "recovery", "clarity"}, "needs": {"journey", "ux"}},
    ),
    "power_user": (
        {"id": "complete_core_path_efficiently", "goal": "Complete an observed core path without unnecessary navigation.", "tags": {"efficiency", "navigation"}, "needs": {"journey"}},
        {"id": "repeat_common_action", "goal": "Repeat a common action with predictable feedback.", "tags": {"efficiency", "feedback"}, "needs": {"journey", "ux"}},
    ),
    "older_user": (
        {"id": "identify_next_action", "goal": "Identify the next action from available labels and structure.", "tags": {"clarity", "discoverability", "accessibility"}, "needs": {"journey", "ux"}},
        {"id": "recover_from_problem_state", "goal": "Recover from an observed or applicable problem state.", "tags": {"recovery", "clarity"}, "needs": {"state"}},
    ),
    "accessibility_focused": (
        {"id": "understand_control_semantics", "goal": "Understand controls from the available UI semantics.", "tags": {"accessibility", "clarity"}, "needs": {"journey", "ux"}},
        {"id": "receive_action_feedback", "goal": "Receive clear feedback and recovery cues after actions.", "tags": {"feedback", "recovery", "accessibility"}, "needs": {"journey", "ux"}},
    ),
    "privacy_conscious": (
        {"id": "understand_sensitive_flow", "goal": "Understand an applicable auth, permission, privacy or storage-sensitive flow.", "tags": {"privacy", "permission", "auth", "storage", "clarity"}, "needs": {"sensitive"}},
        {"id": "recover_from_sensitive_denial", "goal": "Recover from an applicable permission/auth denial or unavailable state.", "tags": {"permission", "auth", "recovery"}, "needs": {"sensitive", "state"}},
    ),
    "impatient": (
        {"id": "reach_goal_quickly", "goal": "Reach an observed goal with a short, direct path.", "tags": {"efficiency", "navigation", "discoverability"}, "needs": {"journey"}},
        {"id": "see_immediate_feedback", "goal": "See immediate evidence of response after an action.", "tags": {"feedback", "efficiency"}, "needs": {"journey", "ux"}},
    ),
    "offline_user": (
        {"id": "continue_without_network", "goal": "Continue or fail clearly when connectivity is unavailable.", "tags": {"offline", "network", "feedback"}, "needs": {"offline"}},
        {"id": "recover_connectivity", "goal": "Recover or retry after an offline/network condition.", "tags": {"offline", "network", "recovery"}, "needs": {"offline", "state"}},
    ),
}

SOURCE_FILES = {
    "app": "app-intelligence.json",
    "journey": "user-journey.json",
    "ux": "ux-friction.json",
    "state": "state-edge-case.json",
    "graph": "evidence-graph.json",
    "confidence": "evidence-confidence.json",
}

TAG_RULES: dict[str, tuple[str, ...]] = {
    "discoverability": ("discover", "unobserved_core_surface", "core_surface", "deep_journey"),
    "clarity": ("ambiguous", "label", "clarity", "unknown", "confus"),
    "navigation": ("navigation", "loop", "journey", "dead_end", "path"),
    "recovery": ("recover", "retry", "error", "denied", "dead_end", "failure"),
    "feedback": ("no_change", "stable_signature", "feedback", "loading", "response"),
    "efficiency": ("deep_journey", "density", "excess", "tap", "efficien"),
    "accessibility": ("accessib", "semantic", "content_desc", "content-desc", "label"),
    "privacy": ("privacy", "personal", "sensitive"),
    "permission": ("permission", "denied"),
    "auth": ("auth", "login", "sign_in", "sign in"),
    "storage": ("storage", "file", "backup"),
    "offline": ("offline", "connectivity"),
    "network": ("network", "connectivity", "http"),
}

WALKTHROUGH_CRITERIA: dict[str, set[str]] = {
    "goal_discoverability": {"discoverability", "clarity", "navigation"},
    "next_action_identifiability": {"clarity", "accessibility", "navigation"},
    "feedback_after_action": {"feedback", "efficiency"},
    "recovery_path": {"recovery", "offline", "network", "permission", "auth"},
}

HEURISTICS: dict[str, set[str]] = {
    "visibility_and_feedback": {"feedback"},
    "clarity_and_match": {"clarity", "discoverability"},
    "user_control_and_recovery": {"recovery", "navigation"},
    "efficiency": {"efficiency"},
    "error_prevention_and_recovery": {"recovery", "permission", "auth", "offline", "network"},
    "accessibility_support": {"accessibility", "clarity"},
}


def clean(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def digest_payload(report: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(report))
    clone.pop("generated_at", None)
    clone["record_digest_sha256"] = ""
    return clone


def report_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(digest_payload(report))).hexdigest()


def evidence_identity(graph: dict[str, Any]) -> dict[str, str]:
    if graph.get("schema_version") != 2 or clean(graph.get("graph_version")) != "2.0":
        raise ValueError("Evidence Graph schema/version is invalid")
    identity = graph.get("identity") if isinstance(graph.get("identity"), dict) else {}
    roots = graph.get("root_nodes") if isinstance(graph.get("root_nodes"), dict) else {}
    artifact_id = clean(roots.get("build_artifact"))
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    artifact_rows = [
        row
        for row in nodes
        if isinstance(row, dict)
        and clean(row.get("id")) == artifact_id
        and clean(row.get("type")) == "BuildArtifact"
    ]
    if not artifact_id or len(artifact_rows) != 1:
        raise ValueError("Evidence Graph canonical build artifact is missing")
    attrs = (
        artifact_rows[0].get("attributes")
        if isinstance(artifact_rows[0].get("attributes"), dict)
        else {}
    )
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


TAG_PREFIX_PATTERNS = {"discover", "confus", "efficien", "accessib", "recover", "permission", "http"}


def text_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold().replace("_", " ").replace("-", " "))


def pattern_matches(tokens: list[str], pattern: str) -> bool:
    wanted = text_tokens(pattern)
    if not wanted:
        return False
    if len(wanted) == 1:
        token = wanted[0]
        if token in TAG_PREFIX_PATTERNS:
            return any(value.startswith(token) for value in tokens)
        return token in tokens
    width = len(wanted)
    return any(tokens[index:index + width] == wanted for index in range(len(tokens) - width + 1))


def tags_for_text(*values: object) -> list[str]:
    tokens = text_tokens(" ".join(clean(value) for value in values if clean(value)))
    return sorted(
        tag
        for tag, patterns in TAG_RULES.items()
        if any(pattern_matches(tokens, pattern) for pattern in patterns)
    )


def normalized_evidence(source: str, rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(rows[:200]):
        if not isinstance(raw, dict):
            continue
        kind = clean(raw.get("kind")) or clean(raw.get("category")) or f"finding_{index + 1}"
        subject = (
            clean(raw.get("subject"))
            or clean(raw.get("state"))
            or clean(raw.get("capability"))
            or kind
        )
        message = clean(raw.get("message"))
        severity = clean(raw.get("severity")).upper() or "INFO"
        tags = tags_for_text(kind, subject, message, raw.get("category"))
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
        result.append(
            {
                "id": hashlib.sha256(
                    canonical_bytes([source, kind, subject, message, index])
                ).hexdigest()[:16],
                "source": source,
                "kind": kind,
                "subject": subject,
                "message": message,
                "severity": severity,
                "tags": tags,
                "evidence": [clean(item) for item in evidence if clean(item)][:12],
            }
        )
    return result


def state_signals(state_report: dict[str, Any]) -> list[dict[str, Any]]:
    raw_findings = state_report.get("findings")
    result = normalized_evidence(SOURCE_FILES["state"], raw_findings)
    covered_states = {
        clean(row.get("state") or row.get("subject"))
        for row in raw_findings
        if isinstance(raw_findings, list) and isinstance(row, dict)
    } if isinstance(raw_findings, list) else set()
    states = state_report.get("states") if isinstance(state_report.get("states"), dict) else {}
    for key, row in sorted(states.items()):
        if not isinstance(row, dict):
            continue
        status = clean(row.get("status")).upper()
        applicability = clean(row.get("applicability")).upper()
        if applicability == "NOT_APPLICABLE":
            continue
        if status not in {"OBSERVED_FAIL", "NOT_OBSERVED", "OBSERVED_UNKNOWN"}:
            continue
        if clean(key) in covered_states:
            continue
        kind = "EDGE_STATE_FAILURE" if status == "OBSERVED_FAIL" else "EDGE_STATE_EVIDENCE_GAP"
        tags = tags_for_text(key, kind)
        result.append(
            {
                "id": hashlib.sha256(canonical_bytes([SOURCE_FILES["state"], key, status])).hexdigest()[:16],
                "source": SOURCE_FILES["state"],
                "kind": kind,
                "subject": clean(key),
                "message": f"{key}: {status} ({applicability or 'UNKNOWN_APPLICABILITY'})",
                "severity": "HIGH_REVIEW" if status == "OBSERVED_FAIL" else "REVIEW",
                "tags": tags,
                "evidence": [],
            }
        )
    return result


def evidence_posture(
    app: dict[str, Any],
    journey: dict[str, Any],
    ux: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    journey_summary = journey.get("summary") if isinstance(journey.get("summary"), dict) else {}
    state_states = state.get("states") if isinstance(state.get("states"), dict) else {}
    feature_rows = (
        ((app.get("product") or {}).get("feature_signals") or [])
        if isinstance(app.get("product"), dict)
        else []
    )
    features = {
        clean(row.get("label")).casefold()
        for row in feature_rows
        if isinstance(row, dict) and clean(row.get("status")).upper() == "PRESENT"
    }
    sensitive_tokens = {"authentication", "permissions", "storage", "file_picker", "biometrics", "camera"}
    offline_state = state_states.get("offline") if isinstance(state_states.get("offline"), dict) else {}
    return {
        "journey": int(journey_summary.get("journeys_observed", 0) or 0) > 0,
        "ux": isinstance(ux.get("findings"), list),
        "state": bool(state_states),
        "offline": bool(offline_state) and clean(offline_state.get("applicability")).upper() != "NOT_APPLICABLE",
        "sensitive": bool(features & sensitive_tokens)
        or any(key in state_states for key in ("auth", "permission", "permissions", "storage")),
    }


def task_session(
    persona: str,
    task: dict[str, Any],
    signals: list[dict[str, Any]],
    posture: dict[str, Any],
) -> dict[str, Any]:
    tags = set(task["tags"])
    needs = set(task["needs"])
    available = all(bool(posture.get(need)) for need in needs)
    relevant = (
        [row for row in signals if tags & set(row.get("tags") or [])]
        if available
        else []
    )
    if not available:
        if "sensitive" in needs and not posture.get("sensitive"):
            outcome = "NOT_APPLICABLE"
            rationale = "No applicable sensitive capability/state was evidenced for this product."
        elif "offline" in needs and not posture.get("offline"):
            outcome = "EVIDENCE_INCOMPLETE"
            rationale = "Offline applicability or observation is not sufficiently evidenced."
        else:
            outcome = "EVIDENCE_INCOMPLETE"
            rationale = "The required trusted evidence for this bounded task is incomplete."
    elif relevant:
        outcome = "FRICTION_SIGNAL"
        rationale = "Existing AppLab evidence exposes one or more review signals relevant to this bounded task."
    else:
        outcome = "NO_STRONG_SIGNAL"
        rationale = "Available evidence does not contain a strong simulated-review signal for this task."

    criteria: list[dict[str, Any]] = []
    for name, criterion_tags in WALKTHROUGH_CRITERIA.items():
        hits = [row["id"] for row in relevant if criterion_tags & set(row.get("tags") or [])]
        if hits:
            state = "REVIEW_SIGNAL"
        elif available:
            state = "EVIDENCE_AVAILABLE_NO_SIGNAL"
        else:
            state = "EVIDENCE_INCOMPLETE"
        criteria.append({"criterion": name, "state": state, "signal_ids": hits[:12]})

    return {
        "task_id": clean(task["id"]),
        "goal": clean(task["goal"]),
        "outcome": outcome,
        "rationale": rationale,
        "signal_ids": [row["id"] for row in relevant][:20],
        "cognitive_walkthrough": criteria,
    }


def build_sessions(
    signals: list[dict[str, Any]],
    posture: dict[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for persona in PERSONAS:
        tasks = [
            task_session(persona, task, signals, posture)
            for task in PERSONA_TASKS[persona]
        ]
        counts = Counter(task["outcome"] for task in tasks)
        result.append(
            {
                "persona": persona,
                "classification": CLASSIFICATION,
                "focus": sorted(PERSONA_FOCUS[persona]),
                "tasks": tasks,
                "summary": {
                    "friction_signals": counts["FRICTION_SIGNAL"],
                    "evidence_incomplete": counts["EVIDENCE_INCOMPLETE"],
                    "no_strong_signal": counts["NO_STRONG_SIGNAL"],
                    "not_applicable": counts["NOT_APPLICABLE"],
                },
            }
        )
    return result


def heuristic_review(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, tags in HEURISTICS.items():
        matching = [row for row in signals if tags & set(row.get("tags") or [])]
        if matching:
            state = "REVIEW_SIGNAL"
        else:
            state = "NO_STRONG_SIGNAL"
        rows.append(
            {
                "heuristic": name,
                "state": state,
                "signal_ids": [row["id"] for row in matching][:20],
            }
        )
    return rows


def consensus(
    signals: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings = []
    actions = []
    signal_support: dict[str, set[str]] = defaultdict(set)
    for session in sessions:
        persona = clean(session.get("persona"))
        tasks = session.get("tasks") if isinstance(session.get("tasks"), list) else []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            for signal_id in task.get("signal_ids") or []:
                if isinstance(signal_id, str) and signal_id:
                    signal_support[signal_id].add(persona)

    for signal in signals:
        supporters = [
            persona
            for persona in PERSONAS
            if persona in signal_support.get(signal["id"], set())
        ]
        non_supporters = [persona for persona in PERSONAS if persona not in supporters]
        recurring = len(supporters) >= 2
        severity = clean(signal.get("severity")).upper()
        if recurring and severity in {"HIGH_REVIEW", "REVIEW"}:
            route = "VERIFY_NEXT"
        elif recurring:
            route = "IMPROVE"
        else:
            route = "NO_ACTION"
        row = {
            "signal_id": signal["id"],
            "kind": signal["kind"],
            "subject": signal["subject"],
            "classification": CLASSIFICATION,
            "supporting_personas": supporters,
            "non_supporting_personas": non_supporters,
            "support_count": len(supporters),
            "recurring": recurring,
            "route": route,
            "evidence": {
                "source": signal["source"],
                "refs": signal.get("evidence", []),
                "message": signal.get("message", ""),
            },
        }
        findings.append(row)
        if route != "NO_ACTION":
            actions.append(
                {
                    "route": route,
                    "signal_id": signal["id"],
                    "kind": signal["kind"],
                    "subject": signal["subject"],
                    "basis": (
                        f"{len(supporters)} simulated personas share an evidence-backed "
                        "review concern; technical/product ownership remains external."
                    ),
                    "supporting_personas": supporters,
                }
            )
    findings.sort(
        key=lambda row: (
            0 if row["route"] == "VERIFY_NEXT" else 1 if row["route"] == "IMPROVE" else 2,
            -int(row["support_count"]),
            row["kind"],
            row["subject"],
        )
    )
    actions.sort(key=lambda row: (0 if row["route"] == "VERIFY_NEXT" else 1, row["kind"], row["subject"]))
    return findings, actions


def advisory_state(
    sessions: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> str:
    if actions:
        return "REVIEW_REQUIRED"
    for session in sessions:
        tasks = session.get("tasks") if isinstance(session, dict) and isinstance(session.get("tasks"), list) else []
        if any(
            isinstance(task, dict)
            and clean(task.get("outcome")).upper() == "EVIDENCE_INCOMPLETE"
            for task in tasks
        ):
            return "EVIDENCE_INCOMPLETE"
    return "NO_STRONG_SIGNAL"


def build_report(evidence_dir: Path) -> dict[str, Any]:
    app = load_json(evidence_dir / SOURCE_FILES["app"]) or {}
    journey = load_json(evidence_dir / SOURCE_FILES["journey"]) or {}
    ux = load_json(evidence_dir / SOURCE_FILES["ux"]) or {}
    state = load_json(evidence_dir / SOURCE_FILES["state"]) or {}
    graph = load_json(evidence_dir / SOURCE_FILES["graph"])
    confidence = load_json(evidence_dir / SOURCE_FILES["confidence"]) or {}
    if not graph:
        raise ValueError("evidence-graph.json is required for Simulated Human QA")

    identity = evidence_identity(graph)
    signals = []
    signals.extend(normalized_evidence(SOURCE_FILES["journey"], journey.get("findings")))
    signals.extend(normalized_evidence(SOURCE_FILES["ux"], ux.get("findings")))
    signals.extend(state_signals(state))

    # Deduplicate source-equivalent findings while preserving source provenance.
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in signals:
        key = (row["source"], row["kind"], row["subject"])
        unique.setdefault(key, row)
    signals = sorted(unique.values(), key=lambda row: (row["source"], row["kind"], row["subject"]))

    posture = evidence_posture(app, journey, ux, state)
    sessions = build_sessions(signals, posture)
    heuristics = heuristic_review(signals)
    findings, actions = consensus(signals, sessions)
    state_value = advisory_state(sessions, actions)

    outcome_counts = Counter(
        task["outcome"]
        for session in sessions
        for task in session["tasks"]
    )
    route_counts = Counter(row["route"] for row in actions)
    disagreements = sum(
        1
        for row in findings
        if row["supporting_personas"] and row["non_supporting_personas"]
    )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "record_type": RECORD_TYPE,
        "authority": AUTHORITY,
        "classification": CLASSIFICATION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "state": state_value,
        "personas": sessions,
        "heuristic_review": heuristics,
        "consensus_findings": findings,
        "actions": actions,
        "source_evidence": {
            "files": sorted(
                name for name in SOURCE_FILES.values()
                if (evidence_dir / name).is_file()
            ),
            "signal_count": len(signals),
            "evidence_graph_schema": graph.get("schema_version"),
            "evidence_graph_version": graph.get("graph_version"),
            "confidence_summary": (
                confidence.get("summary")
                if isinstance(confidence.get("summary"), dict)
                else {}
            ),
        },
        "summary": {
            "persona_count": len(sessions),
            "task_count": sum(len(row["tasks"]) for row in sessions),
            "friction_sessions": outcome_counts["FRICTION_SIGNAL"],
            "evidence_incomplete_sessions": outcome_counts["EVIDENCE_INCOMPLETE"],
            "no_strong_signal_sessions": outcome_counts["NO_STRONG_SIGNAL"],
            "not_applicable_sessions": outcome_counts["NOT_APPLICABLE"],
            "consensus_findings": sum(1 for row in findings if row["recurring"]),
            "disagreements": disagreements,
            "verify_next": route_counts["VERIFY_NEXT"],
            "improve": route_counts["IMPROVE"],
        },
        "guardrails": {
            "simulated_review_is_not_real_user_validation": True,
            "simulated_review_is_not_physical_device_evidence": True,
            "simulated_review_has_no_release_verdict": True,
            "simulated_review_cannot_override_technical_gates": True,
            "simulated_review_never_emits_fix_now": True,
            "source_evidence_remains_authoritative": True,
            "missing_evidence_does_not_become_user_failure": True,
            "no_numeric_persona_or_ux_score": True,
            "deterministic_core_no_llm_required": True,
        },
        "record_digest_sha256": "",
    }
    report["record_digest_sha256"] = report_digest(report)
    return report


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    identity = report["identity"]
    lines = [
        "# AppLab v5.0 — Simulated Human QA",
        "",
        f"- Classification: **{CLASSIFICATION}**",
        f"- Advisory state: **{report['state']}**",
        f"- Project: **{identity['repository']}@{identity['resolved_sha']}**",
        f"- Package: **{identity['package_id']}** · {identity['version_name']} ({identity['version_code']})",
        f"- APK SHA-256: **{identity['artifact_sha256']}**",
        f"- Personas: **{summary['persona_count']}**",
        f"- Tasks: **{summary['task_count']}**",
        f"- Friction / incomplete: **{summary['friction_sessions']} / {summary['evidence_incomplete_sessions']}**",
        f"- VERIFY_NEXT / IMPROVE: **{summary['verify_next']} / {summary['improve']}**",
        "",
        "## Persona sessions",
        "",
    ]
    for session in report["personas"]:
        s = session["summary"]
        lines.append(
            f"- **{session['persona']}** — friction {s['friction_signals']} · "
            f"incomplete {s['evidence_incomplete']} · no strong signal {s['no_strong_signal']}"
        )
    lines.extend(["", "## Advisory actions", ""])
    if report["actions"]:
        for row in report["actions"][:30]:
            lines.append(
                f"- **{row['route']} / {row['kind']}** · {row['subject']} — "
                + ", ".join(row["supporting_personas"])
            )
    else:
        lines.append("- None.")
    lines.extend([
        "",
        "## Authority boundary",
        "",
        "- This is simulated-user review evidence, not real-user validation.",
        "- It does not replace trusted runtime, physical-device evidence or certification.",
        "- It cannot emit FIX_NOW or alter deterministic release gates.",
        "",
    ])
    return "\n".join(lines)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        graph = {
            "schema_version": 2,
            "graph_version": "2.0",
            "identity": {
                "repository": "owner/demo",
                "resolved_sha": "a" * 40,
                "run_id": "123",
                "package_id": "com.example.demo",
            },
            "root_nodes": {"build_artifact": "artifact:demo"},
            "nodes": [
                {
                    "id": "artifact:demo",
                    "type": "BuildArtifact",
                    "attributes": {
                        "package_id": "com.example.demo",
                        "apk_sha256": "b" * 64,
                        "version_name": "1.0.0",
                        "version_code": "1",
                    },
                }
            ],
        }
        (root / SOURCE_FILES["graph"]).write_text(json.dumps(graph), encoding="utf-8")
        (root / SOURCE_FILES["app"]).write_text(json.dumps({
            "product": {
                "feature_signals": [
                    {"label": "network_api", "status": "PRESENT"},
                    {"label": "authentication", "status": "PRESENT"},
                ]
            }
        }), encoding="utf-8")
        (root / SOURCE_FILES["journey"]).write_text(json.dumps({
            "summary": {"journeys_observed": 2},
            "findings": [
                {
                    "kind": "SAFE_DEAD_END_CANDIDATE",
                    "severity": "REVIEW",
                    "subject": "profile",
                    "message": "Observed bounded path ends without a safe next action.",
                    "evidence": ["journey/profile.xml"],
                }
            ],
        }), encoding="utf-8")
        (root / SOURCE_FILES["ux"]).write_text(json.dumps({
            "findings": [
                {
                    "kind": "STABLE_SIGNATURE_AFTER_ACTION_CANDIDATE",
                    "category": "feedback",
                    "severity": "REVIEW",
                    "subject": "Search",
                    "message": "Action produced a stable signature.",
                    "evidence": ["after.xml"],
                }
            ]
        }), encoding="utf-8")
        (root / SOURCE_FILES["state"]).write_text(json.dumps({
            "states": {
                "offline": {"applicability": "APPLICABLE", "status": "NOT_OBSERVED"},
                "auth": {"applicability": "APPLICABLE", "status": "OBSERVED"},
                "camera": {"applicability": "NOT_APPLICABLE", "status": "NOT_OBSERVED"},
            },
            "findings": [],
        }), encoding="utf-8")

        report = build_report(root)
        assert report["classification"] == CLASSIFICATION
        assert report["state"] == "REVIEW_REQUIRED"
        assert [row["persona"] for row in report["personas"]] == list(PERSONAS)
        assert report["summary"]["persona_count"] == 7
        assert report["summary"]["task_count"] == 14
        assert report["summary"]["verify_next"] > 0
        assert not any(row["subject"] == "camera" for row in report["consensus_findings"])
        assert all(
            row["support_count"] == len(row["supporting_personas"])
            for row in report["consensus_findings"]
        )
        assert all(row["route"] in ALLOWED_ROUTES for row in report["actions"])
        assert all(row["route"] != "FIX_NOW" for row in report["actions"])
        assert report["guardrails"]["simulated_review_is_not_real_user_validation"] is True
        assert report["record_digest_sha256"] == report_digest(report)
        assert report["identity"]["artifact_sha256"] == "b" * 64
        assert "storage" not in tags_for_text("profile")
        assert "auth" not in tags_for_text("authoritative")
        assert "auth" in tags_for_text("auth failure")

        stale_graph = json.loads(json.dumps(graph))
        stale_graph["nodes"][0]["attributes"]["package_id"] = "com.example.other"
        (root / SOURCE_FILES["graph"]).write_text(json.dumps(stale_graph), encoding="utf-8")
        try:
            build_report(root)
        except ValueError as exc:
            assert "package identity is inconsistent" in str(exc)
        else:
            raise AssertionError("stale Evidence Graph artifact identity must fail closed")
        (root / SOURCE_FILES["graph"]).write_text(json.dumps(graph), encoding="utf-8")

        empty = Path(raw) / "empty"
        empty.mkdir()
        (empty / SOURCE_FILES["graph"]).write_text((root / SOURCE_FILES["graph"]).read_text(encoding="utf-8"), encoding="utf-8")
        empty_report = build_report(empty)
        assert empty_report["state"] == "EVIDENCE_INCOMPLETE"
        assert empty_report["summary"]["verify_next"] == 0

        out = Path(raw) / "out"
        write_report(out, "simulated-human-qa", report, markdown(report))
        assert (out / "simulated-human-qa.json").is_file()
        assert CLASSIFICATION in (out / "simulated-human-qa.md").read_text(encoding="utf-8")

    print("AppLab v5.0 Simulated Human QA self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.evidence_dir:
        parser.error("--evidence-dir is required unless --self-test is used")
    evidence_dir = Path(args.evidence_dir)
    output_dir = Path(args.output_dir) if args.output_dir else evidence_dir
    report = build_report(evidence_dir)
    write_report(output_dir, "simulated-human-qa", report, markdown(report))
    print(json.dumps({
        "lab_version": LAB_VERSION,
        "state": report["state"],
        **report["summary"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, AssertionError) as exc:
        raise SystemExit(f"AppLab Simulated Human QA failed: {exc}") from exc
