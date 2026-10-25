"""The trash hold: a recoverable holding area for what Cleaner takes out of the ingest lanes.

Nothing is deleted when Cleaner "removes" something. The folder is renamed into
``_TRASH/<run id>/<its original path>`` (same disk, so instant and reversible) and a manifest
records what it was, why it was taken, the evidence, and when it may be purged. Purging, after
the hold period, is the only place a file is ever deleted.

Every function here fails closed: it raises ``TrashError`` instead of guessing.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import CleanerConfig

MANIFEST_NAME = "trash-manifest.json"
MANIFEST_VERSION = 1
RUN_DIR_PATTERN = re.compile(r"^trash-\d{8}-\d{6}(-\d+)?$")
INVENTORY_FILE_LIMIT = 20000

IN_TRASH = "in_trash"
RESTORED = "restored"
PURGED = "purged"


class TrashError(RuntimeError):
    pass


# ---- gates ---------------------------------------------------------------------------------------------

def _production_gates_open(config: CleanerConfig) -> bool:
    return config.mode == "production" and not config.dry_run and config.destructive_actions_enabled


def trash_enabled(config: CleanerConfig) -> bool:
    """Moving things into the trash hold needs the production gates plus ALLOW_TRASH_HOLD."""
    return _production_gates_open(config) and config.allow_trash_hold


def purge_enabled(config: CleanerConfig) -> bool:
    """Purging (real deletion) needs the production gates plus its own ALLOW_TRASH_PURGE."""
    return _production_gates_open(config) and config.allow_trash_purge


def trash_category_enabled(config: CleanerConfig, category: str) -> bool:
    if not trash_enabled(config):
        return False
    if category == "known_harmless_trash":
        return config.allow_known_trash_delete
    if category == "quarantine_discard_approved":
        return config.allow_quarantine_discard
    return category in {"verified_duplicate", "unrecorded_leftover"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---- path safety -----------------------------------------------------------------------------

def is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def tree_has_link(path: Path) -> bool:
    if is_link(path):
        return True
    if not path.is_dir():
        return False
    for folder, dirs, files in os.walk(path):
        for name in (*dirs, *files):
            if is_link(Path(folder) / name):
                return True
    return False


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _relative(config: CleanerConfig, path: Path) -> str:
    return path.resolve().relative_to(config.data_root.resolve()).as_posix()


def source_roots(config: CleanerConfig, category: str) -> list[Path]:
    """Where an item of this category may be taken from. Quarantine only for approved discards."""
    if category == "quarantine_discard_approved":
        return [config.quarantine_dir]
    return [config.ready_dir, config.failed_dir, config.staging_dir]


def check_trashable(config: CleanerConfig, path: Path, category: str) -> None:
    if not path.exists():
        raise TrashError(f"Not found: {path}")
    roots = source_roots(config, category)
    matching = [root for root in roots if _inside(path, root)]
    if not matching:
        raise TrashError(f"Not inside a lane Cleaner may take {category} items from: {path}")
    resolved = path.resolve()
    if any(resolved == root.resolve() for root in roots):
        raise TrashError(f"Refusing to take a lane root: {path}")
    if category == "quarantine_discard_approved":
        # _QUARANTINE/<kind>/<item>: the kind folders themselves are never taken.
        depth = len(resolved.relative_to(config.quarantine_dir.resolve()).parts)
        if depth < 2:
            raise TrashError(f"Refusing a quarantine container folder: {path}")
    elif _inside(path, config.quarantine_dir) or _inside(path, config.leftover_review_dir):
        raise TrashError(f"Refusing a protected path: {path}")
    if _inside(path, config.trash_dir) or _inside(path, config.reports_root):
        raise TrashError(f"Refusing a Cleaner-owned path: {path}")
    if tree_has_link(path):
        raise TrashError(f"Refusing a link, junction, or a folder containing one: {path}")


# ---- inventories ---------------------------------------------------------------------------------

def inventory_of(path: Path) -> dict[str, Any]:
    """Names and sizes of every file under ``path``. Used to prove a trashed item is unchanged."""
    files: list[dict[str, Any]] = []
    total = 0
    count = 0
    if path.is_file():
        entries = [(path.name, path)]
    else:
        entries = [
            (Path(folder, name).relative_to(path).as_posix(), Path(folder, name))
            for folder, _dirs, names in os.walk(path)
            for name in names
        ]
    for relative, file in sorted(entries):
        size = file.stat().st_size
        total += size
        count += 1
        if len(files) < INVENTORY_FILE_LIMIT:
            files.append({"relative_path": relative, "size_bytes": size})
    return {"file_count": count, "total_bytes": total, "files": files, "files_truncated": count > len(files)}


def inventory_matches(expected: dict[str, Any], live: dict[str, Any]) -> bool:
    if expected.get("file_count") != live.get("file_count") or expected.get("total_bytes") != live.get("total_bytes"):
        return False
    if expected.get("files_truncated") or live.get("files_truncated"):
        return True  # counts and bytes agree; the per-file list was too long to keep
    return expected.get("files") == live.get("files")


# ---- manifests ---------------------------------------------------------------------------------------

def read_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise TrashError(f"Unreadable trash manifest: {path}") from None
    return data if isinstance(data, dict) else None


def write_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / MANIFEST_NAME
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    temporary.replace(target)


def _run_dir(config: CleanerConfig, trash_run: str) -> Path:
    if not RUN_DIR_PATTERN.match(trash_run or ""):
        raise TrashError("Invalid trash run id")
    return config.trash_dir / trash_run


def _find_entry(manifest: dict[str, Any] | None, relative_path: str) -> dict[str, Any]:
    for entry in (manifest or {}).get("entries", []):
        if entry.get("relative_path") == relative_path:
            return entry
    raise TrashError(f"Not in this trash manifest: {relative_path}")


def _prune_empty_parents(start: Path, stop: Path) -> None:
    current = start
    while current != stop and _inside(current, stop):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


# ---- move to trash ---------------------------------------------------------------------------------------

def move_to_trash(
    config: CleanerConfig,
    source: Path,
    *,
    trash_run: str,
    category: str,
    reason: str,
    details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rename ``source`` into the trash hold and record it. Never copies, never overwrites."""
    now = now or utc_now()
    check_trashable(config, source, category)
    relative = _relative(config, source)
    run_dir = _run_dir(config, trash_run)
    destination = run_dir / relative
    if destination.exists():
        raise TrashError(f"Already in the trash hold: {relative}")
    config.trash_dir.mkdir(parents=True, exist_ok=True)
    if os.stat(source).st_dev != os.stat(config.trash_dir).st_dev:
        raise TrashError("The trash hold is on a different disk; Cleaner never copies and deletes")

    manifest = read_manifest(run_dir) or {
        "version": MANIFEST_VERSION,
        "run_id": trash_run,
        "created_at": _iso(now),
        "hold_days": config.trash_hold_days,
        "entries": [],
    }
    entry: dict[str, Any] = {
        "relative_path": relative,
        "category": category,
        "reason": reason,
        "moved_at": _iso(now),
        "purge_after": _iso(now + timedelta(days=config.trash_hold_days)),
        "status": "moving",
        "inventory": inventory_of(source),
        "details": details or {},
    }
    manifest["entries"].append(entry)
    write_manifest(run_dir, manifest)  # the intent is on disk before anything moves
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, destination)
    except OSError as exc:
        entry["status"] = "failed"
        entry["error"] = str(exc)
        write_manifest(run_dir, manifest)
        _prune_empty_parents(destination.parent, run_dir)
        raise TrashError(f"Could not move into the trash hold: {exc}") from exc
    entry["status"] = IN_TRASH
    write_manifest(run_dir, manifest)
    return entry


