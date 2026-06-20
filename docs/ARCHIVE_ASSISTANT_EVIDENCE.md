# Archive Assistant Evidence Contract

Cleaner should read Archive Assistant evidence from JSON move manifests, not from Archive Assistant internals.

Expected move manifest fields include:

```text
source_path
detected_type
review_type
status_after_move
metadata_confirmed
metadata_locked_for_move
files_moved
artwork_moved
subtitles_moved
failed_moves
destination_roots
created_at
```

Cleaner treats a source path as eligible for cleanup planning only when a matching manifest exists, the status is final (`moved` or `rejected`), and destination verification passes for moved items.

If a successful Archive Assistant move exists but no manifest can be found, Cleaner classifies the leftover as `blocked_by_missing_evidence`.
