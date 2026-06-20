from __future__ import annotations

from pathlib import Path

from cleaner.executor import CleanerExecutionError, execute_plan
from cleaner.planner import build_plan
from .conftest import make_old, write_manifest


def test_no_delete_by_default(config, data_root: Path) -> None:
    source = data_root / "_INGEST" / "ready" / "Example"
    source.mkdir(parents=True)
    make_old(source)
    write_manifest(data_root, "_INGEST/ready/Example")
    plan = build_plan(config)
    assert any(action.category == "safe_empty_folder" for action in plan.actions)
    try:
        execute_plan(config, plan)
    except CleanerExecutionError:
        pass
    assert source.exists()
