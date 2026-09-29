#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from product_review_common import find_json, load_json, result_state, write_report

SCHEMA_VERSION = 1
LAB_VERSION = "3.1.0"

REPORTS = {
    "normal": ["interaction-crawl.json"],
    "offline": ["network-lab.json"],
    "restart": ["persistence-lab.json"],
    "configuration": ["configuration-lab.json"],
    "process_death": ["resource-pressure-lab.json", "resource-pressure.json"],
    "storage": ["storage-lab.json", "storage-integrity.json"],
    "background": ["background-lab.json", "background-doze-recovery.json"],
    "permissions": ["system-lab.json", "permissions-system-ui.json"],
}

UI_KEYWORDS = {
    "empty": ("empty", "nessun", "no items", "no data", "nothing here"),
    "loading": ("loading", "caricamento", "please wait"),
    "error": ("error", "errore", "something went wrong", "failed"),
    "auth": ("login", "sign in", "signin", "log in", "autentic"),
    "permission_denied": ("permission denied", "permesso negato", "permission required"),
}


def hierarchy_visible_text(path: Path) -> str:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return ""
    values: list[str] = []
    for node in root.iter():
        for key in ("text", "content-desc"):
            value = str(node.attrib.get(key, "")).strip()
            if value:
                values.append(value)
    return " ".join(values).lower()


def scan_ui_states(root: Path | None) -> dict[str, list[str]]:
    found = {key: [] for key in UI_KEYWORDS}
    if root is None or not root.exists():
        return found
    for path in sorted(root.rglob("*.xml")):
        try:
            if path.stat().st_size > 2_000_000:
                continue
        except OSError:
            continue
        text = hierarchy_visible_text(path)
        if not text:
            continue
        for key, terms in UI_KEYWORDS.items():
            if any(term in text for term in terms):
                found[key].append(str(path))
                found[key] = found[key][:8]
    return found


