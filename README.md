# NAS Cleaner

NAS Cleaner is the third app in Bonny's local NAS workflow. It is separate from Intake Watcher and Archive Assistant.

```text
Intake Watcher  = Is the upload finished?
Archive Assistant = What is it, what needs review, and where should it go after approval?
Cleaner = After approved moves, what safe leftovers can be cleaned or sent to review?
```

MVP behavior is read-only except writing Cleaner reports. It does not delete files, delete folders, move files, organize media, or import code from the other two apps.

## Shared local root

Preferred local root:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data
```

The default `.env.example` uses `DATA_ROOT=../nas-data` so this project can sit beside Intake Watcher and Archive Assistant under:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-cleaner
```

## Folder ownership

```text
nas-data/_INGEST/incoming          Intake Watcher watches active copies/downloads
nas-data/_INGEST/intake-processing Intake Watcher temporary promotion lane
nas-data/_INGEST/ready             Archive Assistant scan input; Cleaner inspects old leftovers only
nas-data/_INGEST/failed            Intake Watcher blocked/problem lane
nas-data/_INGEST/leftover-review   Cleaner/human review lane
nas-data/_STAGING                  Archive Assistant working area
nas-data/_QUARANTINE               Archive Assistant quarantine/review area; Cleaner reports only
nas-data/_REPORTS/intake-watcher   Intake Watcher logs
nas-data/_REPORTS/archive-assistant Archive Assistant logs/reports
nas-data/_REPORTS/cleaner          Cleaner reports
nas-data/Music                     Archive Assistant final music output
nas-data/Movies                    Archive Assistant final movie output
nas-data/TV                        Archive Assistant final TV output
nas-data/Books                     Archive Assistant final book output
nas-data/Audiobooks                Archive Assistant final audiobook output
```

## Local setup

```powershell
cd C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS
mkdir nas-cleaner
# copy this scaffold into nas-cleaner
cd nas-cleaner
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env
```

Edit `.env` if needed:

```env
DATA_ROOT=C:/Users/BonnyMakaniankhondo/Documents/GitHub/NAS/nas-data
CLEANER_MODE=development
DRY_RUN=true
DESTRUCTIVE_ACTIONS_ENABLED=false
CHECK_INTERVAL_SECONDS=604800
MIN_AGE_DAYS=14
DASHBOARD_PORT=8092
```

Create or verify the shared folder skeleton:

```powershell
python -m cleaner.cli ensure-folders
```

Run a dry plan:

```powershell
python -m cleaner.cli dry-run
```

Run the dashboard:

```powershell
python -m cleaner.server --host 127.0.0.1 --port 8092
```

Open:

```text
http://127.0.0.1:8092
```

## 7-day / 14-day timing model

Cleaner can run every 7 days, but candidates remain blocked until they are at least 14 days old. This is intentionally conservative so Cleaner does not race active uploads, recent Archive Assistant moves, or fresh local tests.

```env
CHECK_INTERVAL_SECONDS=604800
MIN_AGE_DAYS=14
```

## MVP safety rules

No automatic deletion by default. No file deletion in MVP. No folder deletion in MVP unless a later production phase deliberately enables it. No cleanup of `_INGEST/incoming` or `_INGEST/intake-processing`. No quarantine deletion. No final library writes. No cleanup without Archive Assistant evidence.

