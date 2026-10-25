# Testing

```powershell
Set-Location C:\Dev\NAS\cleaner
.\.venv\Scripts\python.exe -m pytest -q
```

54 tests. They use temporary folders only and never touch the real data root.

What they prove:

```text
destructive actions are disabled by default (report-only)
default timing is a weekly check and a 30-day age gate
incoming is ignored by default
quarantine is never deleted
missing evidence blocks cleanup
missing destinations block cleanup
items younger than MIN_AGE_DAYS are blocked
uncertain leftovers stay report-only
reports are written under _REPORTS/cleaner
a reviewed empty folder is removed and reported; leftovers with files are kept
a folder added after the review is skipped
a folder that gained a file after the review is kept
quarantine, final-library folders and lane roots are refused even when empty
a stale (over 24 hours) or malformed reviewed plan is refused
execution is refused while report-only
empty disc sub-folders (CD 1, CD 2) count as empty and are all removed
a tree with a file anywhere inside is never removed
CD-rip logs left after a verified move are labeled known_harmless_trash (report only)
rip-log matching ignores case and rejects look-alikes such as Dracula.txt
rip logs next to unmoved audio, without move evidence, or under 30 days old are not labeled
execution never touches a rip-log folder, even with every production gate on
a POST from another site is refused (403) before it can write a plan or start an execution
the dashboard's own address, listed LAN origins and plain clients such as curl still work
```
