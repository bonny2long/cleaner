from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvidenceRecord:
    manifest_path: str
    source_path: str
    batch_id: int | None
    detected_type: str | None
    review_type: str | None
    status_after_move: str | None
    created_at: str | None
    files_moved: list[dict[str, Any]] = field(default_factory=list)
    artwork_moved: list[dict[str, Any]] = field(default_factory=list)
    subtitles_moved: list[dict[str, Any]] = field(default_factory=list)
    failed_moves: list[dict[str, Any]] = field(default_factory=list)
    destination_roots: list[str] = field(default_factory=list)
    destination_verified: bool = False
    verification_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanItem:
    path: str
    relative_path: str
    name: str
    kind: str
    area: str
    empty: bool
    file_count: int
    dir_count: int
    total_size_bytes: int
    modified_time: float
    max_modified_time: float
    age_days: float
    known_trash_only: bool = False
    hidden_or_sidecar_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Classification:
    category: str
    reason: str
    evidence: EvidenceRecord | None = None
    severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = self.evidence.to_dict() if self.evidence else None
        return data


@dataclass
class PlannedAction:
    action: str
    path: str
    relative_path: str
    category: str
    safety_status: str
    reason: str
    severity: str = "info"
    evidence: EvidenceRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = self.evidence.to_dict() if self.evidence else None
        return data


@dataclass
class CleanerPlan:
    run_id: str
    created_at: str
    mode: str
    dry_run: bool
    data_root: str
    min_age_days: int
    items_scanned: int
    evidence_records: int
    actions: list[PlannedAction]
    counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["actions"] = [action.to_dict() for action in self.actions]
        return data
