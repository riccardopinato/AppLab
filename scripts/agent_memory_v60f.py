#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import verify_repair_loop_v60d as repair_loop

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = (
    ROOT
    / "integration"
    / "orchestration"
    / "contracts"
    / "agent-memory-v1.json"
)
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
SUPPORTED_TYPES = {
    "AUTONOMOUS_FAILURE_TRIAGE_V58A",
    "CAUSAL_REPO_INVESTIGATION_V60B",
    "BOUNDED_FIX_RESULT_V60C",
    "VERIFY_REPAIR_LOOP_DECISION_V60D",
}


class MemoryError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise MemoryError("unsupported episodic memory contract version")
    if payload.get("contract_name") != "APPLAB_AGENT_EPISODIC_MEMORY":
        raise MemoryError("unexpected episodic memory contract")
    if payload.get("authority") != "ADVISORY_RANKING_ONLY":
        raise MemoryError("episodic memory authority mismatch")
    if set(payload.get("source_record_types") or []) != SUPPORTED_TYPES:
        raise MemoryError("episodic memory source record types drifted")
    return payload


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _repository(record: dict[str, Any]) -> str:
    return _clean(record.get("repository"))


def _source_sha(record: dict[str, Any]) -> str:
    return _clean(
        record.get("resolved_sha")
        or record.get("root_resolved_sha")
    ).lower()


def _valid_source_record(record: dict[str, Any]) -> bool:
    kind = record.get("record_type")
    if not isinstance(kind, str) or kind not in SUPPORTED_TYPES:
        return False
    repository = _repository(record)
    if not REPOSITORY_RE.fullmatch(repository):
        return False
    sha = _source_sha(record)
    if not SHA40_RE.fullmatch(sha):
        return False
    if kind == "BOUNDED_FIX_RESULT_V60C":
        if record.get("state") != "READY_FOR_VERIFICATION":
            return False
        if not _clean(record.get("work_item_id")):
            return False
        if not SHA256_RE.fullmatch(
            _clean(record.get("result_patch_sha256")).lower()
        ):
            return False
        changed = record.get("changed_files")
        if not isinstance(changed, list) or not any(_clean(x) for x in changed):
            return False
    return True


def _read_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not root.is_dir():
        return records
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict) or not _valid_source_record(value):
                continue
            row = dict(value)
            row["_source_ref"] = path.relative_to(root).as_posix()
            records.append(row)
    return records


def _work_item_id(record: dict[str, Any]) -> str:
    return _clean(
        record.get("work_item_id")
        or record.get("root_work_item_id")
    )


def _key(record: dict[str, Any]) -> tuple[str, str]:
    work_item_id = _work_item_id(record)
    if not work_item_id:
        work_item_id = f"sha:{_source_sha(record)}"
    return _repository(record), work_item_id


def _candidate_paths(record: dict[str, Any]) -> list[str]:
    rows = record.get("ranked_candidate_files")
    if not isinstance(rows, list):
        return []
    result: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            path = _clean(row.get("path"))
            if path:
                result.append(path)
    return list(dict.fromkeys(result))


def _regressions(record: dict[str, Any]) -> list[str]:
    values = record.get("required_regression_targets")
    if not isinstance(values, list):
        values = record.get("required_regression_evidence")
    if not isinstance(values, list):
        return []
    return list(
        dict.fromkeys(_clean(value) for value in values if _clean(value))
    )


def _signatures(record: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[Any] = []
    trigger = record.get("trigger_failure_signature")
    if isinstance(trigger, dict):
        rows.append(trigger)
    attempts = record.get("attempt_signatures")
    if isinstance(attempts, list):
        rows.extend(attempts)

    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        signature = _clean(row.get("signature_sha256")).lower()
        classification = _clean(row.get("classification"))
        if not SHA256_RE.fullmatch(signature):
            continue
        key = (signature, classification)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "signature_sha256": signature,
                "classification": classification,
            }
        )
    return result


