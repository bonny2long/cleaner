# IDE AI Prompt — Create NAS Cleaner App in Shared Local NAS System

Use this prompt in the IDE AI inside Bonny's NAS workspace.

## Goal

Create a new separate app named `nas-cleaner` beside Intake Watcher and Archive Assistant. It must share the same local NAS-style data root:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data
```

The app must fit into the three-app flow:

```text
nas-data/_INGEST/incoming
  -> Intake Watcher watches active copies/downloads
nas-data/_INGEST/ready
  -> Archive Assistant scans, reviews, approves, moves, and writes manifests/logs
nas-data/_REPORTS/cleaner
  -> Cleaner writes dry-run cleanup reports
nas-data/_INGEST/leftover-review
  -> Cleaner/human review lane for uncertain leftovers later
```

## Required app location

Create the app here:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-cleaner
```

Do not place Cleaner inside Intake Watcher. Do not place Cleaner inside Archive Assistant. Do not modify either existing app for this first Cleaner scaffold.

## Hard boundaries

Cleaner must not:

```text
delete files
delete folders
move files in MVP
organize media
scan active uploads in _INGEST/incoming
scan _INGEST/intake-processing
write final library folders
mutate embedded metadata
import Archive Assistant modules
import Intake Watcher modules
run or depend on Archive Assistant reset behavior
delete or clean quarantine files
```

Cleaner may write only:

```text
nas-data/_REPORTS/cleaner/*.json
nas-data/_REPORTS/cleaner/*.md
nas-data/_REPORTS/cleaner/cleaner-log.jsonl
```

## Config defaults

Create `.env.example` and `.env` using:

```env
DATA_ROOT=C:/Users/BonnyMakaniankhondo/Documents/GitHub/NAS/nas-data
CLEANER_MODE=development
DRY_RUN=true
DESTRUCTIVE_ACTIONS_ENABLED=false
AUTO_RUN=false
CHECK_INTERVAL_SECONDS=604800
MIN_AGE_DAYS=14
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8092
CLEANER_REPORTS_DIR=C:/Users/BonnyMakaniankhondo/Documents/GitHub/NAS/nas-data/_REPORTS/cleaner
LEFTOVER_REVIEW_DIR=C:/Users/BonnyMakaniankhondo/Documents/GitHub/NAS/nas-data/_INGEST/leftover-review
QUARANTINE_DIR=C:/Users/BonnyMakaniankhondo/Documents/GitHub/NAS/nas-data/_QUARANTINE
ALLOW_EMPTY_FOLDER_REMOVAL=false
ALLOW_LEFTOVER_REVIEW_MOVES=false
ALLOW_QUARANTINE_ROUTING=false
ALLOW_KNOWN_TRASH_DELETE=false
IGNORE_INCOMING=true
IGNORE_PROCESSING=true
```

Use `CHECK_INTERVAL_SECONDS=604800` for weekly checks and `MIN_AGE_DAYS=14` so Cleaner only plans cleanup for items at least two weeks old.

## Shared folder skeleton to create if missing

```text
nas-data/
  _INGEST/
    incoming/
    intake-processing/
    ready/
    failed/
    leftover-review/
  _STAGING/
  _QUARANTINE/
  _REPORTS/
    intake-watcher/
    archive-assistant/
    cleaner/
  Music/
    Library/
      FLAC/
      MP3/
    Discographies/
    Metadata/
    Playlists/
  Movies/
    Library/
    Metadata/
  TV/
    Library/
    Metadata/
  Books/
    EPUB/
    PDF/
    Metadata/
  Audiobooks/
    Library/
    Metadata/
```

Do not delete old app-owned `data` folders. Do not migrate media automatically.

## Build style

Use a Python standard-library-first app similar to Intake Watcher. Use a simple static dashboard served by Python's `http.server`, not React for the MVP.

Use the same visual language as Archive Assistant and Intake Watcher:

