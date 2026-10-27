#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import verify_repair_loop_v60d as loopmod

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = ROOT / "integration" / "orchestration" / "contracts" / "agent-episodic-memory-v1.json"


class MemoryError(ValueError):
    pass


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise MemoryError("unsupported episodic memory contract version")
    if payload.get("contract_name") != "APPLAB_AGENT_EPISODIC_MEMORY":
        raise MemoryError("unexpected episodic memory contract")
    if payload.get("authority") != "ADVISORY_STRATEGY_RANKING_ONLY":
        raise MemoryError("episodic memory authority must remain advisory")
    return payload


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(x for x in values if x))


def _source_record(name: str, payload: dict[str, Any]) -> dict[str, str]:
    return {
        "name": name,
        "digest_sha256": _digest(payload),
        "record_type": str(payload.get("record_type") or ""),
    }


def build_episode(
    triage: dict[str, Any],
    investigation: dict[str, Any],
    attempts: list[dict[str, Any]],
    loop_decision: dict[str, Any],
) -> dict[str, Any]:
    repository = str(
        loop_decision.get("repository")
        or triage.get("repository")
        or investigation.get("repository")
        or ""
    )
    source_sha = str(
        loop_decision.get("resolved_sha")
        or triage.get("resolved_sha")
        or investigation.get("resolved_sha")
        or ""
    ).lower()
    failure_class = str(
        triage.get("classification")
        or (loop_decision.get("attempt_signatures") or [{}])[0].get("classification")
        or "UNKNOWN_FAILURE"
    )
    signatures = [
        str(row.get("signature_sha256") or "")
        for row in loop_decision.get("attempt_signatures", [])
        if isinstance(row, dict)
    ]
    failure_signature = signatures[0] if signatures else _digest(
        {
            "failure_class": failure_class,
            "failed_labs": sorted(str(x) for x in triage.get("failed_labs", []) if str(x)),
            "hypotheses": triage.get("root_cause_hypotheses", []),
        }
    )
    candidates = [
        str(row.get("path") or "")
        for row in investigation.get("ranked_candidate_files", [])
        if isinstance(row, dict)
    ]
    surfaces = _unique(
        [str(x) for x in triage.get("likely_surfaces", []) if str(x)]
        + [
            str(signal.get("detail") or "")
            for row in investigation.get("ranked_candidate_files", [])
            if isinstance(row, dict)
            for signal in row.get("signals", [])
            if isinstance(signal, dict)
            and signal.get("kind") in {"FAILED_LAB_PATH_SIGNAL", "SURFACE_PATH_SIGNAL"}
        ]
    )
    regression_targets = _unique(
        [str(x) for x in investigation.get("required_regression_targets", []) if str(x)]
        + [str(x) for x in triage.get("required_regression_evidence", []) if str(x)]
    )

    successful_patterns: list[dict[str, Any]] = []
    failed_patterns: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    source_records = [
        _source_record("triage", triage),
        _source_record("investigation", investigation),
        _source_record("loop_decision", loop_decision),
    ]

    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        fix = attempt.get("fix_result") if isinstance(attempt.get("fix_result"), dict) else {}
        applab = attempt.get("applab_verification") if isinstance(attempt.get("applab_verification"), dict) else {}
        focused = attempt.get("focused_verification") if isinstance(attempt.get("focused_verification"), dict) else {}
        number = int(attempt.get("attempt_number", 0) or 0)
        source_records.append(_source_record("attempt_%s" % number, attempt))
        refs = attempt.get("evidence_ref_ids")
        if isinstance(refs, list):
            evidence_refs.extend(str(x) for x in refs if str(x))
        pattern = {
            "attempt_number": number,
            "changed_files": sorted(str(x) for x in fix.get("changed_files", []) if str(x)),
            "patch_sha256": str(fix.get("result_patch_sha256") or fix.get("patch_sha256") or ""),
            "focused_result": str(focused.get("result") or focused.get("status") or ""),
            "applab_result": str(applab.get("result") or applab.get("status") or ""),
        }
        if str(applab.get("result", "")).upper() == "PASS":
            successful_patterns.append(pattern)
        else:
            failed_patterns.append(pattern)

    state = str(loop_decision.get("state") or "")
    reason = str(loop_decision.get("reason_code") or "")
    if state == "COMPLETE" and reason == "VERIFIED_PASS":
        outcome = "PASS"
    elif state == "STOPPED":
        outcome = "STOPPED"
    elif state == "WAITING_EXTERNAL":
        outcome = "BLOCKED"
    elif any(
        str((row.get("applab_verification") or {}).get("result", "")).upper() == "FAIL"
        for row in attempts
        if isinstance(row, dict)
    ):
        outcome = "FAIL"
    else:
        outcome = "UNKNOWN"

    identity = {
        "repository": repository,
        "source_sha": source_sha,
        "failure_signature": failure_signature,
        "outcome": outcome,
        "source_records": source_records,
    }
    episode_id = "ep_" + hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()[:24]
    return {
        "schema_version": 1,
        "record_type": "APPLAB_AGENT_EPISODE",
        "episode_id": episode_id,
        "repository": repository,
        "source_sha": source_sha,
        "failure_signature": failure_signature,
        "failure_class": failure_class,
        "surfaces": surfaces,
        "candidate_files": _unique(candidates),
        "repair_outcome": outcome,
        "successful_patterns": successful_patterns,
        "failed_patterns": failed_patterns,
        "regression_targets": regression_targets,
        "evidence_refs": _unique(evidence_refs),
        "source_records": source_records,
        "guardrails": {
            "verification_authority": "NONE",
            "policy_mutation_authority": "NONE",
            "guardrail_mutation_authority": "NONE",
        },
    }


