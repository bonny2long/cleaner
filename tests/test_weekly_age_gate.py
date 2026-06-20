from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan
from .conftest import write_manifest


def test_items_younger_than_min_age_are_blocked(config, data_root: Path) -> None:
    source = data_root / "_INGEST" / "ready" / "Fresh"
    source.mkdir(parents=True)
    write_manifest(data_root, "_INGEST/ready/Fresh")
    plan = build_plan(config)
    assert any(action.category == "blocked_too_new" for action in plan.actions)
