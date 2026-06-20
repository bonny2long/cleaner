from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan
from .conftest import make_old, write_manifest


def test_non_empty_leftover_is_uncertain_not_deleted(config, data_root: Path) -> None:
    source = data_root / "_INGEST" / "ready" / "MovieWithNfo"
    source.mkdir(parents=True)
    (source / "sample.nfo").write_text("notes", encoding="utf-8")
    make_old(source / "sample.nfo")
    make_old(source)
    write_manifest(data_root, "_INGEST/ready/MovieWithNfo")
    plan = build_plan(config)
    matches = [action for action in plan.actions if action.relative_path == "_INGEST/ready/MovieWithNfo"]
    assert matches
    assert matches[0].category == "uncertain_leftover"
    assert matches[0].action == "report_only"
