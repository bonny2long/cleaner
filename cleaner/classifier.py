from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from .config import CleanerConfig
from .dispositions import DispositionRecord, approved_discards, eligible_after, inventory_matches
from .duplicates import DuplicateAssessment, assess_item
from .models import Classification, EvidenceRecord, ScanItem


class ClassificationContext:
    """Things shared by one planning run: approved quarantine discards and the hashing time budget.

    ``hash_budget_seconds=None`` means no limit (written plans and executions). The dashboard
    passes a small budget so a refresh never stalls on hashing large folders; items it could
    not finish are shown as "not yet checked" and complete on later refreshes.
    """

    def __init__(self, config: CleanerConfig, hash_budget_seconds: float | None = None) -> None:
        self.config = config
        self.deadline = None if hash_budget_seconds is None else time.monotonic() + hash_budget_seconds
        self._discards: dict[str, DispositionRecord] | None = None

    @property
    def discards(self) -> dict[str, DispositionRecord]:
        if self._discards is None:
            self._discards = approved_discards(self.config)
        return self._discards

    def assess(self, path: Path) -> DuplicateAssessment:
        return assess_item(self.config, path, self.deadline)


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


def _classify_discard(config: CleanerConfig, item: ScanItem, context: ClassificationContext) -> Classification:
    """A single quarantined item. It qualifies only on a person's recorded discard decision."""
    record = context.discards.get(item.relative_path)
    if record is None:
        return Classification("quarantine_hold", "no approved discard decision for this item; Cleaner leaves it alone", severity="warning")
    after = eligible_after(record, config.min_age_days)
    now = datetime.now(timezone.utc)
    details = {
        "batch_id": record.batch_id,
        "discard_reason": record.reason,
        "decided_at": record.created_at,
        "eligible_after": after.isoformat() if after else None,
        "eligible_now": bool(after and now >= after),
        "decision_record": record.record_path,
        "size_bytes": item.total_size_bytes,
        "file_count": item.file_count,
    }
    matches, message = inventory_matches(record.inventory, Path(item.path))
    details["inventory_check"] = message
    if not matches:
        return Classification(
            "quarantine_hold",
            f"a discard was approved, but {message}; Cleaner leaves it alone until it is reviewed again",
            severity="warning",
            details=details,
        )
    when = "eligible now" if details["eligible_now"] else f"eligible after {after.date().isoformat() if after else 'its waiting period'}"
    return Classification(
        "quarantine_discard_approved",
        f"you approved discarding this in Archive Assistant ({record.reason or 'no reason recorded'}); {when}. "
        "Nothing is removed until the trash hold exists",
        severity="info",
        details=details,
    )


def _classify_unrecorded(item: ScanItem, context: ClassificationContext, empty_reason: str) -> Classification:
    """A folder Archive Assistant has no record of. Duplicates of library content are provable; the rest is the owner's call."""
    if item.empty or item.file_count == 0:
        return Classification("blocked_by_missing_evidence", empty_reason, severity="warning")
    assessment = context.assess(Path(item.path))
    details = assessment.details()
    if assessment.verdict == "verified_duplicate":
        return Classification(
            "verified_duplicate",
            f"all {assessment.content_files} media file(s) are exact copies of files already in the library; "
            "Archive Assistant has no record of this folder. Nothing is removed until the trash hold exists",
            severity="info",
            details=details,
        )
    reasons = {
        "pending": "Archive Assistant has no record of this folder and it has not been checked against the library yet; run a dry plan to verify it",
        "unmatched_content": f"{len(assessment.unmatched)} media file(s) are not in any library; Archive Assistant has no record of this folder",
        "other_files": f"contains {len(assessment.other)} file(s) Cleaner does not recognise; Archive Assistant has no record of this folder",
        "no_content": "no media files, only artwork or notes; Archive Assistant has no record of this folder",
        "missing": "the folder disappeared while it was being checked",
    }
    return Classification("unrecorded_leftover", reasons.get(assessment.verdict, "Archive Assistant has no record of this folder"), severity="warning", details=details)


def classify_item(
    config: CleanerConfig,
    item: ScanItem,
    evidence_by_source: dict[str, EvidenceRecord],
    context: ClassificationContext | None = None,
) -> Classification:
    context = context or ClassificationContext(config)

    if _is_final_library_or_project_path(item):
        return Classification("do_not_touch", "final library or personal/project path is outside Cleaner cleanup scope", severity="warning")

    if item.area in {"incoming", "intake-processing"}:
        return Classification("do_not_touch", "active upload/processing lane is owned by Intake Watcher", severity="warning")

    if item.area == "quarantine-discard":
        return _classify_discard(config, item, context)

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

    if evidence is None:
        empty_reason = (
            "failed/staging item has no Archive Assistant evidence"
            if item.area in {"failed", "staging"}
            else "no Archive Assistant move manifest/log matched this source path"
        )
        return _classify_unrecorded(item, context, empty_reason)

    status = (evidence.status_after_move or "").casefold()
    if status not in {"moved", "rejected"}:
        return Classification("blocked_by_missing_evidence", f"Archive Assistant status is not final: {evidence.status_after_move}", evidence=evidence, severity="warning")

    if not evidence.destination_verified and status == "moved":
        return Classification("blocked_by_destination_missing", "destination verification failed for moved item", evidence=evidence, severity="critical")

    if item.empty and item.kind == "directory":
        return Classification("safe_empty_folder", "source folder is empty after approved/rejected Archive Assistant decision", evidence=evidence, severity="info")

    if item.known_trash_only and item.rip_sidecar_count:
        return Classification(
            "known_harmless_trash",
            "only CD-rip logs (.log, .cue, .accurip, .m3u, DR and auCDtect reports) and other known junk remain; "
            "Archive Assistant already moved this release. Report only until the trash hold exists",
            evidence=evidence,
            severity="info",
        )

    if item.known_trash_only:
        return Classification("known_harmless_trash", "only known harmless trash files detected; report only in MVP", evidence=evidence, severity="info")

    return Classification("uncertain_leftover", "non-empty leftover may be sidecar, bonus content, or unsupported file; do not delete", evidence=evidence, severity="warning")


def classify_items(
    config: CleanerConfig,
    items: list[ScanItem],
    evidence_by_source: dict[str, EvidenceRecord],
    context: ClassificationContext | None = None,
) -> list[tuple[ScanItem, Classification]]:
    context = context or ClassificationContext(config)
    return [(item, classify_item(config, item, evidence_by_source, context)) for item in items]
