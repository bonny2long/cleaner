from __future__ import annotations

from pathlib import Path

from .config import CleanerConfig
from .models import Classification, EvidenceRecord, ScanItem


def _find_evidence(item: ScanItem, evidence_by_source: dict[str, EvidenceRecord]) -> EvidenceRecord | None:
    rel = item.relative_path.rstrip("/")
    if rel in evidence_by_source:
        return evidence_by_source[rel]
    for source, evidence in evidence_by_source.items():
        prefix = source.rstrip("/") + "/"
        if rel.startswith(prefix):
            return evidence
    return None


def _is_final_library_or_project_path(item: ScanItem) -> bool:
    protected_roots = (
        "Music/Library",
        "Music/Discographies",
        "Movies/Library",
        "TV/Library",
        "Books/EPUB",
        "Books/PDF",
        "Audiobooks/Library",
        "Documents",
        "Projects",
        "Backups",
        "Photos",
    )
    return any(item.relative_path == root or item.relative_path.startswith(root + "/") for root in protected_roots)


def classify_item(config: CleanerConfig, item: ScanItem, evidence_by_source: dict[str, EvidenceRecord]) -> Classification:
    rel = item.relative_path

    if _is_final_library_or_project_path(item):
        return Classification("do_not_touch", "final library or personal/project path is outside Cleaner cleanup scope", severity="warning")

    if item.area in {"incoming", "intake-processing"}:
        return Classification("do_not_touch", "active upload/processing lane is owned by Intake Watcher", severity="warning")

    if item.area == "quarantine":
        return Classification("quarantine_hold", "quarantine is for review; Cleaner never deletes it by default", severity="warning")

    if item.age_days < config.min_age_days:
        return Classification(
            "blocked_too_new",
            f"item is {item.age_days:.2f} days old; minimum age is {config.min_age_days} days",
            severity="info",
        )

    evidence = _find_evidence(item, evidence_by_source)

    if item.area == "leftover-review":
        return Classification("uncertain_leftover", "already in leftover-review; keep visible for human review", evidence=evidence, severity="warning")

    if item.area in {"failed", "staging"} and evidence is None:
        return Classification("blocked_by_missing_evidence", "failed/staging item has no Archive Assistant evidence", severity="warning")

    if evidence is None:
        return Classification("blocked_by_missing_evidence", "no Archive Assistant move manifest/log matched this source path", severity="warning")

    status = (evidence.status_after_move or "").casefold()
    if status not in {"moved", "rejected"}:
        return Classification("blocked_by_missing_evidence", f"Archive Assistant status is not final: {evidence.status_after_move}", evidence=evidence, severity="warning")

    if not evidence.destination_verified and status == "moved":
        return Classification("blocked_by_destination_missing", "destination verification failed for moved item", evidence=evidence, severity="critical")

    if item.empty and item.kind == "directory":
        return Classification("safe_empty_folder", "source folder is empty after approved/rejected Archive Assistant decision", evidence=evidence, severity="info")

    if item.known_trash_only:
        return Classification("known_harmless_trash", "only known harmless trash files detected; report only in MVP", evidence=evidence, severity="info")

    return Classification("uncertain_leftover", "non-empty leftover may be sidecar, bonus content, or unsupported file; do not delete", evidence=evidence, severity="warning")


def classify_items(config: CleanerConfig, items: list[ScanItem], evidence_by_source: dict[str, EvidenceRecord]) -> list[tuple[ScanItem, Classification]]:
    return [(item, classify_item(config, item, evidence_by_source)) for item in items]
