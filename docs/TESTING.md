# Testing

Run:

```powershell
python -m pytest
```

Required proof:

```text
destructive actions disabled by default
incoming ignored by default
quarantine never deleted
missing evidence blocks cleanup
destination missing blocks cleanup
items younger than MIN_AGE_DAYS are blocked
reports are written under _REPORTS/cleaner
```
