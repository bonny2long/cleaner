# Testing

```powershell
Set-Location C:\Dev\NAS\cleaner
.\.venv\Scripts\python.exe -m pytest -q
```

126 tests. They use temporary folders only and never touch the real data root.

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
a refused request that carries a large body still gets a clean 403, never a dropped connection
manifests are found at every layout Archive Assistant writes, and only inside the evidence folders
the evidence scan lists each folder once and never opens individual files
the dashboard may reuse evidence for 60 seconds; written plans and executions never do
a folder with no Archive Assistant record is a verified duplicate only when every media file is a byte copy of a library file (names do not matter)
same size but different bytes, a new media file, an unknown file type, or only artwork keeps it an unrecorded leftover
hashing respects a time budget and finishes on a later run
an approved quarantine discard is picked up; undecided, revoked, restored, changed or out-of-quarantine decisions are not
nothing picked up is touched, even with every production gate open
the dashboard shows the new lanes and counts
```
