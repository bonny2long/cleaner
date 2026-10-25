# Archive Assistant Evidence Contract

Cleaner reads Archive Assistant evidence from files on disk. It never reads Archive Assistant's database or imports its code.

## Move manifests (read today)

Archive Assistant writes one JSON manifest per moved batch:

```text
<destination>/metadata/move_manifest.json
Music|Books|Movies|Audiobooks/Metadata/move_manifests/<date>_<batch>_<name>_move_manifest.json
_REPORTS/move_manifests/<date>_<batch>_move_manifest.json
```

Cleaner finds both `move_manifest.json` and `*_move_manifest.json`, but only under `Music`, `Movies`, `TV`, `Books`, `Audiobooks` and `_REPORTS/move_manifests`, down to 8 folder levels. It lists folders only and never opens other files. A manifest copy anywhere else (Backups, Photos, ingest lanes, Cleaner's own reports) is not evidence. If Archive Assistant ever writes manifests somewhere new, add that folder to `EVIDENCE_ROOTS` in `cleaner/evidence.py`. The dashboard reuses what it found for up to 60 seconds; writing or executing a plan always rescans. Fields Cleaner uses:

```text
source_path          original ingest folder, relative to the data root
status_after_move    must be "moved" or "rejected"
files_moved          entries with destination_relative
artwork_moved
subtitles_moved
failed_moves         any entry blocks cleanup
destination_roots
batch_id, detected_type, review_type, created_at
```

A leftover is eligible for cleanup planning only when a matching manifest exists, its status is final, and every destination it lists still exists. Otherwise it is `blocked_by_destination_missing`, or, when no manifest matches at all, one of the "no record" outcomes below.

### Folders with no manifest

A non-empty folder in `ready`, `failed` or `staging` that no manifest matches is not simply blocked. Cleaner compares its media files with the final libraries by SHA-256 (`Music`, `Movies`, `TV`, `Books`, `Audiobooks`):

- every media file is an exact copy of a library file, and everything else is artwork, release notes (`.nfo`, `.sfv`, `.md5`, `.ffp`, subtitles), rip logs, known junk or empty: `verified_duplicate`;
- anything else: `unrecorded_leftover`. It is never picked up on its own, because it may be a download that has not been scanned yet.

An empty folder with no manifest stays `blocked_by_missing_evidence`.

Known gap: when several manifests share one source folder (a discography split into albums), Cleaner currently keeps only one of them per source.

## Disposition records (read for quarantine discards)

Archive Assistant also writes append-only disposition records for quarantine, restore, discard, undo discard, and reject:

```text
_REPORTS/archive-assistant/dispositions/<timestamp>_<batch>_<action>.json
```

The format is documented in Archive Assistant's `docs/CLEANER_BOUNDARY.md`. Cleaner reads them and picks up a quarantined item only when all of this holds:

- `discard_approved` is the newest record for its batch (a later `discard_revoked` or `restored` cancels it);
- its recorded path is inside `_QUARANTINE` (a record pointing anywhere else is ignored);
- the live files still match the record's `inventory` exactly (same names and sizes, nothing added or missing);
- `MIN_AGE_DAYS` have passed since the decision; before that the item is listed with the date it becomes eligible.

Items that fail the inventory check are reported as `quarantine_hold` with the reason. Items nobody decided about are never picked up. `rejected` records are not used yet: a rejected batch's files are reported, not cleaned, because a `rejected` record whose `shared_source_batch_ids` is not empty means a shared folder, not a rejected one.
