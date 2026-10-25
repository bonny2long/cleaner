from __future__ import annotations

from collections import Counter

from .classifier import ClassificationContext, classify_items
from .config import CleanerConfig
from .evidence import evidence_index
from .models import CleanerPlan, PlannedAction
from .reports import run_id, utc_now_iso
from .scanner import scan_cleanup_candidates, scan_quarantine_discards


def _action_for_category(config: CleanerConfig, category: str) -> tuple[str, str]:
    if category == "safe_empty_folder":
        if config.dry_run:
            return "remove_empty_folder_dry_run", "allowed_in_dry_run_only"
        if config.mode == "production" and config.destructive_actions_enabled and config.allow_empty_folder_removal:
            return "remove_empty_folder", "allowed_by_production_gates"
        return "blocked_no_action", "blocked_by_config"
    if category == "known_harmless_trash":
        if config.dry_run:
            return "known_trash_report_only", "report_only_mvp"
        if config.mode == "production" and config.destructive_actions_enabled and config.allow_known_trash_delete:
            return "delete_known_trash", "allowed_by_production_gates"
        return "blocked_no_action", "blocked_by_config"
    if category == "uncertain_leftover":
        return "report_only", "leave_visible_for_review"
    # Picked up for cleanup, but nothing can act on them until the 14-day trash hold exists.
    if category in {"verified_duplicate", "quarantine_discard_approved"}:
        return "report_only", "awaiting_trash_hold"
    if category == "unrecorded_leftover":
        return "report_only", "needs_your_decision"
    if category in {"quarantine_hold", "do_not_touch"}:
        return "report_only", "protected_path"
    if category.startswith("blocked_"):
        return "blocked_no_action", category
    return "report_only", "no_action_default"


def build_plan(
    config: CleanerConfig,
    write_report: bool = False,
    evidence_max_age_seconds: float = 0,
    hash_budget_seconds: float | None = None,
) -> CleanerPlan:
    """Build a plan.

    Evidence is read fresh unless the caller (the dashboard) allows a short-lived cache. Content
    hashing is unlimited unless the caller (the dashboard) passes a small time budget.
    """
    config.validate()
    config.ensure_shared_directories()
    evidence = evidence_index(config, max_age_seconds=evidence_max_age_seconds)
    context = ClassificationContext(config, hash_budget_seconds=hash_budget_seconds)
    items = scan_cleanup_candidates(config)
    items.extend(scan_quarantine_discards(config, list(context.discards)))
    classified = classify_items(config, items, evidence, context)

    actions: list[PlannedAction] = []
    counts: Counter[str] = Counter()
    for item, classification in classified:
        counts[classification.category] += 1
        action, safety_status = _action_for_category(config, classification.category)
        actions.append(
            PlannedAction(
                action=action,
                path=item.path,
                relative_path=item.relative_path,
                category=classification.category,
                safety_status=safety_status,
                reason=classification.reason,
                severity=classification.severity,
                evidence=classification.evidence,
                details=classification.details,
            )
        )

    counts["actions_planned"] = len(actions)
    counts["blocked"] = sum(value for key, value in counts.items() if key.startswith("blocked_"))
    counts["protected"] = counts.get("do_not_touch", 0) + counts.get("quarantine_hold", 0)
    counts["evidence_records"] = len(evidence)

    return CleanerPlan(
        run_id=run_id(),
        created_at=utc_now_iso(),
        mode=config.mode,
        dry_run=config.dry_run,
        data_root=str(config.data_root),
        min_age_days=config.min_age_days,
        items_scanned=len(items),
        evidence_records=len(evidence),
        actions=actions,
        counts=dict(counts),
    )
