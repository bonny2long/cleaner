# NAS Deployment

Production mapping:

```text
/mnt/rust-pool -> /app/data
/app/data/_REPORTS/cleaner -> Cleaner reports
```

Keep Cleaner private. Use LAN, Tailscale, or VPN. Do not expose the dashboard publicly.

Initial NAS environment should still be safe:

```env
DATA_ROOT=/app/data
CLEANER_MODE=development
DRY_RUN=true
DESTRUCTIVE_ACTIONS_ENABLED=false
MIN_AGE_DAYS=14
CHECK_INTERVAL_SECONDS=604800
```
