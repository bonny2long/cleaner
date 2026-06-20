# Local Development

Place this project beside the other local NAS apps:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\intake-watccher
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\archive-assistant-scaffold\archive-assistant-scaffold
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-cleaner
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data
```

Use:

```powershell
python -m cleaner.cli ensure-folders
python -m cleaner.cli inspect
python -m cleaner.cli dry-run
python -m cleaner.server --host 127.0.0.1 --port 8092
```
