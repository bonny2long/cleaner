from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CleanerConfig
from .models import CleanerPlan, PlannedAction
from .reports import append_jsonl, read_json, run_id, utc_now_iso, write_json
from .scanner import _dir_stats
from .trash import (
    TrashError,
    move_to_trash,
    purge_enabled,
    purge_entry,
    restore_entry,
    trash_category_enabled,
    trash_enabled,
)


# Empty-folder removal is only ever allowed inside these lanes. Quarantine,
# incoming, intake-processing, leftover-review, and final libraries are never
# cleanup roots.
EMPTY_FOLDER_CLEANUP_AREAS = ("_INGEST/ready", "_INGEST/failed", "_STAGING")
REVIEWED_PLAN_MAX_AGE_SECONDS = 24 * 60 * 60
RUN_ID_PATTERN = re.compile(r"^cleaner-\d{8}-\d{6}$")


class CleanerExecutionError(RuntimeError):
    pass


def execution_enabled(config: CleanerConfig) -> bool:
    """True only when every gate for the first real action is open."""
    return (
        config.mode == "production"
        and not config.dry_run
        and config.destructive_actions_enabled
        and config.allow_empty_folder_removal
    )


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _check_empty_folder_target(config: CleanerConfig, path: Path) -> None:
    """Fail closed unless ``path`` is a real, empty folder in a cleanup lane."""
    roots = [config.data_root / area for area in EMPTY_FOLDER_CLEANUP_AREAS]
    matching = [root for root in roots if _inside(path, root)]
    if not matching:
        raise CleanerExecutionError(f"Not inside an allowed cleanup lane: {path}")
    if any(path.resolve() == root.resolve() for root in matching):
        raise CleanerExecutionError(f"Refusing to remove a lane root: {path}")
    if _inside(path, config.quarantine_dir) or _inside(path, config.leftover_review_dir):
        raise CleanerExecutionError(f"Refusing a protected path: {path}")
    if _is_link(path):
        raise CleanerExecutionError(f"Refusing a link or junction: {path}")
    if not path.is_dir():
        raise CleanerExecutionError(f"Not a directory: {path}")
    for root, dirs, files in os.walk(path):
        if files:
            raise CleanerExecutionError(f"Refusing to remove folder containing files: {Path(root) / files[0]}")
        for name in dirs:
            if _is_link(Path(root) / name):
                raise CleanerExecutionError(f"Refusing a folder tree containing a link: {Path(root) / name}")


def _remove_empty_tree(path: Path) -> int:
    """Remove an all-empty folder tree bottom-up. Never deletes a file.

    ``rmdir`` itself fails if anything appeared since the check, so a file
    arriving mid-removal stops the operation instead of being deleted.
    """
    removed = 0
    for root, dirs, _files in os.walk(path, topdown=False):
        for name in dirs:
            (Path(root) / name).rmdir()
            removed += 1
    path.rmdir()
    return removed + 1


def _remove_empty_folder(config: CleanerConfig, action: PlannedAction) -> dict:
    path = Path(action.path)
    if not path.exists():
        return {"action": action.action, "path": action.path, "status": "skipped_missing"}
    _check_empty_folder_target(config, path)
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    folders_removed = _remove_empty_tree(path)
    return {
        "action": action.action,
        "path": action.path,
        "relative_path": action.relative_path,
        "status": "removed_empty_folder",
        "folders_removed": folders_removed,
        "folder_modified_at": modified.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "evidence_manifest": action.evidence.manifest_path if action.evidence else None,
    }


