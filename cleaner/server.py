from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import CleanerConfig
from .planner import build_plan
from .reports import read_recent_jsonl, write_plan_report

WEB_DIR = Path(__file__).parent / "web"


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def build_dashboard_payload(config: CleanerConfig) -> dict[str, Any]:
    plan = build_plan(config)
    events = read_recent_jsonl(config.cleaner_log_path, 80)
    lanes: dict[str, list[dict[str, Any]]] = {
        "ready_to_clean_later": [],
        "too_new": [],
        "leftovers_need_review": [],
        "quarantine_hold": [],
        "blocked_by_safety": [],
        "protected": [],
    }
    for action in plan.actions:
        data = action.to_dict()
        if action.category == "safe_empty_folder":
            lanes["ready_to_clean_later"].append(data)
        elif action.category == "blocked_too_new":
            lanes["too_new"].append(data)
        elif action.category in {"uncertain_leftover", "known_harmless_trash"}:
            lanes["leftovers_need_review"].append(data)
        elif action.category == "quarantine_hold":
            lanes["quarantine_hold"].append(data)
        elif action.category == "do_not_touch":
            lanes["protected"].append(data)
        else:
            lanes["blocked_by_safety"].append(data)

    return {
        "service": "nas-cleaner",
        "status": "ok",
        "config": {
            "data_root": str(config.data_root),
            "ready_dir": str(config.ready_dir),
            "leftover_review_dir": str(config.leftover_review_dir),
            "quarantine_dir": str(config.quarantine_dir),
            "reports_dir": str(config.cleaner_reports_dir),
            "mode": config.mode,
            "dry_run": config.dry_run,
            "destructive_actions_enabled": config.destructive_actions_enabled,
            "min_age_days": config.min_age_days,
            "check_interval_seconds": config.check_interval_seconds,
            "allow_empty_folder_removal": config.allow_empty_folder_removal,
            "allow_leftover_review_moves": config.allow_leftover_review_moves,
        },
        "counts": plan.counts,
        "items_scanned": plan.items_scanned,
        "evidence_records": plan.evidence_records,
        "lanes": lanes,
        "events": events,
    }


def run_dry_plan(config: CleanerConfig) -> dict[str, Any]:
    plan = build_plan(config)
    paths = write_plan_report(config.cleaner_reports_dir, config.cleaner_log_path, plan)
    return {"ok": True, "plan": plan.to_dict(), "report_paths": paths}


class CleanerHandler(BaseHTTPRequestHandler):
    config: CleanerConfig

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_web_asset(self, request_path: str) -> bool:
        static = request_path.lstrip("/")
        if not static.startswith("assets/"):
            return False

        assets_root = (WEB_DIR / "assets").resolve()
        asset_path = (WEB_DIR / static).resolve()
        if assets_root not in asset_path.parents or not asset_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Asset not found")
            return True

        self._send_file(asset_path)
        return True
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if self._send_web_asset(path):
            return
        if path == "/api/health":
            self._send_json({"ok": True, "service": "nas-cleaner"})
            return
        if path == "/api/dashboard":
            self._send_json(build_dashboard_payload(self.config))
            return
        if path == "/api/plan":
            self._send_json(build_plan(self.config).to_dict())
            return
        if path == "/":
            self._send_file(WEB_DIR / "index.html")
            return
        static = path.lstrip("/")
        if static in {"app.js", "styles.css"}:
            self._send_file(WEB_DIR / static)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/run-dry-plan":
            self._send_json(run_dry_plan(self.config))
            return
        if parsed.path == "/api/ensure-folders":
            self.config.ensure_shared_directories()
            self._send_json({"ok": True, "message": "shared NAS folder skeleton exists"})
            return
        self.send_error(HTTPStatus.NOT_FOUND)


def serve(config: CleanerConfig, host: str, port: int) -> None:
    config.validate()
    config.ensure_shared_directories()
    handler_cls = type("ConfiguredCleanerHandler", (CleanerHandler,), {"config": config})
    server = ThreadingHTTPServer((host, port), handler_cls)
    print(f"NAS Cleaner dashboard: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _auto_loop(config: CleanerConfig) -> None:
    while True:
        run_dry_plan(config)
        time.sleep(config.check_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NAS Cleaner dashboard")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    config = CleanerConfig.from_env()
    if config.auto_run:
        thread = threading.Thread(target=_auto_loop, args=(config,), daemon=True)
        thread.start()
    serve(config, args.host or config.dashboard_host, args.port or config.dashboard_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
