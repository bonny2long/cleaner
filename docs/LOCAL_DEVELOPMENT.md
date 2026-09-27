# Local Development

Canonical local layout (runbook v12):

```text
C:\Dev\NAS\intake-watcher
C:\Dev\NAS\archive_assistant
C:\Dev\NAS\cleaner
C:\Dev\NAS\BM_radio
C:\NAS-Local\nas-data          shared data root
C:\NAS-Local\Restock           master copies of the test downloads
C:\NAS-Local\Backups           verified backups
```

Old copies under `Documents\GitHub` are frozen backups. Do not run or edit them.

Setup:

```powershell
Set-Location C:\Dev\NAS\cleaner
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
Copy-Item .env.example .env
```

Daily use:

```powershell
.\.venv\Scripts\python.exe -m cleaner.server --host 127.0.0.1 --port 8092
.\.venv\Scripts\python.exe -m cleaner.cli dry-run
.\.venv\Scripts\python.exe -m pytest -q
```

To test empty-folder removal on copied data, set the four production gates in `.env` (see [README.md](../README.md)) and restart the dashboard. Keep a report-only copy of `.env` to switch back.
