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

## The trash hold

Cleaner recognises verified duplicates, approved quarantine discards, unrecorded leftovers and known junk. It only acts on them when `CLEANER_MODE=production`, `DRY_RUN=false`, `DESTRUCTIVE_ACTIONS_ENABLED=true` and `ALLOW_TRASH_HOLD=true` are all set (plus `ALLOW_QUARANTINE_DISCARD` for discards and `ALLOW_KNOWN_TRASH_DELETE` for junk), and then it only **moves the item aside**:

```text
the action, path and category are in a reviewed plan under 24 hours old
a fresh plan, built just now, still gives it the same category (duplicates re-proved by SHA-256)
unrecorded leftovers: you ticked this exact path; discards: the waiting period is over
the folder has the same file count, total size and newest change as when it was classified
path is inside _INGEST/ready, _INGEST/failed or _STAGING (or _QUARANTINE/<kind>/<item> for discards),
  is not a lane root or quarantine container, and contains no link or junction
the trash folder is on the same disk, and nothing exists at the item's place in the hold
```

The move is a rename, recorded in `trash-manifest.json` before it happens; nothing is copied, and nothing is overwritten. **Restore** needs no gate and refuses to overwrite. **Purge** is the only deletion: it needs `ALLOW_TRASH_PURGE`, an explicit list from you, an expired hold (`TRASH_HOLD_DAYS`, at least 1), a `in_trash` status, and held files that still match the recorded inventory. Cleaner never purges on its own.

## Still open before enabling it on real data

Cleaner does not yet ask Archive Assistant whether a batch from a folder is still pending review, and keeps one move record per source folder. The hold is recoverable and off by default, and duplicates are proved by content, but review the trash candidates in the dashboard before moving them.
