# NAS Cleaner

Cleaner is the fourth app in Bonny's NAS workflow. It looks at what is left in the ingest lanes after Archive Assistant has moved media into the final libraries, and decides what is safe to clean up.

```text
Intake Watcher     Is the upload finished?
Archive Assistant  What is it, and where should it go after approval?
Cleaner            After approved moves, what leftovers are safe to clean?
BM Radio           Plays the final Music and Audiobooks libraries.
```

Cleaner never deletes files. Its only real action today is removing **empty folders** that a person has reviewed, and only when every production gate is switched on. Everything else is reported for review.

## Where it lives

| What | Local path | NAS path |
|---|---|---|
| Code | `C:\Dev\NAS\cleaner` | container image |
| Data root | `C:\NAS-Local\nas-data` | `/mnt/rust-pool` mounted at `/app/data` |
| Reports | `C:\NAS-Local\nas-data\_REPORTS\cleaner` | `/app/data/_REPORTS/cleaner` |
| Dashboard | http://127.0.0.1:8092 | private LAN or Tailscale only |

## Timing model

| Setting | Default | Meaning |
|---|---|---|
| `MIN_AGE_DAYS` | `30` | A leftover must be untouched for 30 days before Cleaner will consider it. Age is measured from the newest modification time anywhere inside the item. |
| `CHECK_INTERVAL_SECONDS` | `604800` (7 days) | How often the dashboard writes a plan automatically when `AUTO_RUN=true`. |
| Trash hold | 14 days, **planned** | Agreed design: a cleaned item moves to a trash holding area and is purged 14 days later. **Not built yet.** Today, empty-folder removal is immediate once approved. |

## What Cleaner classifies

| Category | Meaning | Action today |
|---|---|---|
| `safe_empty_folder` | Folder tree with no files, backed by a verified Archive Assistant move record | Removable when production gates are on |
| `known_harmless_trash` | Only junk files such as `Thumbs.db`, `.DS_Store`, `.tmp` | Report only |
| `uncertain_leftover` | Anything else left behind (sidecars, logs, unmoved media) | Report only |
| `quarantine_hold` | Anything in `_QUARANTINE` | Never touched |
| `do_not_touch` | Final libraries, Photos, Documents, Projects, Backups, active upload lanes | Never touched |
| `blocked_too_new` | Younger than `MIN_AGE_DAYS` | Waits |
| `blocked_by_missing_evidence` | No Archive Assistant move record matches | Waits for evidence |
| `blocked_by_destination_missing` | Move record exists but the moved files are missing | Flagged as critical |

Cleaner scans `_INGEST/ready`, `_INGEST/leftover-review`, `_INGEST/failed`, `_STAGING` and `_QUARANTINE`. It ignores `_INGEST/incoming` and `_INGEST/intake-processing`, which belong to Intake Watcher.

## Modes and gates

Default mode is **report-only**:

```env
CLEANER_MODE=development
DRY_RUN=true
DESTRUCTIVE_ACTIONS_ENABLED=false
ALLOW_EMPTY_FOLDER_REMOVAL=false
```

Empty-folder removal runs only when **all four** are set:

```env
CLEANER_MODE=production
DRY_RUN=false
DESTRUCTIVE_ACTIONS_ENABLED=true
ALLOW_EMPTY_FOLDER_REMOVAL=true
```

Even then, a removal must pass every check at the moment it runs:

- the folder appears in a plan report you wrote and reviewed less than 24 hours ago;
- it is still classified `safe_empty_folder` in a fresh plan;
- it is inside `_INGEST/ready`, `_INGEST/failed` or `_STAGING`, and is not the lane root itself;
- it is not quarantine, leftover-review, or a link or junction;
- its whole tree still contains no files.

Removal deletes folders bottom-up with `rmdir` only. If a file appears mid-way, the removal stops. Each run writes `execution-<run id>.json` listing every removed folder so it can be recreated.

`ALLOW_KNOWN_TRASH_DELETE`, `ALLOW_LEFTOVER_REVIEW_MOVES` and `ALLOW_QUARANTINE_ROUTING` exist in configuration but no working action is wired to them yet. Leave them `false`.

## Evidence Cleaner reads

Cleaner reads Archive Assistant's JSON **move manifests**. It never imports Archive Assistant code or reads its database. See [docs/ARCHIVE_ASSISTANT_EVIDENCE.md](docs/ARCHIVE_ASSISTANT_EVIDENCE.md).

## Local setup

```powershell
Set-Location C:\Dev\NAS\cleaner
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
Copy-Item .env.example .env   # then set DATA_ROOT=C:/NAS-Local/nas-data
```

## Commands

```powershell
.\.venv\Scripts\python.exe -m cleaner.server --host 127.0.0.1 --port 8092   # dashboard
.\.venv\Scripts\python.exe -m cleaner.cli dry-run                           # write a plan report
.\.venv\Scripts\python.exe -m cleaner.cli status                            # counts only
.\.venv\Scripts\python.exe -m cleaner.cli inspect                           # raw scan items
.\.venv\Scripts\python.exe -m cleaner.cli ensure-folders                    # create the shared folder layout
.\.venv\Scripts\python.exe -m cleaner.cli execute --run-id cleaner-YYYYMMDD-HHMMSS
.\.venv\Scripts\python.exe -m pytest -q                                     # tests
```

On the dashboard, **Run dry plan** (or **Write plan to review** when execution is enabled) writes a plan report. **Remove N empty folders** appears only when all production gates are on, and acts only on the plan you just wrote.

## Known limitations

- When one download produced several move records (for example a discography split into albums), Cleaner keeps only one record per source folder when checking destinations.
- Cleaner does not yet ask Archive Assistant whether any batch from a folder is still pending review. A folder that still holds unmoved media is reported as `uncertain_leftover`, never removed, because it is not empty.
- Cleaner does not yet read Archive Assistant **disposition records** (quarantine, discard, reject). Discarded quarantine items stay on disk.
- The 14-day trash hold is not built.

## Roadmap

1. Read all move records per source folder and Archive Assistant disposition records.
2. Ask Archive Assistant for pending batches before acting on a folder.
3. Add a Cleaner SQLite ledger for first-seen dates, plan identity, and the action log.
4. Add the trash holding area with a 14-day purge, then known-junk cleanup and approved quarantine discards.
