# START HERE

Cleaner finds leftovers in the NAS ingest lanes after Archive Assistant moves media, and reports what is safe to clean. By default it is report-only and never deletes anything.

1. Set up once:

```powershell
Set-Location C:\Dev\NAS\cleaner
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
Copy-Item .env.example .env
```

2. In `.env`, point at the shared data root:

```env
DATA_ROOT=C:/NAS-Local/nas-data
```

3. Start the dashboard and open http://127.0.0.1:8092:

```powershell
.\.venv\Scripts\python.exe -m cleaner.server --host 127.0.0.1 --port 8092
```

4. Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Leftovers must be 30 days old before Cleaner considers them. See [README.md](README.md) for the full timing model, the production gates for empty-folder removal, and known limitations.
