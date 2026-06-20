from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan
from .conftest import make_old, write_manifest


def test_empty_folder_with_verified_evidence_is_safe_empty_folder(config, data_root: Path) -> None:
    source = data_root / "_INGEST" / "ready" / "EmptyMoved"
    source.mkdir(parents=True)
    make_old(source)
    write_manifest(data_root, "_INGEST/ready/EmptyMoved")
    plan = build_plan(config)
    matches = [action for action in plan.actions if action.relative_path == "_INGEST/ready/EmptyMoved"]
    assert matches
    assert matches[0].category == "safe_empty_folder"
    assert matches[0].action == "remove_empty_folder_dry_run"
