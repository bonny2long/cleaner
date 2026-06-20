from __future__ import annotations

import json
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


def _manifest_files(data_root: Path) -> list[Path]:
    patterns = ["**/move_manifest.json", "**/*_move_manifest.json"]
    seen: set[Path] = set()
    found: list[Path] = []
    for pattern in patterns:
        for path in data_root.glob(pattern):
            if path in seen or not path.is_file():
                continue
            # Ignore Cleaner's own reports. They are not Archive Assistant move evidence.
            parts = {part.casefold() for part in path.parts}
            if "cleaner" in parts and "_reports" in parts:
                continue
            seen.add(path)
            found.append(path)
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


def evidence_index(config: CleanerConfig) -> dict[str, EvidenceRecord]:
    index: dict[str, EvidenceRecord] = {}
    for record in load_archive_evidence(config):
        index[record.source_path] = record
        # Also allow matching children under a moved source root.
        index[record.source_path.rstrip("/")] = record
    return index
