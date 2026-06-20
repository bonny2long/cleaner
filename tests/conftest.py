from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from cleaner.config import CleanerConfig


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "nas-data"
    config = CleanerConfig(data_root=root)
    config.ensure_shared_directories()
    return root


@pytest.fixture
def config(data_root: Path) -> CleanerConfig:
    return CleanerConfig(data_root=data_root, min_age_days=14)


def make_old(path: Path, days: int = 15) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def write_manifest(data_root: Path, source_rel: str, destination_rel: str = "Movies/Library/2000 - Test/Test.mkv", status: str = "moved") -> Path:
    dest = data_root / destination_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("media", encoding="utf-8")
    manifest_dir = dest.parent / "metadata"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": "v1",
        "archive_assistant_version": "test",
        "created_at": "2026-01-01T00:00:00Z",
        "batch_id": 1,
        "source_path": source_rel,
        "detected_type": "video_movie",
        "review_type": "video_movie",
        "status_after_move": status,
        "metadata_confirmed": True,
        "metadata_locked_for_move": True,
        "files_moved": [
            {
                "source_relative": "Test.mkv",
                "destination_relative": destination_rel,
                "role": "media_file",
                "size_bytes": 5,
                "format": "MKV",
            }
        ],
        "artwork_moved": [],
        "subtitles_moved": [],
        "failed_moves": [],
        "destination_roots": [str(Path(destination_rel).parent).replace("\\", "/")],
    }
    path = manifest_dir / "move_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path