def _repair_binding(record: dict[str, Any]) -> str:
    if record.get("record_type") != "BOUNDED_FIX_RESULT_V60C":
        return ""
    try:
        return repair_loop.repair_identity(record)
    except (TypeError, ValueError, KeyError):
        return ""


def _source_refs(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            _clean(row.get("_source_ref"))
            for row in rows
            if _clean(row.get("_source_ref"))
        }
    )


def build_memory(
    records: list[dict[str, Any]],
    *,
    max_episodes: int | None = None,
) -> dict[str, Any]:
    contract = load_contract()
    ceiling = int(contract["max_episodes"])
    limit = ceiling if max_episodes is None else int(max_episodes)
    if limit < 1 or limit > ceiling:
        raise MemoryError(f"max_episodes must be between 1 and {ceiling}")

    clean_records = [row for row in records if _valid_source_record(row)]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_work: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_source: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    repair_by_identity: dict[str, dict[str, Any]] = {}

    for record in clean_records:
        grouped[_key(record)].append(record)
        by_source[(_repository(record), _source_sha(record))].append(record)
        wid = _work_item_id(record)
        if wid:
            by_work[(_repository(record), wid)].append(record)
        binding = _repair_binding(record)
        if binding:
            repair_by_identity[binding] = record

    episodes: list[dict[str, Any]] = []
    successful_repairs: list[dict[str, Any]] = []

    for (repository, episode_key), rows in grouped.items():
        triages = [
            row for row in rows
            if row.get("record_type") == "AUTONOMOUS_FAILURE_TRIAGE_V58A"
        ]
        investigations = [
            row for row in rows
            if row.get("record_type") == "CAUSAL_REPO_INVESTIGATION_V60B"
        ]
        repairs = [
            row for row in rows
            if row.get("record_type") == "BOUNDED_FIX_RESULT_V60C"
        ]
        verdicts = [
            row for row in rows
            if row.get("record_type") == "VERIFY_REPAIR_LOOP_DECISION_V60D"
        ]

        classifications = sorted(
            {
                _clean(row.get("classification"))
                for row in [*triages, *investigations]
                if _clean(row.get("classification"))
            }
        )
        candidate_files: list[str] = []
        regressions: list[str] = []
        for row in investigations:
            candidate_files.extend(_candidate_paths(row))
            regressions.extend(_regressions(row))
        for row in triages:
            regressions.extend(_regressions(row))

        local_changed: list[str] = []
        for repair in repairs:
            changed = repair.get("changed_files")
            if isinstance(changed, list):
                local_changed.extend(_clean(x) for x in changed if _clean(x))

        signatures: list[dict[str, str]] = []
        for triage in triages:
            signatures.extend(_signatures(triage))
        stop_reasons: list[str] = []
        complete_verdicts: list[dict[str, Any]] = []
        for verdict in verdicts:
            signatures.extend(_signatures(verdict))
            if verdict.get("state") == "STOPPED":
                reason = _clean(verdict.get("reason_code"))
                if reason:
                    stop_reasons.append(reason)
            if (
                verdict.get("state") == "COMPLETE"
                and verdict.get("reason_code") == "VERIFIED_PASS"
            ):
                complete_verdicts.append(verdict)

        final_binding = ""
        final_repair: dict[str, Any] | None = None
        final_verdict: dict[str, Any] | None = None
        for verdict in complete_verdicts:
            binding = _clean(verdict.get("repair_identity_sha256")).lower()
            if binding and binding in repair_by_identity:
                final_binding = binding
                final_repair = repair_by_identity[binding]
                final_verdict = verdict
                break

        outcome = (
            "VERIFIED_PASS"
            if complete_verdicts
            else ("STOPPED" if stop_reasons else "INCOMPLETE")
        )
        repair_binding_state = (
            "BOUND"
            if final_repair is not None
            else ("MISSING_FINAL_REPAIR" if complete_verdicts else "NOT_APPLICABLE")
        )

        episode = {
            "repository": repository,
            "episode_key": episode_key,
            "classifications": classifications,
            "failure_signatures": signatures,
            "candidate_files": list(dict.fromkeys(candidate_files)),
            "observed_changed_files": list(dict.fromkeys(local_changed)),
            "required_regressions": list(dict.fromkeys(regressions)),
            "outcome": outcome,
            "repair_binding_state": repair_binding_state,
            "final_repair_identity_sha256": final_binding,
            "stop_reasons": list(dict.fromkeys(stop_reasons)),
            "resolved_shas": sorted({_source_sha(row) for row in rows}),
            "source_refs": _source_refs(rows),
        }
        episode["episode_digest_sha256"] = _digest(episode)
        episodes.append(episode)

        if final_repair is not None and final_verdict is not None:
            final_work_item = _work_item_id(final_repair)
            related = list(by_work.get((repository, final_work_item), []))
            final_source_sha = _source_sha(final_repair)
            related.extend(
                row
                for row in by_source.get((repository, final_source_sha), [])
                if not _work_item_id(row)
                and row.get("record_type")
                in {"AUTONOMOUS_FAILURE_TRIAGE_V58A", "CAUSAL_REPO_INVESTIGATION_V60B"}
            )
            final_investigations = [
                row for row in related
                if row.get("record_type") == "CAUSAL_REPO_INVESTIGATION_V60B"
            ]
            final_triages = [
                row for row in related
                if row.get("record_type") == "AUTONOMOUS_FAILURE_TRIAGE_V58A"
            ]
            final_classifications = sorted(
                {
                    _clean(row.get("classification"))
                    for row in [*final_investigations, *final_triages]
                    if _clean(row.get("classification"))
                }
            )
            final_regressions: list[str] = []
            current_candidates: list[str] = []
            for row in final_investigations:
                final_regressions.extend(_regressions(row))
                current_candidates.extend(_candidate_paths(row))
            for row in final_triages:
                final_regressions.extend(_regressions(row))

            final_signatures: list[dict[str, str]] = []
            seen_signatures: set[tuple[str, str]] = set()
            for row in [*final_triages, final_verdict]:
                for signature in _signatures(row):
                    key = (
                        signature["signature_sha256"],
                        signature["classification"],
                    )
                    if key in seen_signatures:
                        continue
                    seen_signatures.add(key)
                    final_signatures.append(signature)

            changed = [
                _clean(value)
                for value in final_repair.get("changed_files", [])
                if _clean(value)
            ]
            successful_repairs.append(
                {
                    "repository": repository,
                    "root_episode_key": episode_key,
                    "work_item_id": final_work_item,
                    "repair_identity_sha256": final_binding,
                    "files": list(dict.fromkeys(changed)),
                    "current_candidate_files": list(dict.fromkeys(current_candidates)),
                    "required_regressions": list(dict.fromkeys(final_regressions)),
                    "classifications": final_classifications or classifications,
                    "failure_signatures": final_signatures,
                    "source_refs": sorted(
                        set(
                            _source_refs([final_repair, final_verdict])
                            + _source_refs(final_investigations)
                            + _source_refs(final_triages)
                        )
                    ),
                }
            )

    episodes.sort(
        key=lambda row: (
            row["outcome"] != "VERIFIED_PASS",
            row["repository"],
            row["episode_key"],
        )
    )
    truncated = len(episodes) > limit
    episodes = episodes[:limit]

    retained_keys = {
        (row["repository"], row["episode_key"])
        for row in episodes
    }
    successful_repairs = [
        row for row in successful_repairs
        if (row["repository"], row["root_episode_key"]) in retained_keys
    ]

    stop_counts = Counter(
        reason
        for row in episodes
        for reason in row["stop_reasons"]
    )
    pattern_threshold = int(contract["pattern3_threshold"])
    policy_observations = [
        {
            "reason_code": reason,
            "occurrences": count,
            "classification": (
                "PATTERN_3_REVIEW"
                if count >= pattern_threshold
                else "OBSERVE"
            ),
            "automatic_policy_change": False,
        }
        for reason, count in sorted(
            stop_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    payload = {
        "schema_version": 1,
        "record_type": "AGENT_EPISODIC_MEMORY_V60F",
        "authority": "ADVISORY_RANKING_ONLY",
        "episode_count": len(episodes),
        "truncated": truncated,
        "episodes": episodes,
        "successful_repairs": successful_repairs,
        "policy_observations": policy_observations,
        "guardrails": {
            "derived_rebuildable_noncanonical": True,
            "source_records_remain_authoritative": True,
            "can_add_causal_candidate": False,
            "can_raise_autonomy_eligibility": False,
            "can_modify_policy": False,
            "can_modify_factory_core": False,
            "can_modify_guardrails": False,
            "can_mint_pass_or_certified": False,
            "can_automatically_change_code": False,
        },
    }
    payload["memory_digest_sha256"] = _digest(
        {
            "episodes": episodes,
            "successful_repairs": successful_repairs,
            "policy_observations": policy_observations,
        }
    )
    return payload


def rank_strategies(
    memory: dict[str, Any],
    *,
    repository: str,
    classification: str,
    failure_signature: str = "",
    candidate_files: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    contract = load_contract()
    max_results = int(contract["max_strategy_results"])
    result_limit = max_results if limit is None else max(1, min(int(limit), max_results))
    current_candidates = {
        _clean(path) for path in (candidate_files or []) if _clean(path)
    }
    ranked: list[dict[str, Any]] = []

    for repair in memory.get("successful_repairs", []):
        if not isinstance(repair, dict):
            continue
        score = 0
        reasons: list[str] = []
        if _clean(repair.get("repository")) == repository:
            score += 35
            reasons.append("same repository")
        classifications = {
            _clean(value)
            for value in repair.get("classifications", [])
            if _clean(value)
        }
        if classification and classification in classifications:
            score += 25
            reasons.append("same failure classification")
        signatures = {
            _clean(row.get("signature_sha256")).lower()
            for row in repair.get("failure_signatures", [])
            if isinstance(row, dict)
        }
        signature = _clean(failure_signature).lower()
        if signature and signature in signatures:
            score += 60
            reasons.append("exact prior failure signature")
        historical_files = {
            _clean(path)
            for path in repair.get("files", [])
            if _clean(path)
        }
        overlap = sorted(current_candidates & historical_files)
        if overlap:
            score += min(30, 10 * len(overlap))
            reasons.append("current candidate overlap")
        if score <= 0:
            continue
        ranked.append(
            {
                "score": score,
                "repository": repair.get("repository"),
                "work_item_id": repair.get("work_item_id"),
                "repair_identity_sha256": repair.get("repair_identity_sha256"),
                "matched_current_candidates": overlap,
                "required_regressions": repair.get("required_regressions", []),
                "source_refs": repair.get("source_refs", []),
                "reasons": reasons,
            }
        )

    ranked.sort(
        key=lambda row: (
            -int(row["score"]),
            str(row.get("repository") or ""),
            str(row.get("work_item_id") or ""),
        )
    )
    return {
        "schema_version": 1,
        "record_type": "AGENT_MEMORY_STRATEGY_RANKING_V60F",
        "authority": "ADVISORY_RANKING_ONLY",
        "repository": repository,
        "classification": classification,
        "failure_signature": failure_signature,
        "strategies": ranked[:result_limit],
        "guardrails": {
            "historical_files_not_in_current_candidates_are_not_returned": True,
            "can_add_causal_candidate": False,
            "can_raise_autonomy_eligibility": False,
            "automatic_code_change": False,
            "automatic_policy_change": False,
        },
    }


def self_test() -> None:
    root_work = "wrk_root"
    second_work = "wrk_second"
    repair1 = {
        "schema_version": 1,
        "record_type": "BOUNDED_FIX_RESULT_V60C",
        "authority": "BRANCH_WORKSPACE_ONLY",
        "state": "READY_FOR_VERIFICATION",
        "repository": "owner/app",
        "resolved_sha": "a" * 40,
        "work_item_id": root_work,
        "attempt_number": 1,
        "patch_sha256": "1" * 64,
        "result_patch_sha256": "2" * 64,
        "changed_files": ["lib/first.dart"],
        "additions": 1,
        "deletions": 1,
        "changed_lines": 2,
        "_source_ref": "repair-1.json",
    }
    repair2 = {
        **repair1,
        "resolved_sha": "b" * 40,
        "work_item_id": second_work,
        "attempt_number": 2,
        "patch_sha256": "3" * 64,
        "result_patch_sha256": "4" * 64,
        "changed_files": ["lib/final.dart", "test/final_test.dart"],
        "_source_ref": "repair-2.json",
    }
    final_binding = repair_loop.repair_identity(repair2)
    records = [
        {
            "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
            "repository": "owner/app",
            "work_item_id": root_work,
            "resolved_sha": "a" * 40,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "ranked_candidate_files": [{"path": "lib/first.dart"}],
            "required_regression_targets": ["test/first_test.dart"],
            "_source_ref": "investigation-1.json",
        },
        repair1,
        {
            "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
            "repository": "owner/app",
            "work_item_id": second_work,
            "resolved_sha": "b" * 40,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "ranked_candidate_files": [{"path": "lib/final.dart"}],
            "required_regression_targets": ["test/final_test.dart"],
            "_source_ref": "investigation-2.json",
        },
        repair2,
        {
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "repository": "owner/app",
            "root_work_item_id": root_work,
            "root_resolved_sha": "a" * 40,
            "state": "COMPLETE",
            "reason_code": "VERIFIED_PASS",
            "repair_attempt_count": 2,
            "repair_identity_sha256": final_binding,
            "attempt_signatures": [
                {
                    "signature_sha256": "sha256:" + "5" * 64,
                    "classification": "BUILD_OR_QUALITY_FAILURE",
                }
            ],
            "_source_ref": "verdict.json",
        },
    ]
    memory = build_memory(records)
    assert len(memory["successful_repairs"]) == 1
    success = memory["successful_repairs"][0]
    assert success["work_item_id"] == second_work
    assert success["files"] == ["lib/final.dart", "test/final_test.dart"]
    assert "lib/first.dart" not in success["files"]

    ranking = rank_strategies(
        memory,
        repository="owner/app",
        classification="BUILD_OR_QUALITY_FAILURE",
        failure_signature="sha256:" + "5" * 64,
        candidate_files=["lib/final.dart", "lib/unrelated.dart"],
    )
    top = ranking["strategies"][0]
    assert top["matched_current_candidates"] == ["lib/final.dart"]
    assert "lib/unrelated.dart" not in top["matched_current_candidates"]
    assert ranking["guardrails"]["can_add_causal_candidate"] is False
    print("AppLab v6.0F agent episodic memory self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default="")
    parser.add_argument("--memory", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--classification", default="")
    parser.add_argument("--failure-signature", default="")
    parser.add_argument("--candidate-file", action="append", default=[])
    parser.add_argument("--max-episodes", type=int, default=0)
    parser.add_argument("--output", default="")
    parser.add_argument("--rank", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    if args.rank:
        if not args.memory:
            raise SystemExit("--memory is required with --rank")
        memory = json.loads(Path(args.memory).read_text(encoding="utf-8"))
        if not isinstance(memory, dict):
            raise SystemExit("--memory JSON root must be an object")
        report = rank_strategies(
            memory,
            repository=args.repository,
            classification=args.classification,
            failure_signature=args.failure_signature,
            candidate_files=args.candidate_file,
        )
    else:
        if not args.history_dir:
            raise SystemExit("--history-dir is required")
        report = build_memory(
            _read_records(Path(args.history_dir)),
            max_episodes=args.max_episodes or None,
        )

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
