from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KNOWN_TRASH_NAMES = (
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "ehthumbs.db",
)

DEFAULT_KNOWN_TRASH_SUFFIXES = (
    ".tmp",
    ".temp",
    ".bak",
)

SHARED_NAS_FOLDERS = (
    "_INGEST/incoming",
    "_INGEST/intake-processing",
    "_INGEST/ready",
    "_INGEST/failed",
    "_INGEST/leftover-review",
    "_STAGING",
    "_QUARANTINE",
    "_REPORTS/intake-watcher",
    "_REPORTS/archive-assistant",
    "_REPORTS/cleaner",
    "Music/Library/FLAC",
    "Music/Library/MP3",
    "Music/Discographies",
    "Music/Metadata",
    "Music/Playlists",
    "Movies/Library",
    "Movies/Metadata",
    "TV/Library",
    "TV/Metadata",
    "Books/EPUB",
    "Books/PDF",
    "Books/Metadata",
    "Audiobooks/Library",
    "Audiobooks/Metadata",
)


def load_env_file(path: Path = Path(".env")) -> None:
    """Small .env loader to keep this project dependency-free."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return Path(raw)


@dataclass(frozen=True)
class CleanerConfig:
    data_root: Path = Path("../nas-data")
    mode: str = "development"
    dry_run: bool = True
    destructive_actions_enabled: bool = False
    auto_run: bool = False
    check_interval_seconds: int = 7 * 24 * 60 * 60
    min_age_days: int = 14
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8092
    allow_empty_folder_removal: bool = False
    allow_leftover_review_moves: bool = False
    allow_quarantine_routing: bool = False
    allow_known_trash_delete: bool = False
    ignore_incoming: bool = True
    ignore_processing: bool = True
    known_trash_names: tuple[str, ...] = DEFAULT_KNOWN_TRASH_NAMES
    known_trash_suffixes: tuple[str, ...] = DEFAULT_KNOWN_TRASH_SUFFIXES
    cleaner_reports_dir_override: Path | None = None
    leftover_review_dir_override: Path | None = None
    quarantine_dir_override: Path | None = None

    @classmethod
    def from_env(cls) -> "CleanerConfig":
        load_env_file()
        data_root = _env_path("DATA_ROOT", Path("../nas-data"))
        return cls(
            data_root=data_root,
            mode=os.getenv("CLEANER_MODE", "development").strip().lower(),
            dry_run=_env_bool("DRY_RUN", True),
            destructive_actions_enabled=_env_bool("DESTRUCTIVE_ACTIONS_ENABLED", False),
            auto_run=_env_bool("AUTO_RUN", False),
            check_interval_seconds=_env_int("CHECK_INTERVAL_SECONDS", 7 * 24 * 60 * 60),
            min_age_days=_env_int("MIN_AGE_DAYS", 14),
            dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
            dashboard_port=_env_int("DASHBOARD_PORT", 8092),
            allow_empty_folder_removal=_env_bool("ALLOW_EMPTY_FOLDER_REMOVAL", False),
            allow_leftover_review_moves=_env_bool("ALLOW_LEFTOVER_REVIEW_MOVES", False),
            allow_quarantine_routing=_env_bool("ALLOW_QUARANTINE_ROUTING", False),
            allow_known_trash_delete=_env_bool("ALLOW_KNOWN_TRASH_DELETE", False),
            ignore_incoming=_env_bool("IGNORE_INCOMING", True),
            ignore_processing=_env_bool("IGNORE_PROCESSING", True),
            cleaner_reports_dir_override=_env_path("CLEANER_REPORTS_DIR", Path("")) if os.getenv("CLEANER_REPORTS_DIR") else None,
            leftover_review_dir_override=_env_path("LEFTOVER_REVIEW_DIR", Path("")) if os.getenv("LEFTOVER_REVIEW_DIR") else None,
            quarantine_dir_override=_env_path("QUARANTINE_DIR", Path("")) if os.getenv("QUARANTINE_DIR") else None,
        )

    @property
    def ingest_root(self) -> Path:
        return self.data_root / "_INGEST"

    @property
    def incoming_dir(self) -> Path:
        return self.ingest_root / "incoming"

    @property
    def processing_dir(self) -> Path:
        return self.ingest_root / "intake-processing"

    @property
    def ready_dir(self) -> Path:
        return self.ingest_root / "ready"

    @property
    def failed_dir(self) -> Path:
        return self.ingest_root / "failed"

    @property
    def leftover_review_dir(self) -> Path:
        return self.leftover_review_dir_override or (self.ingest_root / "leftover-review")

    @property
    def staging_dir(self) -> Path:
        return self.data_root / "_STAGING"

    @property
    def quarantine_dir(self) -> Path:
        return self.quarantine_dir_override or (self.data_root / "_QUARANTINE")

    @property
    def reports_root(self) -> Path:
        return self.data_root / "_REPORTS"

    @property
    def archive_reports_dir(self) -> Path:
        return self.reports_root / "archive-assistant"

    @property
    def cleaner_reports_dir(self) -> Path:
        return self.cleaner_reports_dir_override or (self.reports_root / "cleaner")

    @property
    def cleaner_log_path(self) -> Path:
        return self.cleaner_reports_dir / "cleaner-log.jsonl"

    def ensure_shared_directories(self) -> None:
        for folder in SHARED_NAS_FOLDERS:
            (self.data_root / folder).mkdir(parents=True, exist_ok=True)

    def ensure_report_directories(self) -> None:
        self.cleaner_reports_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if self.mode not in {"development", "production"}:
            raise ValueError("CLEANER_MODE must be development or production")
        if self.check_interval_seconds < 3600:
            raise ValueError("CHECK_INTERVAL_SECONDS cannot be less than 3600; hourly is the fastest supported cadence")
        if self.min_age_days < 0:
            raise ValueError("MIN_AGE_DAYS cannot be negative")
        if self.mode == "development" and self.destructive_actions_enabled:
            raise ValueError("development mode cannot enable destructive actions")
        if self.dry_run and self.destructive_actions_enabled:
            raise ValueError("DRY_RUN=true cannot enable destructive actions")
