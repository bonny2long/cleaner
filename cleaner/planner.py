from __future__ import annotations

from collections import Counter

from .classifier import classify_items
from .config import CleanerConfig
from .evidence import evidence_index
from .models import CleanerPlan, PlannedAction
from .reports import run_id, utc_now_iso
from .scanner import scan_cleanup_candidates


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
        if config.allow_leftover_review_moves and not config.dry_run and not config.destructive_actions_enabled:
            # Moving leftovers is non-destructive, but still disabled in MVP unless explicitly enabled later.
            return "move_to_leftover_review", "allowed_non_destructive_move"
        if config.allow_leftover_review_moves and config.dry_run:
            return "move_to_leftover_review_dry_run", "allowed_in_dry_run_only"
        return "report_only", "leave_visible_for_review"
    if category in {"quarantine_hold", "do_not_touch"}:
        return "report_only", "protected_path"
    if category.startswith("blocked_"):
        return "blocked_no_action", category
    return "report_only", "no_action_default"


def build_plan(config: CleanerConfig, write_report: bool = False) -> CleanerPlan:
    config.validate()
    config.ensure_shared_directories()
    evidence = evidence_index(config)
    items = scan_cleanup_candidates(config)
    classified = classify_items(config, items, evidence)

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