def validate_episode(episode: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_contract()
    missing = [field for field in contract["required_fields"] if field not in episode]
    if missing:
        raise MemoryError("episode missing fields: " + ", ".join(missing))
    if episode.get("record_type") != contract["record_type"]:
        raise MemoryError("episode record_type mismatch")
    if episode.get("repair_outcome") not in contract["repair_outcomes"]:
        raise MemoryError("invalid repair_outcome")
    if not str(episode.get("episode_id") or "").startswith("ep_"):
        raise MemoryError("invalid episode_id")
    if (episode.get("guardrails") or {}).get("policy_mutation_authority") != "NONE":
        raise MemoryError("episode cannot mutate policy")
    return episode


def merge_memory(existing: dict[str, Any], episodes: list[dict[str, Any]]) -> dict[str, Any]:
    contract = load_contract()
    current = existing.get("episodes") if isinstance(existing.get("episodes"), list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for row in current + episodes:
        if not isinstance(row, dict):
            continue
        validate_episode(row, contract)
        by_id[row["episode_id"]] = row
    ordered = sorted(
        by_id.values(),
        key=lambda row: (row["repository"], row["source_sha"], row["episode_id"]),
    )
    max_episodes = int(contract["max_episodes"])
    if len(ordered) > max_episodes:
        ordered = ordered[-max_episodes:]
    return {
        "schema_version": 1,
        "record_type": "APPLAB_AGENT_MEMORY_V60F",
        "authority": "ADVISORY_STRATEGY_RANKING_ONLY",
        "episodes": ordered,
        "episode_count": len(ordered),
        "rebuildable": True,
        "policy_mutation_authority": "NONE",
        "verification_authority": "NONE",
    }


def query_memory(
    memory: dict[str, Any],
    *,
    repository: str,
    failure_signature: str = "",
    failure_class: str = "",
    surfaces: list[str] | None = None,
    candidate_files: list[str] | None = None,
    allow_cross_repository: bool = False,
) -> dict[str, Any]:
    surfaces = surfaces or []
    candidate_files = candidate_files or []
    surface_set = {x.lower() for x in surfaces}
    file_set = set(candidate_files)
    scored: list[dict[str, Any]] = []
    for episode in memory.get("episodes", []):
        if not isinstance(episode, dict):
            continue
        same_repo = episode.get("repository") == repository
        if not same_repo and not allow_cross_repository:
            continue
        score = 0
        reasons: list[str] = []
        if same_repo:
            score += 40
            reasons.append("SAME_REPOSITORY")
        else:
            reasons.append("CROSS_REPOSITORY_ADVISORY_ONLY")
        if failure_signature and episode.get("failure_signature") == failure_signature:
            score += 100
            reasons.append("EXACT_FAILURE_SIGNATURE")
        if failure_class and episode.get("failure_class") == failure_class:
            score += 25
            reasons.append("SAME_FAILURE_CLASS")
        overlap_surfaces = sorted(surface_set & {str(x).lower() for x in episode.get("surfaces", [])})
        if overlap_surfaces:
            score += min(30, 10 * len(overlap_surfaces))
            reasons.append("SURFACE_OVERLAP")
        overlap_files = sorted(file_set & set(episode.get("candidate_files", [])))
        if overlap_files:
            score += min(30, 10 * len(overlap_files))
            reasons.append("FILE_OVERLAP")
        if episode.get("repair_outcome") == "PASS":
            score += 15
            reasons.append("SUCCESSFUL_PRIOR_REPAIR")
        elif episode.get("repair_outcome") in {"FAIL", "STOPPED"}:
            score += 5
            reasons.append("FAILED_APPROACH_RETained")
        if score <= 0:
            continue
        scored.append(
            {
                "episode_id": episode["episode_id"],
                "repository": episode["repository"],
                "source_sha": episode["source_sha"],
                "score": score,
                "reasons": reasons,
                "repair_outcome": episode["repair_outcome"],
                "successful_patterns": episode["successful_patterns"],
                "failed_patterns": episode["failed_patterns"],
                "regression_targets": episode["regression_targets"],
                "evidence_refs": episode["evidence_refs"],
            }
        )
    scored.sort(key=lambda row: (-row["score"], row["repository"], row["episode_id"]))
    limit = int(load_contract()["max_query_results"])
    return {
        "schema_version": 1,
        "record_type": "APPLAB_AGENT_MEMORY_QUERY_V60F",
        "authority": "ADVISORY_STRATEGY_RANKING_ONLY",
        "repository": repository,
        "allow_cross_repository": allow_cross_repository,
        "results": scored[:limit],
        "policy_mutation_authority": "NONE",
        "verification_authority": "NONE",
    }


def self_test() -> None:
    triage = {
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "classification": "BUILD_OR_QUALITY_FAILURE",
        "likely_surfaces": ["network client"],
        "required_regression_evidence": ["focused network regression"],
    }
    investigation = {
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "ranked_candidate_files": [
            {
                "path": "lib/client.py",
                "signals": [{"kind": "SURFACE_PATH_SIGNAL", "detail": "network client"}],
            }
        ],
        "required_regression_targets": ["tests/test_client.py"],
    }
    fix = loopmod._fix(1)
    attempts = [
        {
            "attempt_number": 1,
            "fix_result": fix,
            "focused_verification": {"result": "PASS"},
            "applab_verification": {"result": "PASS"},
            "evidence_ref_ids": ["ev_fixture"],
        }
    ]
    loop = {
        "repository": "owner/app",
        "resolved_sha": "b" * 40,
        "state": "COMPLETE",
        "reason_code": "VERIFIED_PASS",
        "attempt_signatures": [
            {
                "signature_sha256": "sha256:" + "1" * 64,
                "classification": "BUILD_OR_QUALITY_FAILURE",
            }
        ],
    }
    episode = build_episode(triage, investigation, attempts, loop)
    validate_episode(episode)
    assert episode["repair_outcome"] == "PASS"
    assert episode["successful_patterns"]
    assert episode["evidence_refs"] == ["ev_fixture"]

    memory = merge_memory({"episodes": []}, [episode, episode])
    assert memory["episode_count"] == 1
    query = query_memory(
        memory,
        repository="owner/app",
        failure_signature="sha256:" + "1" * 64,
        failure_class="BUILD_OR_QUALITY_FAILURE",
        surfaces=["network client"],
        candidate_files=["lib/client.py"],
    )
    assert query["results"][0]["episode_id"] == episode["episode_id"]
    assert query["results"][0]["score"] >= 180

    cross = query_memory(
        memory,
        repository="owner/other",
        failure_class="BUILD_OR_QUALITY_FAILURE",
        allow_cross_repository=True,
    )
    assert cross["results"][0]["reasons"][0] == "CROSS_REPOSITORY_ADVISORY_ONLY"
    assert query["policy_mutation_authority"] == "NONE"
    print("AppLab v6.0F episodic agent memory self-test PASS")


def _load(path: str) -> dict[str, Any]:
    if not path:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MemoryError("JSON root must be object: " + path)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--triage", default="")
    parser.add_argument("--investigation", default="")
    parser.add_argument("--attempts", default="")
    parser.add_argument("--loop-decision", default="")
    parser.add_argument("--memory", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.triage, args.investigation, args.loop_decision)):
        raise SystemExit("--triage, --investigation and --loop-decision are required")
    attempts_payload = _load(args.attempts) if args.attempts else {"attempts": []}
    attempts = attempts_payload.get("attempts")
    if not isinstance(attempts, list):
        raise MemoryError("attempts must be a list")
    episode = build_episode(
        _load(args.triage),
        _load(args.investigation),
        attempts,
        _load(args.loop_decision),
    )
    memory = merge_memory(_load(args.memory), [episode])
    rendered = json.dumps(memory, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