def build_report(app: dict[str, Any], evidence_root: Path | None) -> dict[str, Any]:
    states: dict[str, dict[str, Any]] = {}
    for state, names in REPORTS.items():
        path, payload = find_json(evidence_root, names)
        states[state] = {
            "status": result_state(payload),
            "source": str(path) if path else None,
            "result": str(payload.get("result", "")) if payload else None,
            "source_kind": "RUNTIME_LAB",
        }

    ui_observations = scan_ui_states(evidence_root)
    for state, paths in ui_observations.items():
        states[state] = {
            "status": "OBSERVED" if paths else "NOT_OBSERVED",
            "source": paths,
            "result": None,
            "source_kind": "UI_HIERARCHY",
        }

    product = app.get("product") if isinstance(app.get("product"), dict) else {}
    features = product.get("feature_signals") if isinstance(product.get("feature_signals"), list) else []
    capabilities = {
        str(x.get("label", ""))
        for x in features
        if isinstance(x, dict) and str(x.get("status", "")).upper() == "PRESENT"
    }

    applicability = {
        "offline": bool(capabilities & {"network_api", "cloud_or_sync"}),
        "auth": "authentication" in capabilities,
        "permissions": bool(capabilities & {"notifications", "maps_or_location", "camera", "microphone"}),
        "permission_denied": bool(capabilities & {"notifications", "maps_or_location", "camera", "microphone"}),
        "restart": True,
        "configuration": True,
        "process_death": True,
        "storage": True,
        "background": "background_execution" in capabilities,
        "empty": True,
        "loading": bool(capabilities & {"network_api", "cloud_or_sync"}),
        "error": True,
        "normal": True,
    }

    findings: list[dict[str, Any]] = []
    for state, row in states.items():
        applicable = applicability.get(state, True)
        if not applicable:
            row["applicability"] = "NOT_APPLICABLE"
            continue
        row["applicability"] = "APPLICABLE"
        if row["status"] == "OBSERVED_FAIL":
            findings.append(
                {
                    "kind": "EDGE_STATE_RUNTIME_FAILURE",
                    "severity": "HIGH_REVIEW",
                    "confidence": "HIGH",
                    "state": state,
                    "subject": state,
                    "message": f"Trusted runtime evidence failed in {state} state.",
                    "evidence": [row["source"]] if isinstance(row["source"], str) and row["source"] else [],
                    "relation_key": f"state:{state}",
                }
            )
        elif row["status"] in {"NOT_OBSERVED", "OBSERVED_UNKNOWN"}:
            findings.append(
                {
                    "kind": "EDGE_STATE_NOT_OBSERVED",
                    "severity": "REVIEW",
                    "confidence": "MEDIUM",
                    "state": state,
                    "subject": state,
                    "message": f"Applicable product state {state} has no bounded runtime observation.",
                    "evidence": [],
                    "relation_key": f"state:{state}",
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "lab_version": LAB_VERSION,
        "states": states,
        "summary": {
            "applicable": sum(1 for k in states if applicability.get(k, True)),
            "observed": sum(
                1
                for k, v in states.items()
                if applicability.get(k, True)
                and v["status"] not in {"NOT_OBSERVED", "OBSERVED_UNKNOWN"}
            ),
            "failed": sum(1 for v in states.values() if v["status"] == "OBSERVED_FAIL"),
            "review_signals": len(findings),
            "ui_states_observed": sum(
                1
                for key in UI_KEYWORDS
                if states.get(key, {}).get("status") == "OBSERVED"
            ),
        },
        "findings": findings,
        "guardrails": {
            "missing_state_is_review_not_fail": True,
            "applicability_is_capability_driven": True,
            "ui_states_require_ui_hierarchy": True,
            "log_or_json_keywords_do_not_prove_ui_state": True,
            "no_runtime_verdict_override": True,
        },
    }


def markdown(r: dict[str, Any]) -> str:
    lines = [
        "# AppLab State & Edge-Case Lab",
        "",
        f"- Applicable states: **{r['summary']['applicable']}**",
        f"- Observed states: **{r['summary']['observed']}**",
        f"- UI states observed: **{r['summary']['ui_states_observed']}**",
        f"- Runtime failures: **{r['summary']['failed']}**",
        "",
    ]
    for key, value in r["states"].items():
        lines.append(
            f"- **{key}**: {value['status']} · {value.get('applicability','')} · "
            f"{value.get('source_kind','')}"
        )
    return "\n".join(lines)


def self_test() -> None:
    app = {
        "product": {
            "feature_signals": [
                {"label": "network_api", "status": "PRESENT"},
                {"label": "authentication", "status": "PRESENT"},
            ]
        }
    }
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "network-lab.json").write_text('{"result":"PASS"}', encoding="utf-8")
        (root / "interaction-crawl.json").write_text('{"result":"PASS"}', encoding="utf-8")
        (root / "log.json").write_text('{"message":"login error loading"}', encoding="utf-8")
        (root / "ui.xml").write_text(
            '<hierarchy><node text="Login" content-desc="Sign in"/></hierarchy>',
            encoding="utf-8",
        )
        r = build_report(app, root)
        assert r["states"]["offline"]["status"] == "OBSERVED_PASS"
        assert r["states"]["auth"]["status"] == "OBSERVED"
        assert r["states"]["loading"]["status"] == "NOT_OBSERVED"
        assert r["states"]["error"]["status"] == "NOT_OBSERVED"
    print("AppLab State & Edge-Case Lab self-test PASS")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--app-intelligence")
    p.add_argument("--runtime-evidence-dir")
    p.add_argument("--output-dir", default="applab-state-edge")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if not a.app_intelligence:
        raise SystemExit("--app-intelligence is required")
    app = load_json(Path(a.app_intelligence))
    if app is None:
        raise SystemExit("invalid app intelligence")
    root = Path(a.runtime_evidence_dir) if a.runtime_evidence_dir else None
    r = build_report(app, root)
    write_report(Path(a.output_dir), "state-edge-case", r, markdown(r))
    print(json.dumps({"lab_version": LAB_VERSION, **r["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
