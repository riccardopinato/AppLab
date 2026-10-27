#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MAX_EPISODES_DEFAULT = 500
SUPPORTED_TYPES = {
    "AUTONOMOUS_FAILURE_TRIAGE_V58A",
    "CAUSAL_REPO_INVESTIGATION_V60B",
    "BOUNDED_FIX_RESULT_V60C",
    "VERIFY_REPAIR_LOOP_DECISION_V60D",
}


class MemoryError(ValueError):
    pass


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


def _read_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict):
                continue
            if value.get("record_type") not in SUPPORTED_TYPES:
                continue
            row = dict(value)
            row["_source_ref"] = path.relative_to(root).as_posix()
            records.append(row)
    return records


def _key(record: dict[str, Any]) -> tuple[str, str]:
    repository = _clean(record.get("repository"))
    work_item_id = _clean(
        record.get("work_item_id") or record.get("root_work_item_id")
    )
    if not work_item_id:
        resolved = _clean(
            record.get("resolved_sha") or record.get("root_resolved_sha")
        )
        work_item_id = f"sha:{resolved}" if resolved else "unknown"
    return repository, work_item_id


def _paths_from_investigation(record: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    rows = record.get("ranked_candidate_files")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = _clean(row.get("path"))
            if path:
                paths.append(path)
    return list(dict.fromkeys(paths))


def _regressions(record: dict[str, Any]) -> list[str]:
    values = record.get("required_regression_targets")
    if not isinstance(values, list):
        values = record.get("required_regression_evidence")
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(_clean(value) for value in values if _clean(value)))


def _failure_signatures(record: dict[str, Any]) -> list[dict[str, str]]:
    rows = record.get("attempt_signatures")
    if not isinstance(rows, list):
        return []
    result: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        signature = _clean(row.get("signature_sha256"))
        classification = _clean(row.get("classification"))
        if signature:
            result.append(
                {
                    "signature_sha256": signature,
                    "classification": classification,
                }
            )
    return result


