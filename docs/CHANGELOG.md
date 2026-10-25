# Changelog

## Unreleased

- Removed the `move_to_leftover_review` action and the `ALLOW_LEFTOVER_REVIEW_MOVES` setting. The planner only offered it when destructive actions were off and the executor only ran it when they were on, so it could never run. Uncertain leftovers are report-only. A leftover `ALLOW_LEFTOVER_REVIEW_MOVES` line in a `.env` is ignored.
- CD-rip logs (`.log`, `.cue`, `.accurip`, `.m3u`, `DR<n>.txt`, `auCDtect.txt`) left beside a release after Archive Assistant moved the audio are now labeled `known_harmless_trash` instead of `uncertain_leftover`. Report-only unless the trash hold is enabled (see below); nothing is ever deleted directly. A folder with any other file, no move evidence, or an age under `MIN_AGE_DAYS` is not labeled.
- `POST` requests (`/api/run-dry-plan`, `/api/execute`, `/api/ensure-folders`) are rejected with 403 when their `Origin` header is not a loopback address or listed in the new `ALLOWED_ORIGINS` setting. This stops a web page on another site from driving Cleaner through the browser. Requests with no `Origin` header (curl, scripts) still work, and the existing gates and reviewed-plan requirement for removal are unchanged. A refused request's body is read and dropped first, so the caller always gets the 403 and not a reset connection.
- Move manifests are now found by one folder-only pass over `Music`, `Movies`, `TV`, `Books`, `Audiobooks` and `_REPORTS/move_manifests` (8 levels deep) instead of two whole-data-root globs. Measured on 3,000 synthetic albums: about 4x faster, same 3,000 manifests found; on the real data root the same 7.
- Manifests outside those folders (for example a copy in `Backups`) no longer count as evidence.
- The dashboard and `GET /api/plan` reuse the evidence for up to 60 seconds, so its 30-second refresh does not rescan the libraries each time. Writing a plan (`/api/run-dry-plan`) and executing always read fresh evidence.
- **Picks up three more kinds of leftover (report-only).** `verified_duplicate`: a folder Archive Assistant has no record of whose media files are all byte-for-byte copies (SHA-256) of files already in a final library, so a `- Copy` folder is recognised by content. `quarantine_discard_approved`: a quarantined item whose newest Archive Assistant disposition record is `discard_approved`, whose recorded path is inside `_QUARANTINE`, and whose files still match the recorded inventory; shown with the date it becomes eligible. `unrecorded_leftover`: any other folder with no record, listed for a decision and never picked up automatically. Undecided quarantine items stay `quarantine_hold`. New dashboard lanes and counters, and the written report lists the matches.
- Folders with files but no Archive Assistant record used to be `blocked_by_missing_evidence`; they are now `unrecorded_leftover` or `verified_duplicate`. Empty folders with no record are unchanged.
- The dashboard checks duplicates for at most 5 seconds per refresh and shows the rest as "not yet checked"; written plans check everything. Measured on the real `ready` folder: the 182-file Mac Miller copy verifies 182 of 182 in about 54 s.
- Nothing is removed for these categories by default.
- **Recoverable trash hold (off by default).** With the production gates plus `ALLOW_TRASH_HOLD`, a reviewed plan can move verified duplicates, strays you tick, quarantine discards (also needs `ALLOW_QUARANTINE_DISCARD`) and known-junk folders (also needs `ALLOW_KNOWN_TRASH_DELETE`) into `_TRASH/<trash run>/<original path>`. It is a same-disk rename with a `trash-manifest.json` (reason, evidence, file inventory, `purge_after`), never a copy or delete. Items are re-verified at move time: in the reviewed plan (under 24 h) with the same category, a duplicate re-proved by content, unchanged since classification, in the right lane, no links, nothing overwritten. Restore is always available and never overwrites. Purge (`ALLOW_TRASH_PURGE`) deletes only items you list whose hold has expired and whose files still match the recorded inventory; it is the only deletion. New dashboard Trash Hold panel with tick boxes, move, restore and purge, `GET /api/trash`, `POST /api/trash/move|restore|purge` (origin-guarded), CLI `trash-move`, `trash-list`, `restore`, `purge`, and `TRASH_HOLD_DAYS` (default 14, minimum 1). Cleanup actions are serialised: a second request while one runs gets 409.
- Removed the unused `ALLOW_QUARANTINE_ROUTING` setting (replaced by `ALLOW_QUARANTINE_DISCARD`). A leftover line in a `.env` is ignored.
- Tests: 126.

## 0.2.0 - 2026-09-27

- Default `MIN_AGE_DAYS` is now 30 (was 14), matching the agreed timing model: weekly check, 30-day age gate, planned 14-day trash hold.
- Reviewed empty-folder removal behind four production gates, with a dashboard button and `cli execute --run-id`. Execution is limited to `_INGEST/ready`, `_INGEST/failed` and `_STAGING`, rechecks every target, removes folders only, and writes an execution report.
- A folder tree with no files, such as empty `CD 1` / `CD 2` shells, now counts as empty.
- Suite navigation links point at the right apps on 127.0.0.1.
- Docs rewritten for the current `C:\Dev\NAS` and `C:\NAS-Local\nas-data` layout.
- Tests: 18.

## 0.1.0

Initial conservative Cleaner scaffold. Dry-run scanner/planner, shared nas-data root, reports, CLI, dashboard, and tests.
