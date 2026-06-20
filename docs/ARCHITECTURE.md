# NAS Cleaner Architecture

Cleaner is a separate Python app. It reads the shared `nas-data` root, reads Archive Assistant move evidence, scans cleanup candidate lanes, classifies leftovers, creates a dry-run plan, and writes reports under `_REPORTS/cleaner`.

It does not import Archive Assistant or Intake Watcher modules. The interface between systems is the filesystem and the JSON/Markdown reports already written by each app.

## Modules

```text
config.py       environment variables, paths, shared folder creation
models.py       dataclasses for evidence, scan items, classifications, actions, plans
evidence.py     Archive Assistant move manifest discovery and destination verification
scanner.py      candidate folder/file scan under shared nas-data lanes
classifier.py   conservative category assignment
planner.py      dry-run action plan builder
executor.py     production-gated future execution layer
reports.py      JSON/Markdown report writer and JSONL event log
cli.py          local operator CLI
server.py       lightweight dashboard server
web/            static dashboard UI
```
