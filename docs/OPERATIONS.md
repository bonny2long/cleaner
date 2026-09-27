# Operations

Normal flow:

```text
1. Intake Watcher promotes finished uploads to _INGEST/ready.
2. Archive Assistant scans, you review and approve, it moves media and writes manifests.
3. Downloads left in ready become leftovers. After 30 days untouched, Cleaner considers them.
4. Cleaner writes a plan (weekly when AUTO_RUN=true, or on demand).
5. You review the plan on the dashboard or in _REPORTS/cleaner/latest-plan.json.
6. If production gates are on, remove the reviewed empty folders from the dashboard.
```

Reading the dashboard:

| Lane | Meaning |
|---|---|
| Safe Empty Folders | Folders with no files and verified move evidence |
| Waiting 30-Day Gate | Leftovers younger than `MIN_AGE_DAYS` |
| Leftovers Need Review | Folders still holding files: sidecars, logs, or unmoved media |
| Blocked by Safety | Missing or broken Archive Assistant evidence |
| Quarantine / Protected | Quarantine and protected areas, never touched |

Reports live in `_REPORTS/cleaner`: `<run id>.json`, `<run id>.md`, `latest-plan.json`, `execution-<run id>.json`, and the `cleaner-log.jsonl` event log.

A good report says what is safe, what is blocked, and why. When in doubt, Cleaner leaves things alone.
