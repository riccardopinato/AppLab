#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from product_review_common import write_report

SCHEMA_VERSION = 1
ENGINE_VERSION = "4.2.0"
GRAPH_VERSION = "1.0"

FILES = {
    "app": "app-intelligence.json",
    "confidence": "evidence-confidence.json",
    "journey": "user-journey.json",
    "ux": "ux-friction.json",
    "longitudinal": "longitudinal-intelligence.json",
    "experiment": "experiment-plan.json",
    "analyst": "analyst-report.json",
    "autonomous": "autonomous-review.json",
}

NODE_TYPES = (
    "Project",
    "Revision",
    "BuildArtifact",
    "Capability",
    "Surface",
    "Journey",
    "Finding",
    "Claim",
    "Evidence",
    "Experiment",
    "Result",
)


def _safe(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.:/-]+", "-", _safe(value).lower()).strip("-")


def _stable(prefix: str, *parts: Any) -> str:
    raw = "|".join(_safe(value) for value in parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(raw).hexdigest()[:16]}"


def _canonical_sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_inputs(evidence_dir: Path, trusted_runtime_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, filename in FILES.items():
        payload = read_json(evidence_dir / filename)
        if payload is not None:
            result[key] = payload

    if trusted_runtime_dir and trusted_runtime_dir.is_dir():
        for key, filename in (
            ("trusted_manifest", "trusted-evidence-manifest.json"),
            ("build_contract", "build-contract.json"),
            ("trusted_result", "result.json"),
        ):
            payload = read_json(trusted_runtime_dir / filename)
            if payload is not None:
                result[key] = payload
    return result


def _version(payload: dict[str, Any]) -> str:
    for key in (
        "platform_version",
        "engine_version",
        "lab_version",
        "studio_version",
        "applab_version",
        "manifest_version",
    ):
        value = _safe(payload.get(key))
        if value:
            return value
    return ""


def _scalars(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in keys:
        value = row.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
    return result


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.subject_index: dict[str, list[str]] = {}

    def add_node(
        self,
        node_type: str,
        key: str,
        label: str,
        *,
        attributes: dict[str, Any] | None = None,
        provenance: list[str] | None = None,
        preferred_id: str = "",
    ) -> str:
        if node_type not in NODE_TYPES:
            raise ValueError(f"Unsupported Evidence Graph node type: {node_type}")
        node_id = preferred_id or _stable(node_type, key)
        row = {
            "id": node_id,
            "type": node_type,
            "key": key,
            "label": label or key,
            "attributes": attributes or {},
            "provenance": sorted(set(provenance or [])),
        }
        existing = self.nodes.get(node_id)
        if existing:
            existing["provenance"] = sorted(
                set(existing.get("provenance", [])) | set(row["provenance"])
            )
            merged = dict(existing.get("attributes", {}))
            for attr, value in row["attributes"].items():
                if value not in ("", None, [], {}):
                    merged[attr] = value
            existing["attributes"] = merged
            if not existing.get("label") and row["label"]:
                existing["label"] = row["label"]
        else:
            self.nodes[node_id] = row

        for token in {_norm(key), _norm(label)}:
            if token:
                self.subject_index.setdefault(token, [])
                if node_id not in self.subject_index[token]:
                    self.subject_index[token].append(node_id)
        return node_id

    def add_edge(
        self,
        relation: str,
        source: str,
        target: str,
        *,
        attributes: dict[str, Any] | None = None,
        provenance: list[str] | None = None,
    ) -> str:
        if source not in self.nodes or target not in self.nodes:
            raise ValueError(f"Evidence Graph edge references unknown node: {source} -> {target}")
        edge_id = _stable("Edge", relation, source, target)
        self.edges[edge_id] = {
            "id": edge_id,
            "type": relation,
            "from": source,
            "to": target,
            "attributes": attributes or {},
            "provenance": sorted(set(provenance or [])),
        }
        return edge_id

    def match_subject(self, subject: Any, allowed: tuple[str, ...] = ()) -> str | None:
        token = _norm(subject)
        if not token:
            return None
        exact = self.subject_index.get(token, [])
        for node_id in exact:
            if not allowed or self.nodes[node_id]["type"] in allowed:
                return node_id

        for indexed, node_ids in self.subject_index.items():
            if not indexed or (token not in indexed and indexed not in token):
                continue
            for node_id in node_ids:
                if not allowed or self.nodes[node_id]["type"] in allowed:
                    return node_id
        return None

    def sorted_nodes(self) -> list[dict[str, Any]]:
        return sorted(
            self.nodes.values(),
            key=lambda row: (str(row["type"]), str(row["key"]), str(row["id"])),
        )

    def sorted_edges(self) -> list[dict[str, Any]]:
        return sorted(
            self.edges.values(),
            key=lambda row: (
                str(row["type"]),
                str(row["from"]),
                str(row["to"]),
                str(row["id"]),
            ),
        )


def _report_evidence_nodes(builder: GraphBuilder, inputs: dict[str, dict[str, Any]]) -> dict[str, str]:
    report_nodes: dict[str, str] = {}
    for key, payload in sorted(inputs.items()):
        filename = FILES.get(key)
        if not filename:
            filename = {
                "trusted_manifest": "trusted-evidence-manifest.json",
                "build_contract": "build-contract.json",
                "trusted_result": "result.json",
            }.get(key, key + ".json")
        report_nodes[key] = builder.add_node(
            "Evidence",
            f"report:{filename}",
            filename,
            attributes={
                "kind": "REPORT",
                "schema_version": payload.get("schema_version"),
                "version": _version(payload),
                "content_sha256": _canonical_sha(payload),
            },
            provenance=[filename],
        )
    return report_nodes


def _reference_evidence(
    builder: GraphBuilder,
    value: Any,
    *,
    source_file: str,
    report_node: str | None,
) -> str | None:
    text = _safe(value)
    if not text:
        return None
    node_id = builder.add_node(
        "Evidence",
        f"reference:{text}",
        text,
        attributes={"kind": "REFERENCE"},
        provenance=[source_file],
    )
    if report_node:
        builder.add_edge(
            "CONTAINED_IN_REPORT",
            node_id,
            report_node,
            provenance=[source_file],
        )
    return node_id


def _identity(inputs: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[str, Any]]:
    autonomous = inputs.get("autonomous", {})
    trust = autonomous.get("runtime_evidence_trust")
    trust = trust if isinstance(trust, dict) else {}
    binding = trust.get("binding")
    binding = binding if isinstance(binding, dict) else {}

    manifest = inputs.get("trusted_manifest", {})
    manifest_binding = manifest.get("binding")
    manifest_binding = manifest_binding if isinstance(manifest_binding, dict) else {}

    longitudinal = inputs.get("longitudinal", {})
    current = longitudinal.get("current")
    current = current if isinstance(current, dict) else {}

    repository = (
        _safe(binding.get("repository"))
        or _safe(manifest_binding.get("repository"))
        or _safe(current.get("repository"))
        or "unknown/unknown"
    )
    resolved_sha = (
        _safe(binding.get("resolved_sha"))
        or _safe(manifest_binding.get("resolved_sha"))
        or _safe(current.get("resolved_sha"))
    ).lower()
    run_id = (
        _safe(binding.get("workflow_run_id"))
        or _safe(manifest_binding.get("workflow_run_id"))
        or _safe(current.get("run_id"))
    )
    package_id = _safe(binding.get("package_id")) or _safe(manifest_binding.get("package_id"))
    lineage_ref = _safe(current.get("lineage_ref"))
    base_sha = _safe(current.get("base_sha")).lower()

    return (
        {
            "repository": repository,
            "resolved_sha": resolved_sha,
            "run_id": run_id,
            "package_id": package_id,
            "lineage_ref": lineage_ref,
            "base_sha": base_sha,
        },
        trust,
    )


def _add_core(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
) -> tuple[str, str, str | None]:
    identity, trust = _identity(inputs)
    repository = identity["repository"]
    sha = identity["resolved_sha"] or "unknown"
    project = builder.add_node(
        "Project",
        repository,
        repository,
        attributes={"repository": repository},
        provenance=[FILES["autonomous"]] if "autonomous" in inputs else [],
    )
    revision = builder.add_node(
        "Revision",
        f"{repository}@{sha}",
        sha[:12] if sha != "unknown" else "unknown revision",
        attributes={
            "repository": repository,
            "resolved_sha": identity["resolved_sha"],
            "workflow_run_id": identity["run_id"],
            "lineage_ref": identity["lineage_ref"],
            "base_sha": identity["base_sha"],
        },
        provenance=(
            ([FILES["autonomous"]] if "autonomous" in inputs else [])
            + ([FILES["longitudinal"]] if "longitudinal" in inputs else [])
            + (["trusted-evidence-manifest.json"] if "trusted_manifest" in inputs else [])
        ),
    )
    builder.add_edge("PROJECT_HAS_REVISION", project, revision)

    baseline = inputs.get("longitudinal", {}).get("baseline")
    if isinstance(baseline, dict) and bool(baseline.get("available")):
        baseline_sha = _safe(baseline.get("resolved_sha")).lower()
        if baseline_sha:
            baseline_revision = builder.add_node(
                "Revision",
                f"{repository}@{baseline_sha}",
                baseline_sha[:12],
                attributes={
                    "repository": repository,
                    "resolved_sha": baseline_sha,
                    "workflow_run_id": _safe(baseline.get("run_id")),
                    "lineage_ref": _safe(baseline.get("lineage_ref")),
                    "recorded_at": _safe(baseline.get("recorded_at")),
                },
                provenance=[FILES["longitudinal"]],
            )
            builder.add_edge("PROJECT_HAS_REVISION", project, baseline_revision)
            builder.add_edge(
                "REVISION_COMPARED_TO",
                revision,
                baseline_revision,
                provenance=[FILES["longitudinal"]],
            )

    contract = inputs.get("build_contract", {})
    apk = contract.get("apk") if isinstance(contract.get("apk"), dict) else {}
    artifact: str | None = None
    package_id = _safe(apk.get("package_id")) or identity["package_id"]
    apk_sha256 = _safe(apk.get("sha256"))
    if contract:
        artifact_key = apk_sha256 or f"{repository}@{sha}:{package_id}"
        artifact = builder.add_node(
            "BuildArtifact",
            artifact_key,
            package_id or "build artifact",
            attributes={
                "package_id": package_id,
                "apk_sha256": apk_sha256,
                "size_bytes": int(apk.get("size_bytes", 0) or 0),
                "version_name": _safe(apk.get("version_name")),
                "version_code": _safe(apk.get("version_code")),
                "build_variant": _safe(apk.get("build_variant")),
                "signing_cert_sha256": _safe(apk.get("signing_cert_sha256")),
                "trusted_applab_sha": _safe(contract.get("trusted_applab_sha")),
                "manifest_sha256": _safe(trust.get("manifest_sha256")),
            },
            provenance=(
                ["build-contract.json"]
                + ([FILES["autonomous"]] if "autonomous" in inputs else [])
                + (["trusted-evidence-manifest.json"] if "trusted_manifest" in inputs else [])
            ),
        )
        builder.add_edge("REVISION_BUILT_AS", revision, artifact)

    return project, revision, artifact


def _add_capabilities(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
    revision: str,
) -> None:
    app = inputs.get("app", {})
    truth = app.get("feature_truth") if isinstance(app.get("feature_truth"), dict) else {}
    rows = truth.get("capabilities") if isinstance(truth.get("capabilities"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        capability = _safe(row.get("capability"))
        if not capability:
            continue
        node = builder.add_node(
            "Capability",
            capability,
            capability,
            attributes={
                "truth": _safe(row.get("truth")) or "NOT_DETECTED",
                "provenance": row.get("provenance", {}) if isinstance(row.get("provenance"), dict) else {},
            },
            provenance=[FILES["app"]],
        )
        builder.add_edge("REVISION_HAS_CAPABILITY", revision, node, provenance=[FILES["app"]])
        if "app" in reports:
            builder.add_edge("DERIVED_FROM", node, reports["app"], provenance=[FILES["app"]])


def _add_surfaces(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
    revision: str,
) -> None:
    app = inputs.get("app", {})
    flow = app.get("product_flow_graph") if isinstance(app.get("product_flow_graph"), dict) else {}
    rows = flow.get("nodes") if isinstance(flow.get("nodes"), list) else []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        surface = _safe(row.get("id")) or _safe(row.get("name")) or f"surface-{index}"
        node = builder.add_node(
            "Surface",
            surface,
            _safe(row.get("label")) or _safe(row.get("name")) or surface,
            attributes=_scalars(
                row,
                (
                    "id",
                    "name",
                    "label",
                    "role",
                    "route",
                    "path",
                    "source",
                    "kind",
                ),
            ),
            provenance=[FILES["app"]],
        )
        builder.add_edge("REVISION_HAS_SURFACE", revision, node, provenance=[FILES["app"]])
        if "app" in reports:
            builder.add_edge("DERIVED_FROM", node, reports["app"], provenance=[FILES["app"]])


def _add_journeys(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
    revision: str,
) -> None:
    journey = inputs.get("journey", {})
    rows = journey.get("journeys") if isinstance(journey.get("journeys"), list) else []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        steps = row.get("steps") if isinstance(row.get("steps"), list) else []
        key = _safe(row.get("id")) or "|".join(_safe(x) for x in steps) or f"journey-{index}"
        node = builder.add_node(
            "Journey",
            key,
            _safe(row.get("name")) or f"Journey {index + 1}",
            attributes={
                **_scalars(row, ("id", "name", "depth", "status", "start_state", "end_state")),
                "steps": [_safe(x) for x in steps[:20]],
            },
            provenance=[FILES["journey"]],
        )
        builder.add_edge("REVISION_OBSERVED_JOURNEY", revision, node, provenance=[FILES["journey"]])
        if "journey" in reports:
            builder.add_edge("DERIVED_FROM", node, reports["journey"], provenance=[FILES["journey"]])


def _finding_history(inputs: dict[str, dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    longitudinal = inputs.get("longitudinal", {})
    findings = longitudinal.get("findings") if isinstance(longitudinal.get("findings"), dict) else {}
    rows = findings.get("history") if isinstance(findings.get("history"), list) else []
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (_norm(row.get("kind")), _norm(row.get("subject")))
        if key != ("", ""):
            result[key] = row
    return result


def _add_finding_rows(
    builder: GraphBuilder,
    rows: Any,
    *,
    source_file: str,
    source_key: str,
    report_node: str | None,
    revision: str,
    history: dict[tuple[str, str], dict[str, Any]],
) -> None:
    if not isinstance(rows, list):
        return
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        kind = _safe(row.get("kind")) or _safe(row.get("category")) or "FINDING"
        subject = _safe(row.get("subject")) or _safe(row.get("id")) or f"{source_key}-{index}"
        message = _safe(row.get("message")) or _safe(row.get("reason"))
        original_id = _safe(row.get("id"))
        hist = history.get((_norm(kind), _norm(subject)), {})
        attrs = {
            **_scalars(
                row,
                (
                    "id",
                    "domain",
                    "category",
                    "kind",
                    "severity",
                    "subject",
                    "message",
                    "reason",
                    "source",
                    "status",
                    "before_severity",
                    "after_severity",
                ),
            ),
            "source_file": source_file,
            "first_observed_sha": _safe(hist.get("first_seen_sha")),
            "last_observed_sha": _safe(hist.get("last_seen_sha")),
            "seen_count": int(hist.get("seen_count", 0) or 0),
            "consecutive_seen": int(hist.get("consecutive_seen", 0) or 0),
        }
        canonical_history_key = _safe(hist.get("key")) or _safe(hist.get("id")) or _safe(row.get("key"))
        key = canonical_history_key or original_id or f"{source_key}:{kind}:{subject}"
        node = builder.add_node(
            "Finding",
            key,
            f"{kind}: {subject}",
            attributes=attrs,
            provenance=[source_file],
        )
        builder.add_edge("REVISION_HAS_FINDING", revision, node, provenance=[source_file])
        if report_node:
            builder.add_edge("DERIVED_FROM", node, report_node, provenance=[source_file])

        target = builder.match_subject(subject, ("Capability", "Surface"))
        if target:
            builder.add_edge("FINDING_ABOUT", node, target, provenance=[source_file])

        evidence_values = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        for value in evidence_values[:16]:
            evidence_node = _reference_evidence(
                builder,
                value,
                source_file=source_file,
                report_node=report_node,
            )
            if evidence_node:
                builder.add_edge("FINDING_SUPPORTED_BY", node, evidence_node, provenance=[source_file])


def _add_findings(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
    revision: str,
) -> None:
    history = _finding_history(inputs)

    app = inputs.get("app", {})
    consistency = app.get("product_consistency") if isinstance(app.get("product_consistency"), dict) else {}
    _add_finding_rows(
        builder,
        consistency.get("findings"),
        source_file=FILES["app"],
        source_key="product_consistency",
        report_node=reports.get("app"),
        revision=revision,
        history=history,
    )

    _add_finding_rows(
        builder,
        inputs.get("journey", {}).get("findings"),
        source_file=FILES["journey"],
        source_key="journey",
        report_node=reports.get("journey"),
        revision=revision,
        history=history,
    )
    _add_finding_rows(
        builder,
        inputs.get("ux", {}).get("findings"),
        source_file=FILES["ux"],
        source_key="ux",
        report_node=reports.get("ux"),
        revision=revision,
        history=history,
    )
    _add_finding_rows(
        builder,
        inputs.get("confidence", {}).get("contradictions"),
        source_file=FILES["confidence"],
        source_key="contradiction",
        report_node=reports.get("confidence"),
        revision=revision,
        history=history,
    )
    _add_finding_rows(
        builder,
        inputs.get("longitudinal", {}).get("regression_candidates"),
        source_file=FILES["longitudinal"],
        source_key="regression",
        report_node=reports.get("longitudinal"),
        revision=revision,
        history=history,
    )


def _add_claims(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
    revision: str,
) -> None:
    confidence = inputs.get("confidence", {})
    rows = confidence.get("claims") if isinstance(confidence.get("claims"), list) else []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        source_id = _safe(row.get("id")) or f"claim-{index}"
        subject = _safe(row.get("subject")) or source_id
        node = builder.add_node(
            "Claim",
            source_id,
            subject,
            attributes={
                **_scalars(
                    row,
                    (
                        "id",
                        "domain",
                        "subject",
                        "proposition",
                        "status",
                        "rationale",
                        "source_sha",
                        "current_sha",
                    ),
                ),
                "sources": [
                    _safe(x) for x in row.get("sources", [])[:16]
                ] if isinstance(row.get("sources"), list) else [],
            },
            provenance=[FILES["confidence"]],
        )
        builder.add_edge("REVISION_HAS_CLAIM", revision, node, provenance=[FILES["confidence"]])
        if "confidence" in reports:
            builder.add_edge("DERIVED_FROM", node, reports["confidence"], provenance=[FILES["confidence"]])

        target = builder.match_subject(subject, ("Capability", "Surface", "Finding"))
        if target:
            builder.add_edge("CLAIM_ABOUT", node, target, provenance=[FILES["confidence"]])

        values = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        for value in values[:16]:
            evidence_node = _reference_evidence(
                builder,
                value,
                source_file=FILES["confidence"],
                report_node=reports.get("confidence"),
            )
            if evidence_node:
                builder.add_edge("CLAIM_SUPPORTED_BY", node, evidence_node, provenance=[FILES["confidence"]])


def _add_experiments(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
    revision: str,
) -> None:
    plan = inputs.get("experiment", {})
    rows = plan.get("experiments") if isinstance(plan.get("experiments"), list) else []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        source_id = _safe(row.get("id")) or f"experiment-{index}"
        subject = _safe(row.get("subject"))
        node = builder.add_node(
            "Experiment",
            source_id,
            subject or source_id,
            attributes={
                **_scalars(
                    row,
                    (
                        "id",
                        "source",
                        "priority",
                        "kind",
                        "subject",
                        "reason",
                        "hypothesis",
                        "experiment_type",
                    ),
                ),
                "labs": [
                    _safe(x) for x in row.get("labs", [])[:12]
                ] if isinstance(row.get("labs"), list) else [],
                "triggers": [
                    _safe(x) for x in row.get("triggers", [])[:12]
                ] if isinstance(row.get("triggers"), list) else [],
            },
            provenance=[FILES["experiment"]],
        )
        builder.add_edge("REVISION_PLANS_EXPERIMENT", revision, node, provenance=[FILES["experiment"]])
        if "experiment" in reports:
            builder.add_edge("DERIVED_FROM", node, reports["experiment"], provenance=[FILES["experiment"]])

        target = builder.match_subject(subject, ("Finding", "Claim", "Capability", "Surface"))
        if target:
            builder.add_edge("EXPERIMENT_TARGETS", node, target, provenance=[FILES["experiment"]])

        values = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        for value in values[:16]:
            evidence_node = _reference_evidence(
                builder,
                value,
                source_file=FILES["experiment"],
                report_node=reports.get("experiment"),
            )
            if evidence_node:
                builder.add_edge("EXPERIMENT_USES_EVIDENCE", node, evidence_node, provenance=[FILES["experiment"]])


def _add_results(
    builder: GraphBuilder,
    inputs: dict[str, dict[str, Any]],
    reports: dict[str, str],
    revision: str,
) -> None:
    analyst = inputs.get("analyst", {})
    if analyst:
        summary = analyst.get("summary") if isinstance(analyst.get("summary"), dict) else {}
        node = builder.add_node(
            "Result",
            "analyst",
            "AppLab Analyst",
            attributes={
                "state": _safe(analyst.get("state")),
                "headline": _safe(analyst.get("headline")),
                "observations": int(summary.get("observations", 0) or 0),
                "next_actions": int(summary.get("next_actions", 0) or 0),
                "contradictions": int(summary.get("contradictions", 0) or 0),
                "regression_candidates": int(summary.get("regression_candidates", 0) or 0),
            },
            provenance=[FILES["analyst"]],
        )
        builder.add_edge("REVISION_HAS_RESULT", revision, node, provenance=[FILES["analyst"]])
        if "analyst" in reports:
            builder.add_edge("DERIVED_FROM", node, reports["analyst"], provenance=[FILES["analyst"]])

    longitudinal = inputs.get("longitudinal", {})
    if longitudinal:
        summary = longitudinal.get("summary") if isinstance(longitudinal.get("summary"), dict) else {}
        node = builder.add_node(
            "Result",
            "longitudinal",
            "Longitudinal Product Intelligence",
            attributes={
                "state": _safe(longitudinal.get("state")),
                "history_snapshots": int(summary.get("history_snapshots", 0) or 0),
                "new_findings": int(summary.get("new_findings", 0) or 0),
                "returned_findings": int(summary.get("returned_findings", 0) or 0),
                "persistent_findings": int(summary.get("persistent_findings", 0) or 0),
                "regression_candidates": int(summary.get("regression_candidates", 0) or 0),
            },
            provenance=[FILES["longitudinal"]],
        )
        builder.add_edge("REVISION_HAS_RESULT", revision, node, provenance=[FILES["longitudinal"]])
        if "longitudinal" in reports:
            builder.add_edge("DERIVED_FROM", node, reports["longitudinal"], provenance=[FILES["longitudinal"]])


def _summary(builder: GraphBuilder, inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["type"]) for row in builder.nodes.values())
    relation_counts = Counter(str(row["type"]) for row in builder.edges.values())

    unverified_capabilities: list[dict[str, Any]] = []
    confidence = inputs.get("confidence", {})
    claims = confidence.get("claims") if isinstance(confidence.get("claims"), list) else []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if _safe(claim.get("domain")) != "capability":
            continue
        if _safe(claim.get("status")) in {"CONFIRMED", "CORROBORATED"}:
            continue
        unverified_capabilities.append(
            {
                "claim_id": _safe(claim.get("id")),
                "capability": _safe(claim.get("subject")),
                "status": _safe(claim.get("status")) or "UNVERIFIED",
                "rationale": _safe(claim.get("rationale")),
            }
        )

    recurring_findings: list[dict[str, Any]] = []
    longitudinal = inputs.get("longitudinal", {})
    findings = longitudinal.get("findings") if isinstance(longitudinal.get("findings"), dict) else {}
    history = findings.get("history") if isinstance(findings.get("history"), list) else []
    for row in history:
        if not isinstance(row, dict):
            continue
        seen_count = int(row.get("seen_count", 0) or 0)
        if seen_count < 2:
            continue
        recurring_findings.append(
            {
                "kind": _safe(row.get("kind")),
                "subject": _safe(row.get("subject")),
                "seen_count": seen_count,
                "consecutive_seen": int(row.get("consecutive_seen", 0) or 0),
                "first_observed_sha": _safe(row.get("first_seen_sha")),
                "last_observed_sha": _safe(row.get("last_seen_sha")),
            }
        )

    regressions = longitudinal.get("regression_candidates")
    regressions = regressions if isinstance(regressions, list) else []

    return {
        "nodes": len(builder.nodes),
        "edges": len(builder.edges),
        "nodes_by_type": {key: counts.get(key, 0) for key in NODE_TYPES},
        "relations_by_type": dict(sorted(relation_counts.items())),
        "unverified_capabilities": len(unverified_capabilities),
        "recurring_findings": len(recurring_findings),
        "regression_candidates": len([row for row in regressions if isinstance(row, dict)]),
    }, {
        "unverified_capabilities": sorted(
            unverified_capabilities,
            key=lambda row: (row["status"], row["capability"]),
        ),
        "recurring_findings": sorted(
            recurring_findings,
            key=lambda row: (-row["seen_count"], row["kind"], row["subject"]),
        ),
        "regression_candidates": [
            {
                "kind": _safe(row.get("kind")),
                "subject": _safe(row.get("subject")),
                "reason": _safe(row.get("reason")),
                "source": _safe(row.get("source")),
            }
            for row in regressions
            if isinstance(row, dict)
        ],
    }


def build_graph(
    inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    builder = GraphBuilder()
    reports = _report_evidence_nodes(builder, inputs)
    project, revision, artifact = _add_core(builder, inputs, reports)
    _add_capabilities(builder, inputs, reports, revision)
    _add_surfaces(builder, inputs, reports, revision)
    _add_journeys(builder, inputs, reports, revision)
    _add_findings(builder, inputs, reports, revision)
    _add_claims(builder, inputs, reports, revision)
    _add_experiments(builder, inputs, reports, revision)
    _add_results(builder, inputs, reports, revision)

    summary, insights = _summary(builder, inputs)
    identity, _ = _identity(inputs)
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "graph_version": GRAPH_VERSION,
        "identity": identity,
        "root_nodes": {
            "project": project,
            "revision": revision,
            "build_artifact": artifact,
        },
        "summary": summary,
        "insights": insights,
        "nodes": builder.sorted_nodes(),
        "edges": builder.sorted_edges(),
        "guardrails": {
            "deterministic_derivation_only": True,
            "source_reports_remain_authoritative": True,
            "graph_does_not_change_fast_full_certification": True,
            "missing_evidence_never_becomes_pass": True,
            "first_observed_sha_is_not_proof_of_introducing_commit": True,
            "regression_candidate_is_not_automatic_defect": True,
            "no_numeric_product_quality_score": True,
            "trusted_runtime_boundary_unchanged": True,
        },
    }


def _index_graph(graph: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    by_id = {
        _safe(row.get("id")): row
        for row in nodes
        if isinstance(row, dict) and _safe(row.get("id"))
    }
    return by_id, [row for row in edges if isinstance(row, dict)]


def query_graph(graph: dict[str, Any], query: str, subject: str = "") -> dict[str, Any]:
    by_id, edges = _index_graph(graph)
    query = _safe(query).lower()

    if query == "unverified-capabilities":
        return {
            "query": query,
            "results": (graph.get("insights") or {}).get("unverified_capabilities", []),
        }
    if query == "recurring-findings":
        return {
            "query": query,
            "results": (graph.get("insights") or {}).get("recurring_findings", []),
        }
    if query == "regressions":
        return {
            "query": query,
            "results": (graph.get("insights") or {}).get("regression_candidates", []),
        }

    token = _norm(subject)
    matched = [
        row
        for row in by_id.values()
        if token
        and (
            token == _norm(row.get("key"))
            or token == _norm(row.get("label"))
            or token in _norm(row.get("key"))
            or token in _norm(row.get("label"))
        )
    ]

    if query == "history":
        results = []
        for row in matched:
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            if row.get("type") != "Finding":
                continue
            results.append(
                {
                    "id": row.get("id"),
                    "kind": attrs.get("kind"),
                    "subject": attrs.get("subject"),
                    "first_observed_sha": attrs.get("first_observed_sha"),
                    "last_observed_sha": attrs.get("last_observed_sha"),
                    "seen_count": attrs.get("seen_count", 0),
                    "consecutive_seen": attrs.get("consecutive_seen", 0),
                    "caveat": "first_observed_sha is evidence of first observation, not proof of the code-introducing commit",
                }
            )
        return {"query": query, "subject": subject, "results": results}

    if query == "evidence":
        matched_ids = {str(row.get("id")) for row in matched}
        evidence_ids: set[str] = set()
        relations = []
        for edge in edges:
            source = _safe(edge.get("from"))
            target = _safe(edge.get("to"))
            if source in matched_ids or target in matched_ids:
                relations.append(edge)
                other = target if source in matched_ids else source
                if by_id.get(other, {}).get("type") == "Evidence":
                    evidence_ids.add(other)
        return {
            "query": query,
            "subject": subject,
            "matched_nodes": matched,
            "evidence": [by_id[node_id] for node_id in sorted(evidence_ids)],
            "relations": relations,
        }

    raise ValueError(
        "Unsupported query. Use one of: unverified-capabilities, recurring-findings, "
        "regressions, history, evidence"
    )


def markdown(graph: dict[str, Any]) -> str:
    summary = graph["summary"]
    identity = graph["identity"]
    lines = [
        "# AppLab v4.2 — Evidence Graph",
        "",
        f"- Project: **{identity.get('repository') or 'unknown'}**",
        f"- Revision: **{identity.get('resolved_sha') or 'unknown'}**",
        f"- Nodes: **{summary['nodes']}**",
        f"- Edges: **{summary['edges']}**",
        f"- Unverified capabilities: **{summary['unverified_capabilities']}**",
        f"- Recurring findings: **{summary['recurring_findings']}**",
        f"- Regression candidates: **{summary['regression_candidates']}**",
        "",
        "## Node model",
        "",
    ]
    for node_type in NODE_TYPES:
        lines.append(f"- {node_type}: **{summary['nodes_by_type'].get(node_type, 0)}**")
    lines.extend(["", "## Guardrails", ""])
    lines.append(
        "- The graph is a deterministic query/index layer. Source reports remain authoritative."
    )
    lines.append(
        "- A first-observed SHA is not proof that the commit introduced the behavior."
    )
    lines.append(
        "- Evidence Graph does not alter FAST/FULL/CERTIFICATION or trusted-runtime authority."
    )
    return "\n".join(lines)


def write_outputs(graph: dict[str, Any], output_dir: Path) -> None:
    write_report(output_dir, "evidence-graph", graph, markdown(graph))


def self_test() -> None:
    sha1 = "1" * 40
    sha2 = "2" * 40
    evidence = {
        "app": {
            "schema_version": 1,
            "feature_truth": {
                "capabilities": [
                    {"capability": "auth", "truth": "CODE_CONFIRMED", "provenance": {"code": ["lib/auth.dart"]}},
                    {"capability": "backup", "truth": "DOC_ONLY_SIGNAL", "provenance": {"docs": ["README.md"]}},
                ]
            },
            "product_flow_graph": {
                "nodes": [{"id": "home", "role": "home"}, {"id": "settings", "role": "settings"}]
            },
            "product_consistency": {
                "findings": [
                    {
                        "id": "finding-save",
                        "domain": "data",
                        "kind": "SAVE_FAILURE",
                        "severity": "REVIEW",
                        "subject": "save",
                        "message": "Save may fail",
                        "evidence": ["lib/save.dart"],
                    }
                ]
            },
        },
        "confidence": {
            "schema_version": 1,
            "claims": [
                {
                    "id": "capability:auth",
                    "domain": "capability",
                    "subject": "auth",
                    "proposition": "capability-present",
                    "status": "CONFIRMED",
                    "evidence": ["lib/auth.dart"],
                    "rationale": "runtime and code agree",
                },
                {
                    "id": "capability:backup",
                    "domain": "capability",
                    "subject": "backup",
                    "proposition": "capability-present",
                    "status": "UNVERIFIED",
                    "evidence": ["README.md"],
                    "rationale": "docs only",
                },
            ],
            "contradictions": [],
        },
        "journey": {
            "schema_version": 1,
            "journeys": [{"depth": 2, "steps": ["home", "settings"]}],
            "findings": [],
        },
        "ux": {"schema_version": 1, "findings": []},
        "longitudinal": {
            "schema_version": 1,
            "state": "REGRESSION_REVIEW",
            "current": {"repository": "owner/app", "resolved_sha": sha2, "run_id": "42", "lineage_ref": "main"},
            "baseline": {"available": True, "repository": "owner/app", "resolved_sha": sha1, "run_id": "41"},
            "summary": {"history_snapshots": 2, "regression_candidates": 1},
            "findings": {
                "history": [
                    {
                        "id": "finding-save",
                        "kind": "SAVE_FAILURE",
                        "subject": "save",
                        "seen_count": 2,
                        "consecutive_seen": 2,
                        "first_seen_sha": sha1,
                        "last_seen_sha": sha2,
                    }
                ]
            },
            "regression_candidates": [
                {"kind": "SAVE_FAILURE", "subject": "save", "reason": "returned", "source": "product_consistency"}
            ],
        },
        "experiment": {
            "schema_version": 1,
            "experiments": [
                {
                    "id": "EXP-1",
                    "priority": "HIGH",
                    "kind": "SAVE_FAILURE",
                    "subject": "save",
                    "experiment_type": "SPECIALIST_RUNTIME",
                    "labs": ["persistence"],
                    "evidence": ["lib/save.dart"],
                }
            ],
        },
        "analyst": {
            "schema_version": 1,
            "state": "VERIFICATION_REQUIRED",
            "headline": "Verify save regression",
            "summary": {"observations": 1, "next_actions": 1, "regression_candidates": 1},
        },
        "autonomous": {
            "schema_version": 1,
            "runtime_evidence_trust": {
                "trusted": True,
                "manifest_sha256": "a" * 64,
                "binding": {
                    "repository": "owner/app",
                    "resolved_sha": sha2,
                    "workflow_run_id": "42",
                    "package_id": "com.example.app",
                },
            },
        },
        "build_contract": {
            "schema_version": 1,
            "repository": "owner/app",
            "resolved_sha": sha2,
            "trusted_applab_sha": "3" * 40,
            "apk": {
                "package_id": "com.example.app",
                "sha256": "b" * 64,
                "size_bytes": 1234,
                "version_name": "1.0",
                "version_code": "1",
                "build_variant": "debug",
            },
        },
    }

    graph = build_graph(evidence)
    counts = graph["summary"]["nodes_by_type"]
    for node_type in NODE_TYPES:
        assert node_type in counts
    assert counts["Project"] == 1
    assert counts["Revision"] == 2
    assert counts["BuildArtifact"] == 1
    assert counts["Capability"] == 2
    assert counts["Finding"] == 1
    assert counts["Claim"] == 2
    assert counts["Experiment"] == 1
    assert graph["summary"]["unverified_capabilities"] == 1
    assert graph["summary"]["recurring_findings"] == 1
    assert graph["summary"]["regression_candidates"] == 1

    recurring = query_graph(graph, "recurring-findings")
    assert recurring["results"][0]["first_observed_sha"] == sha1
    unverified = query_graph(graph, "unverified-capabilities")
    assert unverified["results"][0]["capability"] == "backup"
    history = query_graph(graph, "history", "save")
    assert len(history["results"]) == 1
    assert history["results"][0]["seen_count"] == 2
    evidence_query = query_graph(graph, "evidence", "backup")
    assert any(row.get("type") == "Evidence" for row in evidence_query["evidence"])

    optional_inputs = dict(evidence)
    optional_inputs.pop("autonomous", None)
    optional_inputs.pop("build_contract", None)
    optional_graph = build_graph(optional_inputs)
    optional_nodes = optional_graph["nodes"]
    optional_revision = next(
        row
        for row in optional_nodes
        if row.get("type") == "Revision"
        and (row.get("attributes") or {}).get("resolved_sha") == sha2
    )
    assert FILES["autonomous"] not in optional_revision["provenance"]
    assert not any(row.get("type") == "BuildArtifact" for row in optional_nodes)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        write_outputs(graph, out)
        assert (out / "evidence-graph.json").is_file()
        assert (out / "evidence-graph.md").is_file()
    print("AppLab Evidence Graph v4.2 self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or query AppLab Evidence Graph")
    parser.add_argument("--evidence-dir", default="applab-autonomous-review")
    parser.add_argument("--trusted-runtime-dir", default="")
    parser.add_argument("--output-dir", default="applab-autonomous-review")
    parser.add_argument("--graph", default="")
    parser.add_argument(
        "--query",
        choices=(
            "unverified-capabilities",
            "recurring-findings",
            "regressions",
            "history",
            "evidence",
        ),
        default="",
    )
    parser.add_argument("--subject", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    if args.query:
        graph_path = Path(args.graph or Path(args.output_dir) / "evidence-graph.json")
        graph = read_json(graph_path)
        if graph is None:
            raise SystemExit(f"Evidence Graph not found or invalid: {graph_path}")
        result = query_graph(graph, args.query, args.subject)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    evidence_dir = Path(args.evidence_dir)
    trusted_dir = Path(args.trusted_runtime_dir) if args.trusted_runtime_dir else None
    inputs = load_inputs(evidence_dir, trusted_dir)
    required = {"app", "confidence", "journey", "ux", "longitudinal", "experiment", "analyst"}
    missing = sorted(required - set(inputs))
    if missing:
        raise SystemExit("Evidence Graph missing required reports: " + ", ".join(missing))

    graph = build_graph(inputs)
    write_outputs(graph, Path(args.output_dir))
    print(json.dumps(graph["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
