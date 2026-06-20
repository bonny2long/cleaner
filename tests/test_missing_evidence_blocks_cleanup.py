from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan
from .conftest import make_old


def test_missing_evidence_blocks_cleanup(config, data_root: Path) -> None:
    source = data_root / "_INGEST" / "ready" / "NoEvidence"
    source.mkdir(parents=True)
    make_old(source)
    plan = build_plan(config)
    matches = [action for action in plan.actions if action.relative_path == "_INGEST/ready/NoEvidence"]
    assert matches
    assert matches[0].category == "blocked_by_missing_evidence"
