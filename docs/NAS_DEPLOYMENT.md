# NAS Deployment

TrueNAS deployment is planned, not done. Target mapping:

```text
/mnt/rust-pool                 -> /app/data   (media and ingest lanes)
/app/data/_REPORTS/cleaner     -> Cleaner reports
```

Keep Cleaner private. Use LAN, Tailscale, or VPN. Never forward its port publicly.

Start the NAS deployment report-only:

```env
DATA_ROOT=/app/data
CLEANER_MODE=development
DRY_RUN=true
DESTRUCTIVE_ACTIONS_ENABLED=false
MIN_AGE_DAYS=30
CHECK_INTERVAL_SECONDS=604800
AUTO_RUN=true
```

`docker-compose.nas.yml` uses these defaults. Cleaner needs read access to the ingest lanes and write access only to `_REPORTS/cleaner` while report-only. Give it write access to the ingest lanes only when empty-folder removal is deliberately enabled.

ZFS snapshots of the rust-pool are a second safety net for any cleanup action. Take one before the first production run.
