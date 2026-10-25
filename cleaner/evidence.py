from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from .config import CleanerConfig
from .models import EvidenceRecord


def _normalize_relative(value: str | Path, data_root: Path) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(data_root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(value).replace("\\", "/").lstrip("./")


# Archive Assistant writes move manifests inside the final libraries
# (<release folder>/metadata/move_manifest.json) and collection manifests under
# <Media>/Metadata/move_manifests. Nothing else is evidence, so Cleaner looks only
# here instead of walking the whole data root (Backups, Photos, ingest lanes, ...).
EVIDENCE_ROOTS = ("Music", "Movies", "TV", "Books", "Audiobooks", "_REPORTS/move_manifests")
# Deepest library layout is Music/Library/FLAC/<Artist>/<Album>/metadata (6 levels).
MAX_EVIDENCE_DEPTH = 8


def _is_manifest_name(name: str) -> bool:
    return name == "move_manifest.json" or name.endswith("_move_manifest.json")


def _manifest_files(data_root: Path) -> list[Path]:
    """Find move manifests by listing folders only; individual files are never opened or stat'ed."""
    found: list[Path] = []
    for relative in EVIDENCE_ROOTS:
        root = data_root / relative
        if not root.is_dir():
            continue
        stack = [(root, len(Path(relative).parts))]
        while stack:
            folder, depth = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if depth < MAX_EVIDENCE_DEPTH:
                                    stack.append((Path(entry.path), depth + 1))
                            elif _is_manifest_name(entry.name) and entry.is_file():
                                found.append(Path(entry.path))
                        except OSError:
                            continue
            except OSError:
                continue
    return sorted(found, key=lambda p: str(p).casefold())


def _verify_destination(data_root: Path, manifest: dict[str, Any]) -> tuple[bool, list[str]]:
    messages: list[str] = []
    if manifest.get("failed_moves"):
        return False, ["manifest contains failed_moves"]

    moved_entries = []
    for key in ("files_moved", "artwork_moved", "subtitles_moved"):
        entries = manifest.get(key) or []
        if isinstance(entries, list):
            moved_entries.extend(entries)

    checked = 0
    missing = 0
    for entry in moved_entries:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("destination_relative")
        if not rel:
            continue
        checked += 1
        if not (data_root / str(rel)).exists():
            missing += 1
            messages.append(f"missing destination file: {rel}")
            if missing >= 5:
                messages.append("additional missing destination files suppressed")
                break

    roots = manifest.get("destination_roots") or []
    for rel in roots:
        checked += 1
        if not (data_root / str(rel)).exists():
            missing += 1
            messages.append(f"missing destination root: {rel}")

    if checked == 0:
        return False, ["manifest has no destination entries to verify"]
    if missing:
        return False, messages
    return True, [f"verified {checked} destination path(s)"]


def load_archive_evidence(config: CleanerConfig) -> list[EvidenceRecord]:
    data_root = config.data_root
    evidence: list[EvidenceRecord] = []
    if not data_root.exists():
        return evidence

    for path in _manifest_files(data_root):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_path = manifest.get("source_path")
        if not source_path:
            continue
        verified, messages = _verify_destination(data_root, manifest)
        evidence.append(
            EvidenceRecord(
                manifest_path=_normalize_relative(path, data_root),
                source_path=_normalize_relative(source_path, data_root),
                batch_id=manifest.get("batch_id"),
                detected_type=manifest.get("detected_type"),
                review_type=manifest.get("review_type"),
                status_after_move=manifest.get("status_after_move"),
                created_at=manifest.get("created_at"),
                files_moved=manifest.get("files_moved") or [],
                artwork_moved=manifest.get("artwork_moved") or [],
                subtitles_moved=manifest.get("subtitles_moved") or [],
                failed_moves=manifest.get("failed_moves") or [],
                destination_roots=[str(value) for value in (manifest.get("destination_roots") or [])],
                destination_verified=verified,
                verification_messages=messages,
            )
        )
    return evidence


_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, EvidenceRecord]]] = {}


def _now() -> float:
    return time.monotonic()


def clear_evidence_cache() -> None:
    with _cache_lock:
        _cache.clear()


def evidence_index(config: CleanerConfig, max_age_seconds: float = 0) -> dict[str, EvidenceRecord]:
    """Index move evidence by source path.

    ``max_age_seconds=0`` (the default) always reads the disk. The dashboard passes a
    small value so its 30-second refresh does not rescan the libraries every time;
    writing a plan and executing never use the cache.
    """
    key = str(config.data_root)
    if max_age_seconds > 0:
        with _cache_lock:
            cached = _cache.get(key)
        if cached is not None and _now() - cached[0] <= max_age_seconds:
            return cached[1]
    index: dict[str, EvidenceRecord] = {}
    for record in load_archive_evidence(config):
        index[record.source_path] = record
        # Also allow matching children under a moved source root.
        index[record.source_path.rstrip("/")] = record
    with _cache_lock:
        _cache[key] = (_now(), index)
    return index
