# Changelog

## Unreleased

- Removed the `move_to_leftover_review` action and the `ALLOW_LEFTOVER_REVIEW_MOVES` setting. The planner only offered it when destructive actions were off and the executor only ran it when they were on, so it could never run. Uncertain leftovers are report-only. A leftover `ALLOW_LEFTOVER_REVIEW_MOVES` line in a `.env` is ignored.
- CD-rip logs (`.log`, `.cue`, `.accurip`, `.m3u`, `DR<n>.txt`, `auCDtect.txt`) left beside a release after Archive Assistant moved the audio are now labeled `known_harmless_trash` instead of `uncertain_leftover`. Still report-only: nothing is deleted, and file cleanup waits for the 14-day trash hold. A folder with any other file, no move evidence, or an age under `MIN_AGE_DAYS` is not labeled.
- Tests: 33.

## 0.2.0 - 2026-09-27

- Default `MIN_AGE_DAYS` is now 30 (was 14), matching the agreed timing model: weekly check, 30-day age gate, planned 14-day trash hold.
- Reviewed empty-folder removal behind four production gates, with a dashboard button and `cli execute --run-id`. Execution is limited to `_INGEST/ready`, `_INGEST/failed` and `_STAGING`, rechecks every target, removes folders only, and writes an execution report.
- A folder tree with no files, such as empty `CD 1` / `CD 2` shells, now counts as empty.
- Suite navigation links point at the right apps on 127.0.0.1.
- Docs rewritten for the current `C:\Dev\NAS` and `C:\NAS-Local\nas-data` layout.
- Tests: 18.

## 0.1.0

Initial conservative Cleaner scaffold. Dry-run scanner/planner, shared nas-data root, reports, CLI, dashboard, and tests.
