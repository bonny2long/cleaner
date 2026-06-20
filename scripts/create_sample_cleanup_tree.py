from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    data_root = Path(os.getenv("DATA_ROOT", "../nas-data"))
    ready = data_root / "_INGEST" / "ready"
    reports = data_root / "_REPORTS" / "cleaner"
    movie_dest = data_root / "Movies" / "Library" / "2020 - Example Movie"
    manifest_dir = movie_dest / "metadata"

    for path in [ready, reports, manifest_dir, data_root / "_INGEST" / "incoming", data_root / "_INGEST" / "leftover-review", data_root / "_QUARANTINE"]:
        path.mkdir(parents=True, exist_ok=True)

    source = ready / "Example Movie"
    source.mkdir(parents=True, exist_ok=True)
    movie_file = movie_dest / "Example Movie.mkv"
    movie_file.parent.mkdir(parents=True, exist_ok=True)
    movie_file.write_text("sample destination", encoding="utf-8")

    old_time = time.time() - (15 * 86400)
    os.utime(source, (old_time, old_time))

    manifest = {
        "manifest_version": "v1",
        "archive_assistant_version": "sample",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": 1,
        "source_path": "_INGEST/ready/Example Movie",
        "detected_type": "video_movie",
        "review_type": "video_movie",
        "status_after_move": "moved",
        "metadata_confirmed": True,
        "metadata_locked_for_move": True,
        "files_moved": [
            {
                "source_relative": "Example Movie.mkv",
                "destination_relative": "Movies/Library/2020 - Example Movie/Example Movie.mkv",
                "role": "media_file",
                "size_bytes": 18,
                "format": "MKV",
            }
        ],
        "artwork_moved": [],
        "subtitles_moved": [],
        "failed_moves": [],
        "destination_roots": ["Movies/Library/2020 - Example Movie"],
    }
    (manifest_dir / "move_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Sample cleanup tree created under {data_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
