from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan
from .conftest import make_old, write_manifest


def test_destination_missing_blocks_cleanup(config, data_root: Path) -> None:
    source = data_root / "_INGEST" / "ready" / "MissingDest"
    source.mkdir(parents=True)
    make_old(source)
    manifest = write_manifest(data_root, "_INGEST/ready/MissingDest")
    dest = data_root / "Movies" / "Library" / "2000 - Test" / "Test.mkv"
    dest.unlink()
    plan = build_plan(config)
    matches = [action for action in plan.actions if action.relative_path == "_INGEST/ready/MissingDest"]
    assert matches
    assert matches[0].category == "blocked_by_destination_missing"
