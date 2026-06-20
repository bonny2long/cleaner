from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan


def test_incoming_ignored_by_default(config, data_root: Path) -> None:
    incoming = data_root / "_INGEST" / "incoming" / "ActiveUpload"
    incoming.mkdir(parents=True)
    plan = build_plan(config)
    assert all(not action.relative_path.startswith("_INGEST/incoming") for action in plan.actions)
