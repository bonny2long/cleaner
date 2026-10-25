"""Read Archive Assistant's disposition records (human decisions about quarantined items).

Archive Assistant writes one append-only JSON file per decision under
``_REPORTS/archive-assistant/dispositions``. The newest record for a batch is its
current disposition. Cleaner only acts on ``discard_approved``, and only while that
is still the newest record and the live files still match the inventory recorded at
decision time. Cleaner never reads Archive Assistant's database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import CleanerConfig

RECORD_TYPE = "archive_assistant_disposition"


@dataclass(frozen=True)
class DispositionRecord:
    record_path: str
    batch_id: int
    action: str
    created_at: str
    reason: str | None
    current_path: str
    inventory: dict[str, Any] = field(default_factory=dict)

    def decided_at(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError:
            return None


def dispositions_dir(config: CleanerConfig) -> Path:
    return config.archive_reports_dir / "dispositions"


def load_newest_dispositions(config: CleanerConfig) -> dict[int, DispositionRecord]:
    """The newest disposition record per batch. Unreadable or foreign files are skipped."""
    directory = dispositions_dir(config)
    if not directory.is_dir():
        return {}
    newest: dict[int, DispositionRecord] = {}
    # File names start with a UTC timestamp, so name order is time order.
    for path in sorted(directory.glob("*.json"), key=lambda item: item.name):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("record_type") != RECORD_TYPE:
                continue
            record = DispositionRecord(
                record_path=str(path),
                batch_id=int(data["batch_id"]),
                action=str(data["action"]),
                created_at=str(data.get("created_at") or ""),
                reason=data.get("reason"),
                current_path=str(data.get("current_path") or "").replace("\\", "/").strip("/"),
                inventory=data.get("inventory") if isinstance(data.get("inventory"), dict) else {},
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        newest[record.batch_id] = record
    return newest


def approved_discards(config: CleanerConfig) -> dict[str, DispositionRecord]:
    """Quarantined items a person approved for discard, keyed by path relative to the data root.

    Only items whose newest record is ``discard_approved`` and whose recorded path is inside
    ``_QUARANTINE`` are returned, so a revoked, restored or tampered record never qualifies.
    """
    quarantine_prefix = _relative(config, config.quarantine_dir) + "/"
    result: dict[str, DispositionRecord] = {}
    for record in load_newest_dispositions(config).values():
        if record.action != "discard_approved":
            continue
        if not record.current_path.startswith(quarantine_prefix) or ".." in record.current_path.split("/"):
            continue
        result[record.current_path] = record
    return result


def inventory_matches(inventory: dict[str, Any], live_path: Path) -> tuple[bool, str]:
    """True when the live files are exactly what was recorded when the decision was made."""
    if not inventory:
        return False, "the decision has no file inventory to compare against"
    if inventory.get("files_truncated"):
        return False, "the recorded inventory was truncated (more than 5000 files)"
    try:
        expected = {str(item["relative_path"]).replace("\\", "/"): int(item["size_bytes"]) for item in inventory.get("files") or []}
    except (KeyError, TypeError, ValueError):
        return False, "the recorded inventory is unreadable"
    if live_path.is_file():
        live = {live_path.name: live_path.stat().st_size}
    elif live_path.is_dir():
        live = {
            file.relative_to(live_path).as_posix(): file.stat().st_size
            for file in live_path.rglob("*")
            if file.is_file()
        }
    else:
        return False, "the item no longer exists"
    if live == expected:
        return True, "live files match the recorded inventory"
    added = len(live.keys() - expected.keys())
    missing = len(expected.keys() - live.keys())
    changed = sum(1 for name in live.keys() & expected.keys() if live[name] != expected[name])
    return False, f"live files differ from the decision: {added} added, {missing} missing, {changed} changed"


def eligible_after(record: DispositionRecord, min_age_days: int) -> datetime | None:
    decided = record.decided_at()
    if decided is None:
        return None
    if decided.tzinfo is None:
        decided = decided.replace(tzinfo=timezone.utc)
    return decided + timedelta(days=min_age_days)


def _relative(config: CleanerConfig, path: Path) -> str:
    try:
        return path.resolve().relative_to(config.data_root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()
