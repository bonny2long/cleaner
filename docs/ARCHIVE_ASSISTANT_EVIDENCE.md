# Archive Assistant Evidence Contract

Cleaner reads Archive Assistant evidence from files on disk. It never reads Archive Assistant's database or imports its code.

## Move manifests (read today)

Archive Assistant writes one JSON manifest per moved batch:

```text
<destination>/metadata/move_manifest.json
Music|Books|Movies|Audiobooks/Metadata/move_manifests/<date>_<batch>_<name>_move_manifest.json
_REPORTS/move_manifests/<date>_<batch>_move_manifest.json
```

Cleaner finds both `move_manifest.json` and `*_move_manifest.json` anywhere under the data root, except its own reports. Fields Cleaner uses:

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

A leftover is eligible for cleanup planning only when a matching manifest exists, its status is final, and every destination it lists still exists. Otherwise it is `blocked_by_missing_evidence` or `blocked_by_destination_missing`.

Known gap: when several manifests share one source folder (a discography split into albums), Cleaner currently keeps only one of them per source.

## Disposition records (not read yet)

Archive Assistant also writes append-only disposition records for quarantine, restore, discard, undo discard, and reject:

```text
_REPORTS/archive-assistant/dispositions/<timestamp>_<batch>_<action>.json
```

The format is documented in Archive Assistant's `docs/CLEANER_BOUNDARY.md`. Cleaner will use `discard_approved` records to clean approved quarantine discards after the planned trash hold is built. Rules for that phase: act only when `discard_approved` is the newest record for the batch, and the live files still match the record's `inventory`. Treat a `rejected` record whose `shared_source_batch_ids` is not empty as a shared folder, not a rejected one.
