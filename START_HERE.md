# START HERE

This scaffold creates `nas-cleaner`, the third app in Bonny's local NAS workflow.

1. Put this project beside the other NAS apps:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-cleaner
```

2. Create `.env` from `.env.example` and set:

```env
DATA_ROOT=C:/Users/BonnyMakaniankhondo/Documents/GitHub/NAS/nas-data
```

3. Run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m cleaner.cli ensure-folders
python -m cleaner.cli dry-run
python -m cleaner.server --host 127.0.0.1 --port 8092
```

4. Open:

```text
http://127.0.0.1:8092
```

Cleaner MVP writes reports only. It does not delete files or folders.
