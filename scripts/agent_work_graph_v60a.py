#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import durable_brain_v54a as brain
import durable_store_v54b as storemod

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "agent-work-graph-v1.json"
)


class WorkGraphError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise WorkGraphError("unsupported agent work graph contract version")
    if payload.get("contract_name") != "APPLAB_AGENT_WORK_GRAPH":
        raise WorkGraphError("unexpected agent work graph contract")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise WorkGraphError("agent work graph authority must remain orchestration-only")
    return payload


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise WorkGraphError(f"{label} must be a list")
    return value


def _require_fields(payload: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise WorkGraphError(f"{label} missing required fields: {', '.join(missing)}")


def _require_work_id(value: Any, label: str) -> str:
    return brain._require_id(value, label)


def validate_authority_envelope(
    envelope: dict[str, Any], contract: dict[str, Any], risk: str
) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise WorkGraphError("authority_envelope must be an object")
    allowed = _require_list(envelope.get("allowed_capabilities"), "allowed_capabilities")
    denied = _require_list(envelope.get("denied_capabilities"), "denied_capabilities")
    allowed_values = set(contract["authority_envelope"]["allowed_capabilities"])
    mandatory_denials = set(contract["authority_envelope"]["mandatory_denials"])
    unknown = sorted(set(allowed) - allowed_values)
    if unknown:
        raise WorkGraphError(f"unsupported allowed capabilities: {', '.join(unknown)}")
    missing_denials = sorted(mandatory_denials - set(denied))
    if missing_denials:
        raise WorkGraphError(
            f"authority envelope missing mandatory denials: {', '.join(missing_denials)}"
        )
    if set(allowed) & set(denied):
        raise WorkGraphError("authority capability cannot be both allowed and denied")
    if risk == "SECURITY" and "ALLOW_CODE_EDIT" in allowed:
        raise WorkGraphError("security-risk WorkItem cannot allow autonomous code edit")
    return envelope


def validate_budgets(budgets: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(budgets, dict):
        raise WorkGraphError("budgets must be an object")
    maximums = contract["budgets"]
    for field, ceiling in maximums.items():
        value = budgets.get(field)
        if not isinstance(value, int) or value < 0:
            raise WorkGraphError(f"budget {field} must be a non-negative integer")
        if value > ceiling:
            raise WorkGraphError(f"budget {field} exceeds contract ceiling")
    return budgets


def validate_work_item(
    payload: dict[str, Any], contract: dict[str, Any], operation: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkGraphError("work_item must be an object")
    spec = contract["work_item"]
    _require_fields(payload, spec["required"], "work_item")
    if payload.get("schema_version") != 1:
        raise WorkGraphError("work_item schema_version must be 1")
    if payload.get("record_type") != spec["record_type"]:
        raise WorkGraphError("work_item record_type mismatch")
    _require_work_id(payload.get("work_item_id"), "work_item_id")
    brain._require_id(payload.get("operation_id"), "operation_id")
    brain._require_repository(payload.get("repository"))
    brain._require_non_empty_string(payload.get("source_ref"), "source_ref")
    brain._require_sha(payload.get("resolved_sha"), "resolved_sha")
    brain._require_sha(payload.get("applab_sha"), "applab_sha")
    baseline = str(payload.get("baseline_sha") or "")
    if baseline:
        brain._require_sha(baseline, "baseline_sha")
    risk = str(payload.get("risk") or "")
    if risk not in spec["risk_levels"]:
        raise WorkGraphError("invalid work_item risk")
    if payload.get("state") not in spec["states"]:
        raise WorkGraphError("invalid work_item state")
    if payload.get("authority") != "ORCHESTRATION_ONLY":
        raise WorkGraphError("work_item authority must remain orchestration-only")
    validate_authority_envelope(payload["authority_envelope"], contract, risk)
    validate_budgets(payload["budgets"], contract)
    for field in ("acceptance_criteria", "required_evidence", "terminal_conditions"):
        values = _require_list(payload[field], field)
        if not all(isinstance(item, str) and item.strip() for item in values):
            raise WorkGraphError(f"{field} must contain non-empty strings")
    unknown_terminal = sorted(
        set(payload["terminal_conditions"]) - set(contract["terminal_conditions"])
    )
    if unknown_terminal:
        raise WorkGraphError(
            f"unsupported terminal conditions: {', '.join(unknown_terminal)}"
        )
    if not isinstance(payload.get("rollback"), dict):
        raise WorkGraphError("rollback must be an object")

    if operation is not None:
        brain.validate_operation(operation, brain.load_contract())
        for field in ("repository", "source_ref", "resolved_sha", "applab_sha"):
            if payload[field] != operation[field]:
                raise WorkGraphError(f"work_item {field} must match durable operation")
        if payload["operation_id"] != operation["operation_id"]:
            raise WorkGraphError("work_item operation_id must match durable operation")
    return payload


def validate_decision(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkGraphError("decision must be an object")
    spec = contract["decision"]
    _require_fields(payload, spec["required"], "decision")
    if payload.get("schema_version") != 1 or payload.get("record_type") != spec["record_type"]:
        raise WorkGraphError("decision contract mismatch")
    _require_work_id(payload.get("decision_id"), "decision_id")
    _require_work_id(payload.get("work_item_id"), "work_item_id")
    if payload.get("kind") not in spec["kinds"]:
        raise WorkGraphError("invalid decision kind")
    brain._require_non_empty_string(payload.get("reason_code"), "reason_code")
    brain._require_non_empty_string(payload.get("created_at"), "created_at")
    refs = _require_list(payload.get("evidence_ref_ids"), "evidence_ref_ids")
    for ref in refs:
        brain._require_id(ref, "evidence_ref_id")
    return payload


def validate_action(
    payload: dict[str, Any],
    contract: dict[str, Any],
    work_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkGraphError("action must be an object")
    spec = contract["action"]
    _require_fields(payload, spec["required"], "action")
    if payload.get("schema_version") != 1 or payload.get("record_type") != spec["record_type"]:
        raise WorkGraphError("action contract mismatch")
    _require_work_id(payload.get("action_id"), "action_id")
    _require_work_id(payload.get("work_item_id"), "work_item_id")
    _require_work_id(payload.get("decision_id"), "decision_id")
    capability = brain._require_non_empty_string(payload.get("capability"), "capability")
    if capability not in contract["authority_envelope"]["allowed_capabilities"]:
        raise WorkGraphError("action capability is not recognized by contract")
    if payload.get("state") not in spec["states"]:
        raise WorkGraphError("invalid action state")
    brain._require_non_empty_string(payload.get("created_at"), "created_at")
    if work_item is not None:
        envelope = work_item["authority_envelope"]
        if capability not in envelope["allowed_capabilities"]:
            raise WorkGraphError("action capability is outside WorkItem authority envelope")
    return payload


def validate_attempt_link(
    payload: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkGraphError("attempt_link must be an object")
    spec = contract["attempt_link"]
    _require_fields(payload, spec["required"], "attempt_link")
    if payload.get("schema_version") != 1 or payload.get("record_type") != spec["record_type"]:
        raise WorkGraphError("attempt_link contract mismatch")
    _require_work_id(payload.get("attempt_link_id"), "attempt_link_id")
    _require_work_id(payload.get("work_item_id"), "work_item_id")
    _require_work_id(payload.get("action_id"), "action_id")
    brain._require_id(payload.get("attempt_id"), "attempt_id")
    brain._require_non_empty_string(payload.get("created_at"), "created_at")
    return payload


def validate_verdict(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise WorkGraphError("verdict must be an object")
    spec = contract["verdict"]
    _require_fields(payload, spec["required"], "verdict")
    if payload.get("schema_version") != 1 or payload.get("record_type") != spec["record_type"]:
        raise WorkGraphError("verdict contract mismatch")
    _require_work_id(payload.get("verdict_id"), "verdict_id")
    _require_work_id(payload.get("work_item_id"), "work_item_id")
    _require_work_id(payload.get("decision_id"), "decision_id")
    if payload.get("state") not in spec["states"]:
        raise WorkGraphError("invalid work verdict state")
    if payload.get("authority") != spec["authority"]:
        raise WorkGraphError("work verdict cannot mint verification authority")
    brain._require_non_empty_string(payload.get("reason_code"), "reason_code")
    brain._require_non_empty_string(payload.get("created_at"), "created_at")
    refs = _require_list(payload.get("evidence_ref_ids"), "evidence_ref_ids")
    for ref in refs:
        brain._require_id(ref, "evidence_ref_id")
    return payload


def validate_transition(
    from_state: str, to_state: str, contract: dict[str, Any]
) -> bool:
    allowed = contract["work_item"]["allowed_transitions"]
    if from_state not in allowed or to_state not in contract["work_item"]["states"]:
        raise WorkGraphError("unknown work item transition state")
    if to_state not in allowed[from_state]:
        raise WorkGraphError(f"illegal work item transition {from_state} -> {to_state}")
    return True


def adapt_operation_to_work_item(
    operation: dict[str, Any],
    *,
    work_item_id: str,
    risk: str = "NORMAL",
    allow_code_edit: bool = False,
) -> dict[str, Any]:
    brain.validate_operation(operation, brain.load_contract())
    contract = load_contract()
    allowed = [
        "READ_REPOSITORY",
        "READ_EVIDENCE",
        "RUN_FOCUSED_TESTS",
        "RUN_APPLAB_FAST",
        "RUN_APPLAB_FULL",
    ]
    if allow_code_edit:
        allowed.append("ALLOW_CODE_EDIT")
    item = {
        "schema_version": 1,
        "record_type": "APPLAB_WORK_ITEM",
        "work_item_id": work_item_id,
        "operation_id": operation["operation_id"],
        "repository": operation["repository"],
        "source_ref": operation["source_ref"],
        "resolved_sha": operation["resolved_sha"],
        "baseline_sha": str(operation.get("baseline_sha") or ""),
        "applab_sha": operation["applab_sha"],
        "risk": risk,
        "state": "CREATED",
        "authority": "ORCHESTRATION_ONLY",
        "authority_envelope": {
            "allowed_capabilities": allowed,
            "denied_capabilities": list(contract["authority_envelope"]["mandatory_denials"]),
        },
        "budgets": {
            "max_files": 5 if allow_code_edit else 0,
            "max_changed_lines": 250 if allow_code_edit else 0,
            "max_repair_attempts": 2 if allow_code_edit else 0,
            "max_agent_actions": 24,
        },
        "acceptance_criteria": ["required evidence is present and identity-bound"],
        "required_evidence": ["exact source identity", "attempt evidence"],
        "rollback": {"strategy": "revert bounded repair delta if code edit is later enabled"},
        "terminal_conditions": list(contract["terminal_conditions"]),
    }
    return validate_work_item(item, contract, operation)


SQLITE_AGENT_WORK_GRAPH_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_work_items (
    work_item_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
    identity_sha256 TEXT NOT NULL,
    initial_state TEXT NOT NULL,
    current_state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_work_decisions (
    decision_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES agent_work_items(work_item_id),
    sequence_number INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(work_item_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS agent_work_actions (
    action_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES agent_work_items(work_item_id),
    decision_id TEXT NOT NULL REFERENCES agent_work_decisions(decision_id),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_work_attempt_links (
    attempt_link_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES agent_work_items(work_item_id),
    action_id TEXT NOT NULL REFERENCES agent_work_actions(action_id),
    attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(work_item_id, attempt_id)
);

CREATE TABLE IF NOT EXISTS agent_work_verdicts (
    verdict_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES agent_work_items(work_item_id),
    decision_id TEXT NOT NULL REFERENCES agent_work_decisions(decision_id),
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_work_transitions (
    transition_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL REFERENCES agent_work_items(work_item_id),
    sequence_number INTEGER NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(work_item_id, sequence_number)
);

CREATE TRIGGER IF NOT EXISTS agent_decisions_no_update
BEFORE UPDATE ON agent_work_decisions BEGIN SELECT RAISE(ABORT, 'agent decisions append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_decisions_no_delete
BEFORE DELETE ON agent_work_decisions BEGIN SELECT RAISE(ABORT, 'agent decisions append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_actions_no_update
BEFORE UPDATE ON agent_work_actions BEGIN SELECT RAISE(ABORT, 'agent actions append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_actions_no_delete
BEFORE DELETE ON agent_work_actions BEGIN SELECT RAISE(ABORT, 'agent actions append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_attempt_links_no_update
BEFORE UPDATE ON agent_work_attempt_links BEGIN SELECT RAISE(ABORT, 'agent attempt links append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_attempt_links_no_delete
BEFORE DELETE ON agent_work_attempt_links BEGIN SELECT RAISE(ABORT, 'agent attempt links append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_verdicts_no_update
BEFORE UPDATE ON agent_work_verdicts BEGIN SELECT RAISE(ABORT, 'agent verdicts append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_verdicts_no_delete
BEFORE DELETE ON agent_work_verdicts BEGIN SELECT RAISE(ABORT, 'agent verdicts append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_transitions_no_update
BEFORE UPDATE ON agent_work_transitions BEGIN SELECT RAISE(ABORT, 'agent transitions append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_transitions_no_delete
BEFORE DELETE ON agent_work_transitions BEGIN SELECT RAISE(ABORT, 'agent transitions append-only'); END;
CREATE TRIGGER IF NOT EXISTS agent_work_items_identity_no_update
BEFORE UPDATE OF work_item_id,operation_id,identity_sha256,initial_state,payload_json,created_at
ON agent_work_items BEGIN SELECT RAISE(ABORT, 'agent work item immutable identity'); END;
CREATE TRIGGER IF NOT EXISTS agent_work_items_no_delete
BEFORE DELETE ON agent_work_items BEGIN SELECT RAISE(ABORT, 'agent work items cannot be deleted'); END;
"""


class AgentWorkGraphStore:
    def __init__(
        self,
        durable_store: storemod.SQLiteShadowStore,
        contract: dict[str, Any] | None = None,
    ) -> None:
        self.store = durable_store
        self.db = durable_store.db
        self.contract = contract or load_contract()
        self.db.executescript(SQLITE_AGENT_WORK_GRAPH_SCHEMA)
        self.db.commit()

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        return brain.sha256_json(payload)

    def _operation(self, operation_id: str) -> dict[str, Any]:
        return self.store.get_operation(operation_id)

    def _validate_evidence_refs(self, work_item_id: str, refs: list[str]) -> None:
        operation_id = self.get_work_item(work_item_id)["operation_id"]
        for ref in refs:
            evidence = self.db.execute(
                "SELECT operation_id FROM evidence_refs WHERE evidence_ref_id=?",
                (ref,),
            ).fetchone()
            if evidence is None:
                raise WorkGraphError("work graph references unknown evidence")
            if evidence["operation_id"] != operation_id:
                raise WorkGraphError("work graph evidence belongs to another operation")

    def put_work_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        operation = self._operation(str(payload.get("operation_id") or ""))
        validate_work_item(payload, self.contract, operation)
        digest = self._digest(payload)
        existing = self.db.execute(
            "SELECT identity_sha256 FROM agent_work_items WHERE work_item_id=?",
            (payload["work_item_id"],),
        ).fetchone()
        if existing:
            if existing["identity_sha256"] != digest:
                raise WorkGraphError("work_item_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "work_item_id": payload["work_item_id"]}
        by_operation = self.db.execute(
            "SELECT work_item_id FROM agent_work_items WHERE operation_id=?",
            (payload["operation_id"],),
        ).fetchone()
        if by_operation:
            return {"status": "OPERATION_REUSE", "work_item_id": by_operation["work_item_id"]}
        with self.db:
            self.db.execute(
                """
                INSERT INTO agent_work_items(
                    work_item_id,operation_id,identity_sha256,initial_state,current_state,payload_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    payload["work_item_id"],
                    payload["operation_id"],
                    digest,
                    payload["state"],
                    payload["state"],
                    brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "work_item_id": payload["work_item_id"]}

    def get_work_item(self, work_item_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM agent_work_items WHERE work_item_id=?", (work_item_id,)
        ).fetchone()
        if row is None:
            raise WorkGraphError("unknown work item")
        payload = json.loads(row["payload_json"])
        payload["initial_state"] = row["initial_state"]
        payload["current_state"] = row["current_state"]
        return payload

    def _next_sequence(self, table: str, work_item_id: str) -> int:
        row = self.db.execute(
            f"SELECT COALESCE(MAX(sequence_number),0)+1 AS n FROM {table} WHERE work_item_id=?",
            (work_item_id,),
        ).fetchone()
        return int(row["n"])

    def put_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_decision(payload, self.contract)
        self.get_work_item(payload["work_item_id"])
        self._validate_evidence_refs(payload["work_item_id"], payload["evidence_ref_ids"])
        digest = self._digest(payload)
        existing = self.db.execute(
            "SELECT payload_sha256,sequence_number FROM agent_work_decisions WHERE decision_id=?",
            (payload["decision_id"],),
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise WorkGraphError("decision_id reused with conflicting immutable payload")
            return {
                "status": "REPLAY",
                "decision_id": payload["decision_id"],
                "sequence_number": existing["sequence_number"],
            }
        sequence = self._next_sequence("agent_work_decisions", payload["work_item_id"])
        with self.db:
            self.db.execute(
                """
                INSERT INTO agent_work_decisions(
                    decision_id,work_item_id,sequence_number,payload_sha256,payload_json
                ) VALUES (?,?,?,?,?)
                """,
                (
                    payload["decision_id"],
                    payload["work_item_id"],
                    sequence,
                    digest,
                    brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "decision_id": payload["decision_id"], "sequence_number": sequence}

    def put_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        work_item = self.get_work_item(payload["work_item_id"])
        validate_action(payload, self.contract, work_item)
        decision = self.db.execute(
            "SELECT work_item_id FROM agent_work_decisions WHERE decision_id=?",
            (payload["decision_id"],),
        ).fetchone()
        if decision is None or decision["work_item_id"] != payload["work_item_id"]:
            raise WorkGraphError("action decision identity mismatch")
        digest = self._digest(payload)
        existing = self.db.execute(
            "SELECT payload_sha256 FROM agent_work_actions WHERE action_id=?",
            (payload["action_id"],),
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise WorkGraphError("action_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "action_id": payload["action_id"]}
        with self.db:
            self.db.execute(
                """
                INSERT INTO agent_work_actions(
                    action_id,work_item_id,decision_id,payload_sha256,payload_json
                ) VALUES (?,?,?,?,?)
                """,
                (
                    payload["action_id"],
                    payload["work_item_id"],
                    payload["decision_id"],
                    digest,
                    brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "action_id": payload["action_id"]}

    def put_attempt_link(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_attempt_link(payload, self.contract)
        item = self.get_work_item(payload["work_item_id"])
        action = self.db.execute(
            "SELECT work_item_id FROM agent_work_actions WHERE action_id=?",
            (payload["action_id"],),
        ).fetchone()
        if action is None or action["work_item_id"] != payload["work_item_id"]:
            raise WorkGraphError("attempt link action identity mismatch")
        attempt = self.db.execute(
            "SELECT operation_id FROM attempts WHERE attempt_id=?",
            (payload["attempt_id"],),
        ).fetchone()
        if attempt is None:
            raise WorkGraphError("attempt link references unknown durable attempt")
        if attempt["operation_id"] != item["operation_id"]:
            raise WorkGraphError("attempt link belongs to another operation")
        digest = self._digest(payload)
        existing = self.db.execute(
            "SELECT payload_sha256 FROM agent_work_attempt_links WHERE attempt_link_id=?",
            (payload["attempt_link_id"],),
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise WorkGraphError("attempt_link_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "attempt_link_id": payload["attempt_link_id"]}
        duplicate = self.db.execute(
            "SELECT attempt_link_id FROM agent_work_attempt_links WHERE work_item_id=? AND attempt_id=?",
            (payload["work_item_id"], payload["attempt_id"]),
        ).fetchone()
        if duplicate:
            return {"status": "ATTEMPT_REUSE", "attempt_link_id": duplicate["attempt_link_id"]}
        with self.db:
            self.db.execute(
                """
                INSERT INTO agent_work_attempt_links(
                    attempt_link_id,work_item_id,action_id,attempt_id,payload_sha256,payload_json
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    payload["attempt_link_id"],
                    payload["work_item_id"],
                    payload["action_id"],
                    payload["attempt_id"],
                    digest,
                    brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "attempt_link_id": payload["attempt_link_id"]}

    def put_verdict(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_verdict(payload, self.contract)
        self.get_work_item(payload["work_item_id"])
        decision = self.db.execute(
            "SELECT work_item_id FROM agent_work_decisions WHERE decision_id=?",
            (payload["decision_id"],),
        ).fetchone()
        if decision is None or decision["work_item_id"] != payload["work_item_id"]:
            raise WorkGraphError("verdict decision identity mismatch")
        self._validate_evidence_refs(payload["work_item_id"], payload["evidence_ref_ids"])
        digest = self._digest(payload)
        existing = self.db.execute(
            "SELECT payload_sha256 FROM agent_work_verdicts WHERE verdict_id=?",
            (payload["verdict_id"],),
        ).fetchone()
        if existing:
            if existing["payload_sha256"] != digest:
                raise WorkGraphError("verdict_id reused with conflicting immutable payload")
            return {"status": "REPLAY", "verdict_id": payload["verdict_id"]}
        with self.db:
            self.db.execute(
                """
                INSERT INTO agent_work_verdicts(
                    verdict_id,work_item_id,decision_id,payload_sha256,payload_json
                ) VALUES (?,?,?,?,?)
                """,
                (
                    payload["verdict_id"],
                    payload["work_item_id"],
                    payload["decision_id"],
                    digest,
                    brain.canonical_json(payload),
                ),
            )
        return {"status": "INSERTED", "verdict_id": payload["verdict_id"]}

    def transition(
        self,
        *,
        transition_id: str,
        work_item_id: str,
        from_state: str,
        to_state: str,
        reason_code: str,
        created_at: str,
    ) -> dict[str, Any]:
        _require_work_id(transition_id, "transition_id")
        validate_transition(from_state, to_state, self.contract)
        brain._require_non_empty_string(reason_code, "reason_code")
        brain._require_non_empty_string(created_at, "created_at")
        payload = {
            "schema_version": 1,
            "record_type": "APPLAB_WORK_TRANSITION",
            "transition_id": transition_id,
            "work_item_id": work_item_id,
            "from_state": from_state,
            "to_state": to_state,
            "reason_code": reason_code,
            "created_at": created_at,
        }
        digest = self._digest(payload)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute(
                """
                SELECT payload_sha256,sequence_number,to_state
                FROM agent_work_transitions WHERE transition_id=?
                """,
                (transition_id,),
            ).fetchone()
            if existing:
                if existing["payload_sha256"] != digest:
                    raise WorkGraphError("transition_id reused with conflicting immutable payload")
                self.db.commit()
                return {
                    "status": "REPLAY",
                    "transition_id": transition_id,
                    "sequence_number": existing["sequence_number"],
                    "current_state": existing["to_state"],
                }
            row = self.db.execute(
                "SELECT current_state FROM agent_work_items WHERE work_item_id=?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise WorkGraphError("transition references unknown work item")
            if row["current_state"] != from_state:
                raise WorkGraphError("transition from_state does not match current state")
            sequence = self._next_sequence("agent_work_transitions", work_item_id)
            self.db.execute(
                """
                INSERT INTO agent_work_transitions(
                    transition_id,work_item_id,sequence_number,from_state,to_state,
                    reason_code,payload_sha256,payload_json
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    transition_id,
                    work_item_id,
                    sequence,
                    from_state,
                    to_state,
                    reason_code,
                    digest,
                    brain.canonical_json(payload),
                ),
            )
            self.db.execute(
                "UPDATE agent_work_items SET current_state=?,updated_at=CURRENT_TIMESTAMP WHERE work_item_id=?",
                (to_state, work_item_id),
            )
            self.db.commit()
            return {
                "status": "INSERTED",
                "transition_id": transition_id,
                "sequence_number": sequence,
                "current_state": to_state,
            }
        except Exception:
            if self.db.in_transaction:
                self.db.rollback()
            raise

    def rebuild_state(self, work_item_id: str) -> str:
        item = self.get_work_item(work_item_id)
        state = item["initial_state"]
        rows = self.db.execute(
            """
            SELECT from_state,to_state FROM agent_work_transitions
            WHERE work_item_id=? ORDER BY sequence_number ASC
            """,
            (work_item_id,),
        ).fetchall()
        for row in rows:
            if row["from_state"] != state:
                raise WorkGraphError("work item transition history is not replayable")
            validate_transition(state, row["to_state"], self.contract)
            state = row["to_state"]
        return state

    def integrity_report(self) -> dict[str, Any]:
        rows = self.db.execute(
            "SELECT work_item_id,current_state FROM agent_work_items ORDER BY work_item_id"
        ).fetchall()
        projection_errors = [
            row["work_item_id"]
            for row in rows
            if self.rebuild_state(row["work_item_id"]) != row["current_state"]
        ]
        counts = {}
        for table in (
            "agent_work_items",
            "agent_work_decisions",
            "agent_work_actions",
            "agent_work_attempt_links",
            "agent_work_verdicts",
            "agent_work_transitions",
        ):
            counts[table] = self.db.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"]
        return {
            "schema_version": 1,
            "authority": "ORCHESTRATION_ONLY",
            "counts": counts,
            "projection_errors": projection_errors,
            "ok": not projection_errors,
        }


def self_test() -> None:
    contract = load_contract()
    sha = "b" * 40
    applab_sha = "c" * 40
    operation = brain._operation_fixture(
        "op_v60a", "owner/app", "main", sha, applab_sha
    )
    item = adapt_operation_to_work_item(
        operation, work_item_id="wrk_v60a", allow_code_edit=False
    )
    assert item["operation_id"] == operation["operation_id"]
    assert item["budgets"]["max_files"] == 0
    assert "WRITE_MAIN" in item["authority_envelope"]["denied_capabilities"]

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "work-graph.sqlite3"
        with storemod.SQLiteShadowStore(db_path) as durable:
            durable.put_operation(operation)
            graph = AgentWorkGraphStore(durable, contract)
            assert graph.put_work_item(item)["status"] == "INSERTED"
            assert graph.put_work_item(item)["status"] == "REPLAY"
            graph.transition(
                transition_id="trn_v60a_1",
                work_item_id="wrk_v60a",
                from_state="CREATED",
                to_state="INVESTIGATING",
                reason_code="FAILURE_RECEIVED",
                created_at="2026-10-27T00:00:00Z",
            )
            decision = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_DECISION",
                "decision_id": "dec_v60a_1",
                "work_item_id": "wrk_v60a",
                "kind": "RUN_APPLAB_FAST",
                "reason_code": "FOCUSED_REPRODUCTION",
                "evidence_ref_ids": [],
                "created_at": "2026-10-27T00:01:00Z",
            }
            assert graph.put_decision(decision)["sequence_number"] == 1
            action = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_ACTION",
                "action_id": "act_v60a_1",
                "work_item_id": "wrk_v60a",
                "decision_id": "dec_v60a_1",
                "capability": "RUN_APPLAB_FAST",
                "state": "PLANNED",
                "created_at": "2026-10-27T00:02:00Z",
            }
            assert graph.put_action(action)["status"] == "INSERTED"
            attempt = brain._attempt_fixture(
                "att_v60a", "op_v60a", 1, "SUCCEEDED", "NONE", False
            )
            assert durable.put_attempt(attempt)["status"] == "INSERTED"
            attempt_link = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_ATTEMPT_LINK",
                "attempt_link_id": "lnk_v60a_1",
                "work_item_id": "wrk_v60a",
                "action_id": "act_v60a_1",
                "attempt_id": "att_v60a",
                "created_at": "2026-10-27T00:02:30Z",
            }
            assert graph.put_attempt_link(attempt_link)["status"] == "INSERTED"
            evidence = storemod._evidence_fixture(
                "evd_v60a_1", operation, "att_v60a"
            )
            assert durable.put_evidence_ref(evidence)["status"] == "INSERTED"
            verdict = {
                "schema_version": 1,
                "record_type": "APPLAB_WORK_VERDICT",
                "verdict_id": "vrd_v60a_1",
                "work_item_id": "wrk_v60a",
                "decision_id": "dec_v60a_1",
                "state": "CONTINUE",
                "reason_code": "MORE_EVIDENCE_REQUIRED",
                "evidence_ref_ids": ["evd_v60a_1"],
                "authority": "ORCHESTRATION_ONLY",
                "created_at": "2026-10-27T00:03:00Z",
            }
            assert graph.put_verdict(verdict)["status"] == "INSERTED"
            assert graph.rebuild_state("wrk_v60a") == "INVESTIGATING"
            assert graph.integrity_report()["ok"] is True

            blocked_action = dict(action, action_id="act_v60a_2", capability="ALLOW_CODE_EDIT")
            try:
                graph.put_action(blocked_action)
            except WorkGraphError as exc:
                assert "outside WorkItem authority envelope" in str(exc)
            else:
                raise AssertionError("read-only WorkItem unexpectedly allowed code edit")

    security = adapt_operation_to_work_item(
        operation, work_item_id="wrk_v60a_security", risk="SECURITY", allow_code_edit=False
    )
    assert security["risk"] == "SECURITY"
    try:
        adapt_operation_to_work_item(
            operation, work_item_id="wrk_v60a_security_edit", risk="SECURITY", allow_code_edit=True
        )
    except WorkGraphError as exc:
        assert "security-risk WorkItem" in str(exc)
    else:
        raise AssertionError("security-risk WorkItem unexpectedly allowed code edit")
    print("AppLab v6.0A unified agent work graph self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    load_contract(Path(args.contract))
    print("VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