def build_memory(
    records: list[dict[str, Any]],
    *,
    max_episodes: int = MAX_EPISODES_DEFAULT,
) -> dict[str, Any]:
    if max_episodes < 1:
        raise MemoryError("max_episodes must be >= 1")

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_key(record)].append(record)

    episodes: list[dict[str, Any]] = []
    for (repository, work_item_id), rows in grouped.items():
        if not repository:
            continue
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
        triages = [
            row for row in rows
            if row.get("record_type") == "AUTONOMOUS_FAILURE_TRIAGE_V58A"
        ]

        candidate_files: list[str] = []
        regressions: list[str] = []
        for row in investigations:
            candidate_files.extend(_paths_from_investigation(row))
            regressions.extend(_regressions(row))
        for row in triages:
            regressions.extend(_regressions(row))

        changed_files: list[str] = []
        for repair in repairs:
            values = repair.get("changed_files")
            if isinstance(values, list):
                changed_files.extend(
                    _clean(value) for value in values if _clean(value)
                )

        classifications = [
            _clean(row.get("classification"))
            for row in [*triages, *investigations]
            if _clean(row.get("classification"))
        ]
        signatures: list[dict[str, str]] = []
        for verdict in verdicts:
            signatures.extend(_failure_signatures(verdict))

        complete = any(
            row.get("state") == "COMPLETE"
            and row.get("reason_code") == "VERIFIED_PASS"
            for row in verdicts
        )
        stop_reasons = list(
            dict.fromkeys(
                _clean(row.get("reason_code"))
                for row in verdicts
                if row.get("state") == "STOPPED"
                and _clean(row.get("reason_code"))
            )
        )

        source_refs = sorted(
            {
                _clean(row.get("_source_ref"))
                for row in rows
                if _clean(row.get("_source_ref"))
            }
        )
        resolved_shas = sorted(
            {
                _clean(row.get("resolved_sha") or row.get("root_resolved_sha"))
                for row in rows
                if _clean(row.get("resolved_sha") or row.get("root_resolved_sha"))
            }
        )

        episode = {
            "repository": repository,
            "work_item_id": work_item_id,
            "classifications": sorted(set(classifications)),
            "failure_signatures": signatures,
            "candidate_files": list(dict.fromkeys(candidate_files)),
            "changed_files": list(dict.fromkeys(changed_files)),
            "required_regressions": list(dict.fromkeys(regressions)),
            "outcome": "VERIFIED_PASS" if complete else (
                "STOPPED" if stop_reasons else "INCOMPLETE"
            ),
            "stop_reasons": stop_reasons,
            "resolved_shas": resolved_shas,
            "source_refs": source_refs,
        }
        episode["episode_digest_sha256"] = _digest(episode)
        episodes.append(episode)

    episodes.sort(
        key=lambda row: (
            row["outcome"] != "VERIFIED_PASS",
            row["repository"],
            row["work_item_id"],
        )
    )
    truncated = len(episodes) > max_episodes
    episodes = episodes[:max_episodes]

    successful_repairs = [
        {
            "repository": row["repository"],
            "work_item_id": row["work_item_id"],
            "files": row["changed_files"] or row["candidate_files"],
            "required_regressions": row["required_regressions"],
            "failure_signatures": row["failure_signatures"],
            "source_refs": row["source_refs"],
        }
        for row in episodes
        if row["outcome"] == "VERIFIED_PASS"
        and (row["changed_files"] or row["candidate_files"])
    ]

    stop_counts = Counter(
        reason
        for row in episodes
        for reason in row["stop_reasons"]
    )
    policy_observations = [
        {
            "reason_code": reason,
            "occurrences": count,
            "classification": (
                "PATTERN_3_REVIEW"
                if count >= 3
                else "OBSERVE"
            ),
            "automatic_policy_change": False,
        }
        for reason, count in sorted(
            stop_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]

    result = {
        "schema_version": 1,
        "record_type": "AGENT_EPISODIC_MEMORY_V60F",
        "authority": "ADVISORY_RANKING_ONLY",
        "episode_count": len(episodes),
        "truncated": truncated,
        "episodes": episodes,
        "successful_repairs": successful_repairs,
        "policy_observations": policy_observations,
        "guardrails": {
            "can_modify_policy": False,
            "can_modify_factory_core": False,
            "can_modify_guardrails": False,
            "can_mint_pass_or_certified": False,
            "source_records_remain_authoritative": True,
        },
    }
    result["memory_digest_sha256"] = _digest(
        {
            "episodes": episodes,
            "successful_repairs": successful_repairs,
            "policy_observations": policy_observations,
        }
    )
    return result


def rank_strategies(
    memory: dict[str, Any],
    *,
    repository: str,
    classification: str,
    failure_signature: str = "",
    candidate_files: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    candidate_set = set(candidate_files or [])
    ranked: list[dict[str, Any]] = []
    for episode in memory.get("episodes", []):
        if not isinstance(episode, dict):
            continue
        if episode.get("outcome") != "VERIFIED_PASS":
            continue
        score = 0
        reasons: list[str] = []
        if episode.get("repository") == repository:
            score += 35
            reasons.append("same repository")
        if classification and classification in episode.get("classifications", []):
            score += 25
            reasons.append("same failure classification")
        signatures = {
            _clean(row.get("signature_sha256"))
            for row in episode.get("failure_signatures", [])
            if isinstance(row, dict)
        }
        if failure_signature and failure_signature in signatures:
            score += 60
            reasons.append("exact prior failure signature")
        paths = set(episode.get("changed_files", [])) | set(
            episode.get("candidate_files", [])
        )
        overlap = sorted(candidate_set & paths)
        if overlap:
            score += min(30, 10 * len(overlap))
            reasons.append("candidate-path overlap")
        if score <= 0:
            continue
        ranked.append(
            {
                "score": score,
                "repository": episode.get("repository"),
                "work_item_id": episode.get("work_item_id"),
                "files": episode.get("changed_files")
                or episode.get("candidate_files")
                or [],
                "required_regressions": episode.get("required_regressions", []),
                "source_refs": episode.get("source_refs", []),
                "reasons": reasons,
                "candidate_overlap": overlap,
            }
        )
    ranked.sort(
        key=lambda row: (
            -int(row["score"]),
            str(row["repository"]),
            str(row["work_item_id"]),
        )
    )
    return {
        "schema_version": 1,
        "record_type": "AGENT_MEMORY_STRATEGY_RANKING_V60F",
        "authority": "ADVISORY_RANKING_ONLY",
        "repository": repository,
        "classification": classification,
        "failure_signature": failure_signature,
        "strategies": ranked[: max(1, limit)],
        "automatic_code_change": False,
        "automatic_policy_change": False,
    }


def self_test() -> None:
    records = [
        {
            "record_type": "CAUSAL_REPO_INVESTIGATION_V60B",
            "repository": "owner/app",
            "work_item_id": "wrk_1",
            "resolved_sha": "a" * 40,
            "classification": "BUILD_OR_QUALITY_FAILURE",
            "ranked_candidate_files": [
                {"path": "lib/client.dart"},
                {"path": "test/client_test.dart"},
            ],
            "required_regression_targets": ["test/client_test.dart"],
            "_source_ref": "investigation.json",
        },
        {
            "record_type": "BOUNDED_FIX_RESULT_V60C",
            "repository": "owner/app",
            "work_item_id": "wrk_1",
            "resolved_sha": "a" * 40,
            "changed_files": ["lib/client.dart", "test/client_test.dart"],
            "_source_ref": "repair.json",
        },
        {
            "record_type": "VERIFY_REPAIR_LOOP_DECISION_V60D",
            "repository": "owner/app",
            "root_work_item_id": "wrk_1",
            "root_resolved_sha": "a" * 40,
            "state": "COMPLETE",
            "reason_code": "VERIFIED_PASS",
            "attempt_signatures": [
                {
                    "signature_sha256": "sha256:abc",
                    "classification": "BUILD_OR_QUALITY_FAILURE",
                }
            ],
            "_source_ref": "verdict.json",
        },
    ]
    memory = build_memory(records)
    assert memory["episode_count"] == 1
    assert memory["successful_repairs"][0]["files"] == [
        "lib/client.dart",
        "test/client_test.dart",
    ]
    ranking = rank_strategies(
        memory,
        repository="owner/app",
        classification="BUILD_OR_QUALITY_FAILURE",
        failure_signature="sha256:abc",
        candidate_files=["lib/client.dart"],
    )
    assert ranking["strategies"][0]["score"] >= 100
    assert ranking["automatic_policy_change"] is False
    print("AppLab v6.0F agent episodic memory self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", default="")
    parser.add_argument("--memory", default="")
    parser.add_argument("--repository", default="")
    parser.add_argument("--classification", default="")
    parser.add_argument("--failure-signature", default="")
    parser.add_argument("--candidate-file", action="append", default=[])
    parser.add_argument("--max-episodes", type=int, default=MAX_EPISODES_DEFAULT)
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
            max_episodes=args.max_episodes,
        )

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
