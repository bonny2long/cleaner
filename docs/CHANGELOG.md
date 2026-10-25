# Changelog

## Unreleased

- Removed the `move_to_leftover_review` action and the `ALLOW_LEFTOVER_REVIEW_MOVES` setting. The planner only offered it when destructive actions were off and the executor only ran it when they were on, so it could never run. Uncertain leftovers are report-only. A leftover `ALLOW_LEFTOVER_REVIEW_MOVES` line in a `.env` is ignored.
- CD-rip logs (`.log`, `.cue`, `.accurip`, `.m3u`, `DR<n>.txt`, `auCDtect.txt`) left beside a release after Archive Assistant moved the audio are now labeled `known_harmless_trash` instead of `uncertain_leftover`. Still report-only: nothing is deleted, and file cleanup waits for the 14-day trash hold. A folder with any other file, no move evidence, or an age under `MIN_AGE_DAYS` is not labeled.
- `POST` requests (`/api/run-dry-plan`, `/api/execute`, `/api/ensure-folders`) are rejected with 403 when their `Origin` header is not a loopback address or listed in the new `ALLOWED_ORIGINS` setting. This stops a web page on another site from driving Cleaner through the browser. Requests with no `Origin` header (curl, scripts) still work, and the existing gates and reviewed-plan requirement for removal are unchanged. A refused request's body is read and dropped first, so the caller always gets the 403 and not a reset connection.
- Move manifests are now found by one folder-only pass over `Music`, `Movies`, `TV`, `Books`, `Audiobooks` and `_REPORTS/move_manifests` (8 levels deep) instead of two whole-data-root globs. Measured on 3,000 synthetic albums: about 4x faster, same 3,000 manifests found; on the real data root the same 7.
- Manifests outside those folders (for example a copy in `Backups`) no longer count as evidence.
- The dashboard and `GET /api/plan` reuse the evidence for up to 60 seconds, so its 30-second refresh does not rescan the libraries each time. Writing a plan (`/api/run-dry-plan`) and executing always read fresh evidence.
- Tests: 63.

## 0.2.0 - 2026-09-27

- Default `MIN_AGE_DAYS` is now 30 (was 14), matching the agreed timing model: weekly check, 30-day age gate, planned 14-day trash hold.
- Reviewed empty-folder removal behind four production gates, with a dashboard button and `cli execute --run-id`. Execution is limited to `_INGEST/ready`, `_INGEST/failed` and `_STAGING`, rechecks every target, removes folders only, and writes an execution report.
- A folder tree with no files, such as empty `CD 1` / `CD 2` shells, now counts as empty.
- Suite navigation links point at the right apps on 127.0.0.1.
- Docs rewritten for the current `C:\Dev\NAS` and `C:\NAS-Local\nas-data` layout.
- Tests: 18.

## 0.1.0

Initial conservative Cleaner scaffold. Dry-run scanner/planner, shared nas-data root, reports, CLI, dashboard, and tests.
