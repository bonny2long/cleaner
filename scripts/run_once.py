from __future__ import annotations

from cleaner.config import CleanerConfig
from cleaner.planner import build_plan
from cleaner.reports import write_plan_report


def main() -> int:
    config = CleanerConfig.from_env()
    plan = build_plan(config)
    paths = write_plan_report(config.cleaner_reports_dir, config.cleaner_log_path, plan)
    print(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