# ---- restore ---------------------------------------------------------------------------------------------

def restore_entry(config: CleanerConfig, trash_run: str, relative_path: str, now: datetime | None = None) -> dict[str, Any]:
    """Put an item back exactly where it came from. Refuses to overwrite anything."""
    now = now or utc_now()
    run_dir = _run_dir(config, trash_run)
    manifest = read_manifest(run_dir)
    entry = _find_entry(manifest, relative_path)
    if entry.get("status") != IN_TRASH:
        raise TrashError(f"Not in the trash hold (status: {entry.get('status')})")
    held = run_dir / relative_path
    if not held.exists() or not _inside(held, run_dir):
        raise TrashError(f"The held item is missing: {held}")
    destination = config.data_root / relative_path
    roots = source_roots(config, str(entry.get("category")))
    if not any(_inside(destination, root) for root in roots) or any(destination.resolve() == root.resolve() for root in roots):
        raise TrashError(f"The original location is outside the lanes Cleaner works in: {destination}")
    if destination.exists():
        raise TrashError(f"Something already exists at the original location: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.rename(held, destination)
    entry["status"] = RESTORED
    entry["restored_at"] = _iso(now)
    write_manifest(run_dir, manifest)
    _prune_empty_parents(held.parent, run_dir)
    return entry


# ---- purge ------------------------------------------------------------------------------------------------

def purge_entry(config: CleanerConfig, trash_run: str, relative_path: str, now: datetime | None = None) -> dict[str, Any]:
    """Delete one held item for good. The only place Cleaner deletes files."""
    now = now or utc_now()
    run_dir = _run_dir(config, trash_run)
    manifest = read_manifest(run_dir)
    entry = _find_entry(manifest, relative_path)
    if entry.get("status") != IN_TRASH:
        raise TrashError(f"Not in the trash hold (status: {entry.get('status')})")
    purge_after = _parse(entry.get("purge_after"))
    if purge_after is None or now < purge_after:
        raise TrashError(f"The hold has not expired; purgeable after {entry.get('purge_after')}")
    held = run_dir / relative_path
    if not held.exists() or not _inside(held, run_dir) or held.resolve() == run_dir.resolve():
        raise TrashError(f"The held item is missing or outside its trash folder: {held}")
    if tree_has_link(held):
        raise TrashError(f"Refusing a link, junction, or a folder containing one: {held}")
    live = inventory_of(held)
    if not inventory_matches(entry.get("inventory") or {}, live):
        raise TrashError("The held item no longer matches what was recorded when it was taken; leaving it alone")
    if held.is_file():
        held.unlink()
    else:
        shutil.rmtree(held)
    entry["status"] = PURGED
    entry["purged_at"] = _iso(now)
    entry["purged_file_count"] = live["file_count"]
    entry["purged_bytes"] = live["total_bytes"]
    write_manifest(run_dir, manifest)
    _prune_empty_parents(held.parent, run_dir)
    return entry


# ---- listing -------------------------------------------------------------------------------------------------

def list_holds(config: CleanerConfig, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every trash run with its entries, newest first, with expiry computed against ``now``."""
    now = now or utc_now()
    root = config.trash_dir
    holds: list[dict[str, Any]] = []
    if not root.is_dir():
        return holds
    for run_dir in sorted((p for p in root.iterdir() if p.is_dir() and RUN_DIR_PATTERN.match(p.name)), reverse=True):
        try:
            manifest = read_manifest(run_dir)
        except TrashError:
            holds.append({"run_id": run_dir.name, "error": "unreadable manifest", "entries": []})
            continue
        if manifest is None:
            continue
        entries = []
        for entry in manifest.get("entries", []):
            purge_after = _parse(entry.get("purge_after"))
            inventory = entry.get("inventory") or {}
            in_trash = entry.get("status") == IN_TRASH
            entries.append({
                "relative_path": entry.get("relative_path"),
                "category": entry.get("category"),
                "reason": entry.get("reason"),
                "status": entry.get("status"),
                "moved_at": entry.get("moved_at"),
                "purge_after": entry.get("purge_after"),
                "expired": bool(in_trash and purge_after and now >= purge_after),
                "days_left": max(0, math.ceil((purge_after - now).total_seconds() / 86400)) if in_trash and purge_after else None,
                "file_count": inventory.get("file_count"),
                "total_bytes": inventory.get("total_bytes"),
                "missing": bool(in_trash and not (run_dir / str(entry.get("relative_path"))).exists()),
            })
        holds.append({"run_id": manifest.get("run_id", run_dir.name), "created_at": manifest.get("created_at"), "entries": entries})
    return holds
