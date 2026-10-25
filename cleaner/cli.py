from __future__ import annotations

import argparse
import json
from typing import Any

from .config import CleanerConfig
from .planner import build_plan
from .reports import write_plan_report
from .scanner import scan_cleanup_candidates


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_ensure_folders(config: CleanerConfig, _args: argparse.Namespace) -> int:
    config.ensure_shared_directories()
    _print_json({"ok": True, "data_root": str(config.data_root), "message": "shared NAS folder skeleton exists"})
    return 0


def cmd_inspect(config: CleanerConfig, _args: argparse.Namespace) -> int:
    config.ensure_shared_directories()
    items = scan_cleanup_candidates(config)
    _print_json({"data_root": str(config.data_root), "items": [item.to_dict() for item in items]})
    return 0


def cmd_plan(config: CleanerConfig, args: argparse.Namespace) -> int:
    plan = build_plan(config)
    if args.write_report:
        paths = write_plan_report(config.cleaner_reports_dir, config.cleaner_log_path, plan)
        data = plan.to_dict()
        data["report_paths"] = paths
        _print_json(data)
    else:
        _print_json(plan.to_dict())
    return 0


def cmd_dry_run(config: CleanerConfig, _args: argparse.Namespace) -> int:
    plan = build_plan(config)
    paths = write_plan_report(config.cleaner_reports_dir, config.cleaner_log_path, plan)
    _print_json({"ok": True, "plan": plan.to_dict(), "report_paths": paths})
    return 0


def cmd_status(config: CleanerConfig, _args: argparse.Namespace) -> int:
    plan = build_plan(config)
    _print_json({
        "service": "nas-cleaner",
        "data_root": str(config.data_root),
        "mode": config.mode,
        "dry_run": config.dry_run,
        "destructive_actions_enabled": config.destructive_actions_enabled,
        "min_age_days": config.min_age_days,
        "check_interval_seconds": config.check_interval_seconds,
        "items_scanned": plan.items_scanned,
        "counts": plan.counts,
    })
    return 0


def cmd_execute(config: CleanerConfig, args: argparse.Namespace) -> int:
    from .server import run_execution

    _status, payload = run_execution(config, args.run_id)
    _print_json(payload)
    return 0 if payload.get("ok") else 1


def cmd_trash_move(config: CleanerConfig, args: argparse.Namespace) -> int:
    from .server import run_trash_move

    _status, payload = run_trash_move(config, args.run_id, list(args.tick or []))
    _print_json(payload)
    return 0 if payload.get("ok") else 1


def cmd_trash_list(config: CleanerConfig, _args: argparse.Namespace) -> int:
    from .trash import list_holds

    _print_json({"trash_dir": str(config.trash_dir), "hold_days": config.trash_hold_days, "holds": list_holds(config)})
    return 0


def cmd_restore(config: CleanerConfig, args: argparse.Namespace) -> int:
    from .server import run_trash_restore

    _status, payload = run_trash_restore(config, args.trash_run, args.relative_path)
    _print_json(payload)
    return 0 if payload.get("ok") else 1


def cmd_purge(config: CleanerConfig, args: argparse.Namespace) -> int:
    from .server import run_trash_purge

    _status, payload = run_trash_purge(config, [{"trash_run": args.trash_run, "relative_path": path} for path in args.relative_path])
    _print_json(payload)
    return 0 if payload.get("ok") and not any(item.get("status") == "refused" for item in payload.get("results", [])) else 1


def cmd_serve(config: CleanerConfig, args: argparse.Namespace) -> int:
    from .server import serve

    host = args.host or config.dashboard_host
    port = args.port or config.dashboard_port
    serve(config, host, port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NAS Cleaner conservative cleanup planner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ensure-folders")
    sub.add_parser("inspect")
    plan = sub.add_parser("plan")
    plan.add_argument("--write-report", action="store_true")
    sub.add_parser("dry-run")
    sub.add_parser("status")
    execute_parser = sub.add_parser("execute", help="Run allowed actions from a reviewed plan report")
    execute_parser.add_argument("--run-id", required=True, help="run_id of the written plan you reviewed")
    move_parser = sub.add_parser("trash-move", help="Move items of a reviewed plan into the recoverable trash hold")
    move_parser.add_argument("--run-id", required=True, help="run_id of the written plan you reviewed")
    move_parser.add_argument("--tick", action="append", help="relative path of an unrecorded leftover you approve (repeatable)")
    sub.add_parser("trash-list", help="Show what is in the trash hold and when each item expires")
    restore_parser = sub.add_parser("restore", help="Put a held item back where it came from")
    restore_parser.add_argument("trash_run")
    restore_parser.add_argument("relative_path")
    purge_parser = sub.add_parser("purge", help="Permanently delete expired held items (needs ALLOW_TRASH_PURGE)")
    purge_parser.add_argument("trash_run")
    purge_parser.add_argument("relative_path", nargs="+")
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = CleanerConfig.from_env()
    handlers = {
        "ensure-folders": cmd_ensure_folders,
        "inspect": cmd_inspect,
        "plan": cmd_plan,
        "dry-run": cmd_dry_run,
        "status": cmd_status,
        "execute": cmd_execute,
        "trash-move": cmd_trash_move,
        "trash-list": cmd_trash_list,
        "restore": cmd_restore,
        "purge": cmd_purge,
        "serve": cmd_serve,
    }
    return handlers[args.command](config, args)


if __name__ == "__main__":
    raise SystemExit(main())