def load_reviewed_plan(config: CleanerConfig, run_id: str) -> dict[str, Any]:
    """Load a written plan report the user reviewed, refusing stale or odd ids."""
    if not RUN_ID_PATTERN.match(run_id or ""):
        raise CleanerExecutionError("Invalid reviewed plan id")
    reviewed = read_json(config.cleaner_reports_dir / f"{run_id}.json")
    if not isinstance(reviewed, dict) or reviewed.get("run_id") != run_id:
        raise CleanerExecutionError(f"Reviewed plan not found: {run_id}")
    try:
        created = datetime.fromisoformat(str(reviewed.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CleanerExecutionError("Reviewed plan has no valid creation time") from exc
    age = (datetime.now(timezone.utc) - created).total_seconds()
    if age > REVIEWED_PLAN_MAX_AGE_SECONDS:
        raise CleanerExecutionError("Reviewed plan is older than 24 hours; write a new plan and review it")
    return reviewed


def _reviewed_keys(reviewed: dict[str, Any] | None) -> set[tuple[str, str, str]] | None:
    if reviewed is None:
        return None
    return {
        (str(item.get("action")), str(item.get("path")), str(item.get("category")))
        for item in reviewed.get("actions", [])
        if isinstance(item, dict)
    }


def execute_plan(
    config: CleanerConfig,
    plan: CleanerPlan,
    reviewed: dict[str, Any] | None = None,
) -> list[dict]:
    """Execute only explicitly allowed production actions.

    ``plan`` must be freshly built. When ``reviewed`` is given, an action runs
    only if the same action, path, and category also appear in that reviewed
    plan, so nothing the user did not see can be acted on.
    """
    config.validate()
    if config.dry_run or not config.destructive_actions_enabled or config.mode != "production":
        raise CleanerExecutionError("Execution blocked: production mode, DRY_RUN=false, and DESTRUCTIVE_ACTIONS_ENABLED=true are required")

    allowed = _reviewed_keys(reviewed)
    results: list[dict] = []
    for action in plan.actions:
        if action.action != "remove_empty_folder":
            continue
        if allowed is not None and (action.action, action.path, action.category) not in allowed:
            results.append({"action": action.action, "path": action.path, "status": "skipped_not_in_reviewed_plan"})
            continue
        try:
            if not config.allow_empty_folder_removal:
                continue
            results.append(_remove_empty_folder(config, action))
        except (CleanerExecutionError, OSError) as exc:
            results.append({"action": action.action, "path": action.path, "status": "refused", "error": str(exc)})
    append_jsonl(
        config.cleaner_log_path,
        {
            "timestamp": utc_now_iso(),
            "event": "execution_completed",
            "plan_run_id": plan.run_id,
            "reviewed_run_id": reviewed.get("run_id") if reviewed else None,
            "results": results,
        },
    )
    return results


def current_signature(config: CleanerConfig, path: Path) -> dict[str, Any]:
    file_count, _dirs, total_size, max_mtime, *_rest = _dir_stats(path, config)
    return {"file_count": file_count, "total_size_bytes": total_size, "max_modified_time": max_mtime}


def execute_trash_plan(
    config: CleanerConfig,
    plan: CleanerPlan,
    reviewed: dict[str, Any],
    include_paths: set[str] | None = None,
) -> tuple[str, list[dict]]:
    """Move picked-up items into the trash hold. Nothing is deleted.

    ``plan`` must be freshly built, with content re-verified. An item moves only when all of this holds:

    * the same action, path and category appear in the plan you reviewed (so a duplicate whose
      library copy has since vanished, now classified differently, does not move);
    * unrecorded leftovers also appear in ``include_paths``, the ones you ticked;
    * quarantine discards are past their waiting period;
    * the folder looks exactly as it did when classified (file count, bytes, newest change);
    * the trash module accepts the path (right lane, no links, same disk, nothing to overwrite).
    """
    config.validate()
    if not trash_enabled(config):
        raise CleanerExecutionError(
            "Moving to the trash hold is disabled: production mode, DRY_RUN=false, "
            "DESTRUCTIVE_ACTIONS_ENABLED=true and ALLOW_TRASH_HOLD=true are required"
        )
    allowed = _reviewed_keys(reviewed) or set()
    ticked = {str(value).replace("\\", "/").strip("/") for value in (include_paths or set())}
    trash_run = run_id("trash")
    results: list[dict] = []
    for action in plan.actions:
        if action.action != "move_to_trash":
            continue
        base = {"action": action.action, "path": action.path, "relative_path": action.relative_path, "category": action.category}
        if (action.action, action.path, action.category) not in allowed:
            results.append({**base, "status": "skipped_not_in_reviewed_plan"})
            continue
        if not trash_category_enabled(config, action.category):
            results.append({**base, "status": "skipped_category_disabled"})
            continue
        if action.category == "unrecorded_leftover" and action.relative_path not in ticked:
            results.append({**base, "status": "skipped_needs_your_tick"})
            continue
        if action.category == "quarantine_discard_approved" and not (action.details or {}).get("eligible_now"):
            results.append({**base, "status": "skipped_not_yet_eligible"})
            continue
        path = Path(action.path)
        if not path.exists():
            results.append({**base, "status": "skipped_missing"})
            continue
        if action.signature is None or current_signature(config, path) != action.signature:
            results.append({**base, "status": "skipped_changed_since_plan"})
            continue
        details = dict(action.details or {})
        if action.evidence:
            details["evidence_manifest"] = action.evidence.manifest_path
        try:
            entry = move_to_trash(
                config, path, trash_run=trash_run, category=action.category, reason=action.reason, details=details,
            )
        except (TrashError, OSError) as exc:
            results.append({**base, "status": "refused", "error": str(exc)})
            continue
        results.append({
            **base,
            "status": "moved_to_trash",
            "trash_run": trash_run,
            "purge_after": entry["purge_after"],
            "file_count": entry["inventory"]["file_count"],
            "total_bytes": entry["inventory"]["total_bytes"],
        })
    append_jsonl(
        config.cleaner_log_path,
        {
            "timestamp": utc_now_iso(),
            "event": "trash_move_completed",
            "trash_run": trash_run,
            "plan_run_id": plan.run_id,
            "reviewed_run_id": reviewed.get("run_id"),
            "results": results,
        },
    )
    return trash_run, results


def write_trash_report(config: CleanerConfig, trash_run: str, reviewed_run_id: str, results: list[dict]) -> str:
    path = config.cleaner_reports_dir / f"trash-{trash_run}.json"
    write_json(
        path,
        {
            "trash_run": trash_run,
            "reviewed_run_id": reviewed_run_id,
            "executed_at": utc_now_iso(),
            "data_root": str(config.data_root),
            "trash_dir": str(config.trash_dir),
            "moved": [item for item in results if item.get("status") == "moved_to_trash"],
            "refused": [item for item in results if item.get("status") == "refused"],
            "skipped": [item for item in results if str(item.get("status", "")).startswith("skipped")],
        },
    )
    return str(path)


def restore_from_trash(config: CleanerConfig, trash_run: str, relative_path: str) -> dict[str, Any]:
    """Put a held item back where it came from. Always available: it deletes nothing."""
    entry = restore_entry(config, trash_run, relative_path)
    append_jsonl(
        config.cleaner_log_path,
        {"timestamp": utc_now_iso(), "event": "trash_restored", "trash_run": trash_run, "relative_path": relative_path},
    )
    return entry


def purge_trash(config: CleanerConfig, requested: list[dict[str, Any]]) -> tuple[str, list[dict]]:
    """Delete expired held items for good. Needs ALLOW_TRASH_PURGE and the list you chose."""
    config.validate()
    if not purge_enabled(config):
        raise CleanerExecutionError(
            "Purging is disabled: production mode, DRY_RUN=false, "
            "DESTRUCTIVE_ACTIONS_ENABLED=true and ALLOW_TRASH_PURGE=true are required"
        )
    purge_id = run_id("purge")
    results: list[dict] = []
    for item in requested:
        trash_run = str(item.get("trash_run") or "")
        relative_path = str(item.get("relative_path") or "")
        try:
            entry = purge_entry(config, trash_run, relative_path)
        except (TrashError, OSError) as exc:
            results.append({"trash_run": trash_run, "relative_path": relative_path, "status": "refused", "error": str(exc)})
            continue
        results.append({
            "trash_run": trash_run,
            "relative_path": relative_path,
            "status": "purged",
            "file_count": entry.get("purged_file_count"),
            "total_bytes": entry.get("purged_bytes"),
            "category": entry.get("category"),
            "moved_at": entry.get("moved_at"),
        })
    write_json(
        config.cleaner_reports_dir / f"{purge_id}.json",
        {"purge_id": purge_id, "executed_at": utc_now_iso(), "results": results},
    )
    append_jsonl(config.cleaner_log_path, {"timestamp": utc_now_iso(), "event": "trash_purged", "purge_id": purge_id, "results": results})
    return purge_id, results


def write_execution_report(config: CleanerConfig, plan: CleanerPlan, reviewed_run_id: str, results: list[dict]) -> str:
    """Record exactly what was done so any removed folder can be recreated."""
    path = config.cleaner_reports_dir / f"execution-{plan.run_id}.json"
    write_json(
        path,
        {
            "execution_run_id": plan.run_id,
            "reviewed_run_id": reviewed_run_id,
            "executed_at": utc_now_iso(),
            "data_root": str(config.data_root),
            "removed": [item for item in results if item.get("status") == "removed_empty_folder"],
            "refused": [item for item in results if item.get("status") == "refused"],
            "skipped": [item for item in results if str(item.get("status", "")).startswith("skipped")],
        },
    )
    return str(path)
