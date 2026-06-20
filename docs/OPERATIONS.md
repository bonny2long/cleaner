# Operations

Normal first-stage operation:

```text
1. Intake Watcher promotes completed uploads to _INGEST/ready.
2. Archive Assistant scans, reviews, approves, moves, and writes manifests/logs.
3. Cleaner runs dry-run weekly.
4. Bonny reviews _REPORTS/cleaner/latest-plan.json or dashboard lanes.
```

Cleaner should be boring. A good report says what is safe, what is blocked, and why.
