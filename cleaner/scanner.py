from __future__ import annotations

import os
import time
from pathlib import Path

from .config import CleanerConfig
from .models import ScanItem


def _relative(path: Path, data_root: Path) -> str:
    try:
        return path.resolve().relative_to(data_root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _is_known_trash(path: Path, config: CleanerConfig) -> bool:
    name_match = path.name in config.known_trash_names
    suffix_match = path.suffix.casefold() in {suffix.casefold() for suffix in config.known_trash_suffixes}
    return name_match or suffix_match


def _dir_stats(path: Path, config: CleanerConfig) -> tuple[int, int, int, float, bool, int]:
    file_count = 0
    dir_count = 0
    total_size = 0
    max_mtime = path.stat().st_mtime
    trash_only = True
    hidden_or_sidecar = 0

    if path.is_file():
        stat = path.stat()
        return 1, 0, stat.st_size, stat.st_mtime, _is_known_trash(path, config), int(path.name.startswith("."))

    for root, dirs, files in os.walk(path):
        root_path = Path(root)
        dir_count += len(dirs)
        try:
            max_mtime = max(max_mtime, root_path.stat().st_mtime)
        except OSError:
            pass
        for filename in files:
            item = root_path / filename
            try:
                stat = item.stat()
            except OSError:
                continue
            file_count += 1
            total_size += stat.st_size
            max_mtime = max(max_mtime, stat.st_mtime)
            if not _is_known_trash(item, config):
                trash_only = False
            if filename.startswith(".") or item.suffix.casefold() in {".nfo", ".srt", ".sub", ".idx", ".cue", ".log"}:
                hidden_or_sidecar += 1
    if file_count == 0:
        trash_only = False
    return file_count, dir_count, total_size, max_mtime, trash_only, hidden_or_sidecar


def _scan_area(config: CleanerConfig, area: str, root: Path, now: float) -> list[ScanItem]:
    if not root.exists():
        return []
    items: list[ScanItem] = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        try:
            stat = path.stat()
        except OSError:
            continue
        kind = "file" if path.is_file() else "directory"
        file_count, dir_count, total_size, max_mtime, trash_only, hidden_or_sidecar = _dir_stats(path, config)
        empty = path.is_dir() and file_count == 0 and dir_count == 0
        age_days = max(0.0, (now - max_mtime) / 86400)
        items.append(
            ScanItem(
                path=str(path),
                relative_path=_relative(path, config.data_root),
                name=path.name,
                kind=kind,
                area=area,
                empty=empty,
                file_count=file_count,
                dir_count=dir_count,
                total_size_bytes=total_size,
                modified_time=stat.st_mtime,
                max_modified_time=max_mtime,
                age_days=age_days,
                known_trash_only=trash_only,
                hidden_or_sidecar_count=hidden_or_sidecar,
            )
        )
    return items


def scan_cleanup_candidates(config: CleanerConfig, now: float | None = None) -> list[ScanItem]:
    now = now or time.time()
    candidates: list[ScanItem] = []
    # Cleanup planning starts in ready, leftover-review, quarantine summary, failed, and staging.
    # Incoming and intake-processing are explicitly ignored by default to avoid racing active uploads.
    candidates.extend(_scan_area(config, "ready", config.ready_dir, now))
    candidates.extend(_scan_area(config, "leftover-review", config.leftover_review_dir, now))
    candidates.extend(_scan_area(config, "quarantine", config.quarantine_dir, now))
    candidates.extend(_scan_area(config, "failed", config.failed_dir, now))
    candidates.extend(_scan_area(config, "staging", config.staging_dir, now))
    if not config.ignore_incoming:
        candidates.extend(_scan_area(config, "incoming", config.incoming_dir, now))
    if not config.ignore_processing:
        candidates.extend(_scan_area(config, "intake-processing", config.processing_dir, now))
    return candidates
