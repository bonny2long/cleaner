from __future__ import annotations

import shutil
from pathlib import Path

from .config import CleanerConfig
from .models import CleanerPlan, PlannedAction
from .reports import append_jsonl, utc_now_iso


class CleanerExecutionError(RuntimeError):
    pass


def _remove_empty_folder(action: PlannedAction) -> dict:
    path = Path(action.path)
    if not path.exists():
        return {"action": action.action, "path": action.path, "status": "skipped_missing"}
    if not path.is_dir():
        raise CleanerExecutionError(f"Not a directory: {path}")
    if any(path.iterdir()):
        raise CleanerExecutionError(f"Refusing to remove non-empty folder: {path}")
    path.rmdir()
    return {"action": action.action, "path": action.path, "status": "removed_empty_folder"}


def _move_to_leftover_review(config: CleanerConfig, action: PlannedAction) -> dict:
    source = Path(action.path)
    destination = config.leftover_review_dir / source.name
    if destination.exists():
        raise CleanerExecutionError(f"Leftover review destination already exists: {destination}")
    config.leftover_review_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return {"action": action.action, "path": action.path, "destination": str(destination), "status": "moved_to_leftover_review"}


def execute_plan(config: CleanerConfig, plan: CleanerPlan) -> list[dict]:
    """Execute only explicitly allowed production actions.

    MVP is dry-run-first. In development/default config this function refuses to mutate the filesystem.
    """
    config.validate()
    if config.dry_run or not config.destructive_actions_enabled or config.mode != "production":
        raise CleanerExecutionError("Execution blocked: production mode, DRY_RUN=false, and DESTRUCTIVE_ACTIONS_ENABLED=true are required")

    results: list[dict] = []
    for action in plan.actions:
        if action.action == "remove_empty_folder":
            if not config.allow_empty_folder_removal:
                continue
            results.append(_remove_empty_folder(action))
        elif action.action == "move_to_leftover_review":
            if not config.allow_leftover_review_moves:
                continue
            results.append(_move_to_leftover_review(config, action))
    append_jsonl(config.cleaner_log_path, {"timestamp": utc_now_iso(), "event": "execution_completed", "results": results})
    return results
