#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    trusted = (ROOT / ".github/workflows/trusted-apk-verifier.yml").read_text(encoding="utf-8")
    review_workflow = (ROOT / ".github/workflows/external-review-watchdog.yml").read_text(encoding="utf-8")
    supersession_workflow = (ROOT / ".github/workflows/supersession-watchdog.yml").read_text(encoding="utf-8")
    live_validation = (ROOT / ".github/workflows/v59e-live-watchdog-validation.yml").read_text(encoding="utf-8")
    review_policy = (ROOT / "scripts/external_review_watchdog_v59e.py").read_text(encoding="utf-8")
    review_reconcile = (ROOT / "scripts/external_review_reconcile_v59e.py").read_text(encoding="utf-8")
    review_support = (ROOT / "scripts/external_review_support_v59e.py").read_text(encoding="utf-8")
    review_config = json.loads((ROOT / "config/external-review-watchdog.json").read_text(encoding="utf-8"))
    supersession_policy = (ROOT / "scripts/supersession_watchdog_v59e.py").read_text(encoding="utf-8")
    warm_policy = (ROOT / "scripts/warm_runtime_route_v59e.py").read_text(encoding="utf-8")
    warm_config = json.loads((ROOT / "config/warm-runtime-production.json").read_text(encoding="utf-8"))
    supersession_config = json.loads((ROOT / "config/supersession-watchdog.json").read_text(encoding="utf-8"))

    require(
        "Record v5.9E primary runtime route" in trusted
        and "Record v5.9E shard runtime route" in trusted
        and "runtime-route-v59e.json" in trusted
        and "Reset primary AVD for cold fallback" in trusted
        and "Reset shard AVD for cold fallback" in trusted
        and "warm_runtime_admitted != 'true'" in trusted,
        "trusted verifier must route AVD reuse, not only label it",
    )
    require(
        '"github_actions_fallback": True' in warm_policy
        and '"coverage_reduction_enabled": False' in warm_policy
        and '"trusted_verifier_authority_unchanged": True' in warm_policy,
        "warm routing must remain orchestration-only with fallback",
    )
    require(
        warm_config.get("global_kill_switch") is False
        and set(warm_config.get("repositories", {}))
        == {"riccardopinato/AppLab", "riccardopinato/Agenda-per-Anna"},
        "warm runtime rollout must remain bounded to AppLab and Anna",
    )

    require(
        "issues: write" in review_workflow
        and "pull-requests: read" in review_workflow
        and "pull-requests: write" not in review_workflow,
        "review watchdog may request review but may not mutate PR findings",
    )
    require(
        '"review_findings_never_auto_resolved": True' in review_policy
        and '"retrigger_is_idempotent_request_only": True' in review_policy,
        "review watchdog must never auto-resolve findings",
    )
    require(
        review_config.get("review_bot_login") == "chatgpt-codex-connector[bot]"
        and review_config.get("watchdog_actor_login") == "github-actions[bot]"
        and "author != review_bot_login" in review_support
        and "author != watchdog_actor_login" in review_support,
        "review watchdog markers must be actor-authenticated",
    )

    protected = set(supersession_config.get("protected_workflow_names", []))
    cancellable = set(supersession_config.get("workflow_names", []))
    require("Production Certification" in protected, "certification must be protected")
    require(not protected & cancellable, "protected workflow cannot be cancellable")
    require(
        'status == "ahead"' in supersession_policy
        and '"ancestry_required": True' in supersession_policy
        and '"cross_repository_cancellation": False' in supersession_policy
        and '"pull_request"' in supersession_policy
        and "head_repository" in supersession_policy
        and "pr_identity" in supersession_policy,
        "supersession requires proven descendant PR/source-repository lineage",
    )
    require(
        "marker_times" in review_support
        and "max(marker_times)" in review_support,
        "review timeout must anchor to trusted review/watchdog activity",
    )
    require(
        "github.paginated_list(" in review_reconcile
        and "max_pages=100" in review_reconcile,
        "review watchdog must evaluate complete bounded PR comment history",
    )
    require(
        "actions: write" in supersession_workflow,
        "supersession watchdog needs bounded Actions cancellation authority",
    )
    require(
        "actions: read" in live_validation
        and "issues: read" in live_validation
        and "pull-requests: read" in live_validation
        and "--dry-run" in live_validation
        and "actions: write" not in live_validation
        and "issues: write" not in live_validation,
        "PR live watchdog validation must remain read-only dry-run evidence",
    )

    print("AppLab v5.9E warm runtime/watchdog contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
