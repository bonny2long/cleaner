from __future__ import annotations

from pathlib import Path

from cleaner.planner import build_plan
from cleaner.reports import write_plan_report


def test_report_written(config, data_root: Path) -> None:
    plan = build_plan(config)
    paths = write_plan_report(config.cleaner_reports_dir, config.cleaner_log_path, plan)
    assert Path(paths["json_path"]).exists()
    assert Path(paths["markdown_path"]).exists()
    assert (data_root / "_REPORTS" / "cleaner" / "latest-plan.json").exists()
