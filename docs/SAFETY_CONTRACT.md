# Cleaner Safety Contract

Cleaner is report-only by default. It never deletes a file.

## Cleaner must never

```text
delete files
mutate embedded tags
write inside final libraries (Music, Movies, TV, Books, Audiobooks)
touch Photos, Documents, Projects, Backups
touch _INGEST/incoming or _INGEST/intake-processing
touch _QUARANTINE or _INGEST/leftover-review
act without proof: an Archive Assistant move record, or a byte-for-byte copy already in a final library, or a person's recorded discard decision
treat an unrecorded folder as removable unless every media file in it is proven to be a copy of library content
act on a quarantined item nobody approved for discard, or whose files changed since the decision
act on anything younger than MIN_AGE_DAYS (30)
act on anything not in a plan a person reviewed
act on a POST from a web page on another site (Origin must be loopback or listed in ALLOWED_ORIGINS)
```

## Cleaner may write

```text
_REPORTS/cleaner/<run id>.json and .md
_REPORTS/cleaner/latest-plan.json
_REPORTS/cleaner/execution-<run id>.json
_REPORTS/cleaner/cleaner-log.jsonl
```

## The one enabled action: remove a reviewed empty folder

Required gates, all at once:

```text
CLEANER_MODE=production
DRY_RUN=false
DESTRUCTIVE_ACTIONS_ENABLED=true
ALLOW_EMPTY_FOLDER_REMOVAL=true
```

Checks at execution time, all fail-closed:

```text
the action, path and category are in a reviewed plan under 24 hours old
a fresh plan still classifies it safe_empty_folder (evidence verified, age >= 30 days)
path is inside _INGEST/ready, _INGEST/failed or _STAGING and is not the lane root
path is not quarantine, leftover-review, a link, or a junction
the whole folder tree contains no files
```

Removal uses `rmdir` bottom-up, so a file appearing mid-removal stops it. Every removal is logged with enough detail to recreate the folder.

## Before any further action is enabled

Cleaner now recognises verified duplicates, approved quarantine discards and unrecorded leftovers (it reads Archive Assistant's disposition records and compares content with the libraries), but only reports them. Acting on them, and on known junk, stays disabled until Cleaner checks for pending Archive Assistant batches, reads every move record per source folder, and routes removals through a 14-day trash hold that keeps them recoverable.
