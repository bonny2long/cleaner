from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan
from .conftest import make_old


def test_quarantine_is_never_deleted(config, data_root: Path) -> None:
    q = data_root / "_QUARANTINE" / "suspicious.xyz"
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text("unknown", encoding="utf-8")
    make_old(q)
    plan = build_plan(config)
    matches = [action for action in plan.actions if action.relative_path == "_QUARANTINE/suspicious.xyz"]
    assert matches
    assert matches[0].category == "quarantine_hold"
    assert matches[0].action == "report_only"
