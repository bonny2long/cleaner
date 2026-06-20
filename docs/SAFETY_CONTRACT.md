# Cleaner Safety Contract

MVP is dry-run first.

Cleaner must not:

```text
delete files
delete folders
move files
mutate embedded tags
write final library folders
clean _INGEST/incoming
clean _INGEST/intake-processing
delete quarantine/rejected files
act without Archive Assistant evidence
act on items younger than MIN_AGE_DAYS
```

Cleaner may write only:

```text
nas-data/_REPORTS/cleaner/*.json
nas-data/_REPORTS/cleaner/*.md
nas-data/_REPORTS/cleaner/cleaner-log.jsonl
```

Future production execution requires all of these gates:

```text
CLEANER_MODE=production
DRY_RUN=false
DESTRUCTIVE_ACTIONS_ENABLED=true
explicit ALLOW_* flag enabled
Archive Assistant evidence exists
candidate age >= MIN_AGE_DAYS
destination verification passed
planned action is logged
```
