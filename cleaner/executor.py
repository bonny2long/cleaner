from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CleanerConfig
from .models import CleanerPlan, PlannedAction
from .reports import append_jsonl, read_json, utc_now_iso, write_json


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


def _move_to_leftover_review(config: CleanerConfig, action: PlannedAction) -> dict:
    source = Path(action.path)
    destination = config.leftover_review_dir / source.name
    if destination.exists():
        raise CleanerExecutionError(f"Leftover review destination already exists: {destination}")
    config.leftover_review_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return {"action": action.action, "path": action.path, "destination": str(destination), "status": "moved_to_leftover_review"}


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
        if action.action not in {"remove_empty_folder", "move_to_leftover_review"}:
            continue
        if allowed is not None and (action.action, action.path, action.category) not in allowed:
            results.append({"action": action.action, "path": action.path, "status": "skipped_not_in_reviewed_plan"})
            continue
        try:
            if action.action == "remove_empty_folder":
                if not config.allow_empty_folder_removal:
                    continue
                results.append(_remove_empty_folder(config, action))
            elif action.action == "move_to_leftover_review":
                if not config.allow_leftover_review_moves:
                    continue
                results.append(_move_to_leftover_review(config, action))
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