```text
dark page background #0f1117
panel #161b27
raised panel #1e2535
hover #242c3d
text #f0f2f7
muted #8892a4
blue #3b82f6
green #22c55e
amber #f59e0b
red #ef4444
1500px wide shell
compact cards
status pills
lane-based dashboard
```

## Required project structure

```text
nas-cleaner/
  README.md
  pyproject.toml
  Dockerfile
  docker-compose.nas.yml
  .env.example
  cleaner/
    __init__.py
    config.py
    models.py
    evidence.py
    scanner.py
    classifier.py
    planner.py
    executor.py
    reports.py
    cli.py
    server.py
    web/
      index.html
      app.js
      styles.css
  docs/
    ARCHITECTURE.md
    SAFETY_CONTRACT.md
    ARCHIVE_ASSISTANT_EVIDENCE.md
    LOCAL_DEVELOPMENT.md
    NAS_DEPLOYMENT.md
    OPERATIONS.md
    TESTING.md
    CHANGELOG.md
  scripts/
    create_sample_cleanup_tree.py
    run_once.py
  tests/
    test_no_delete_by_default.py
    test_weekly_age_gate.py
    test_empty_folder_detection.py
    test_missing_evidence_blocks_cleanup.py
    test_destination_missing_blocks_cleanup.py
    test_incoming_is_never_touched.py
    test_quarantine_is_never_deleted.py
    test_uncertain_leftovers_go_to_review_plan.py
    test_report_written.py
```

## Core behavior

Implement these commands:

```powershell
python -m cleaner.cli ensure-folders
python -m cleaner.cli inspect
python -m cleaner.cli plan
python -m cleaner.cli dry-run
python -m cleaner.cli status
python -m cleaner.cli serve
python -m cleaner.server --host 127.0.0.1 --port 8092
```

Dashboard endpoints:

```text
GET  /api/health
GET  /api/dashboard
GET  /api/plan
POST /api/run-dry-plan
POST /api/ensure-folders
```

## Evidence rules

Cleaner reads Archive Assistant evidence from move manifests only. Search under `DATA_ROOT` for:

```text
**/move_manifest.json
**/*_move_manifest.json
```

Useful manifest fields:

```text
source_path
created_at
batch_id
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
```

A moved item is eligible only when:

```text
status_after_move is moved or rejected
failed_moves is empty
destination files or destination roots can be verified
source candidate is at least MIN_AGE_DAYS old
source candidate is not in incoming or intake-processing
```

## Classifications

Use these categories:

```text
safe_empty_folder
known_harmless_trash
uncertain_leftover
rejected_or_unsupported
quarantine_hold
blocked_by_missing_evidence
blocked_by_destination_missing
blocked_too_new
do_not_touch
```

## MVP actions

MVP actions are dry-run/report actions only:

```text
remove_empty_folder_dry_run
move_to_leftover_review_dry_run
known_trash_report_only
report_only
blocked_no_action
```

Do not implement real delete buttons in the UI. Do not add a one-click clean action.

## Tests must pass

Run:

```powershell
python -m pytest
```

Required result:

```text
all tests pass
```

Tests must prove:

```text
no destructive actions occur by default
_INTAKE/incoming or _INGEST/incoming is ignored by default
_QUARANTINE is never deleted
missing Archive Assistant evidence blocks cleanup
destination-missing blocks cleanup
items younger than MIN_AGE_DAYS are blocked
uncertain leftovers are not deleted
reports are written to _REPORTS/cleaner
```

## Done criteria

```text
nas-cleaner exists beside the other NAS apps
.env points to shared nas-data
ensure-folders creates/verifies the shared skeleton
CLI dry-run writes JSON and Markdown reports under nas-data/_REPORTS/cleaner
dashboard works at http://127.0.0.1:8092
UI uses the same dark styling as the other systems
Cleaner does not modify Intake Watcher or Archive Assistant
Cleaner does not delete or move media in MVP
all tests pass
```
