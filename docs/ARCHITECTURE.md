# NAS Cleaner Architecture

Cleaner is a separate, dependency-free Python app. It reads the shared NAS data root and Archive Assistant's move manifests, scans the cleanup lanes, classifies leftovers, and writes plan reports under `_REPORTS/cleaner`. When every production gate is on, it can remove reviewed empty folders.

It does not import Archive Assistant, Intake Watcher or BM Radio code, and it does not read their databases. The interface between the apps is the filesystem and the JSON reports each app writes.

## Flow

```text
evidence.py   find Archive Assistant move manifests, verify destinations exist
scanner.py    list top-level items in ready, leftover-review, failed, staging, quarantine
classifier.py assign a category (safe_empty_folder, uncertain_leftover, blocked_*, ...)
planner.py    map each category to an action allowed by the current config
reports.py    write <run id>.json, <run id>.md, latest-plan.json, cleaner-log.jsonl
executor.py   run allowed actions from a reviewed plan (empty-folder removal only)
```

## Modules

```text
config.py      environment variables, derived paths, shared folder creation, validation
models.py      dataclasses for evidence, scan items, classifications, actions, plans
evidence.py    manifest discovery and destination verification
scanner.py     candidate scan; a folder tree with no files counts as empty
classifier.py  conservative category assignment and the MIN_AGE_DAYS gate
planner.py     action per category, gated by mode and ALLOW_* flags
executor.py    reviewed-plan execution with fail-closed checks and execution reports
reports.py     JSON/Markdown reports and JSONL event log
cli.py         ensure-folders, inspect, plan, dry-run, status, execute, serve
server.py      dashboard HTTP server and API
web/           static dashboard UI
```

## HTTP API

```text
GET  /api/health       service check
GET  /api/dashboard    lanes, counts, config, latest reviewed plan
GET  /api/plan         a fresh plan (not written)
POST /api/run-dry-plan write a plan report
POST /api/execute      {"run_id": "..."} run allowed actions from that reviewed plan
POST /api/ensure-folders create the shared folder layout
```

`/api/execute` returns 409 while Cleaner is report-only.

## Execution safety

An action runs only if the same action, path and category appear in both the reviewed plan (less than 24 hours old) and a fresh plan built at execution time. Each target is checked again immediately before removal. See [SAFETY_CONTRACT.md](SAFETY_CONTRACT.md).
