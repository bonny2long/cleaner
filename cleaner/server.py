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
from .executor import (
    CleanerExecutionError,
    execute_plan,
    execute_trash_plan,
    execution_enabled,
    load_reviewed_plan,
    purge_trash,
    restore_from_trash,
    write_execution_report,
    write_trash_report,
)
from .origin_guard import request_allowed
from .planner import build_plan
from .reports import read_json, read_recent_jsonl, write_plan_report
from .trash import TrashError, list_holds, purge_enabled, trash_enabled

WEB_DIR = Path(__file__).parent / "web"
# Cleanup actions change the disk, so only one runs at a time. A second request is refused,
# not queued: it would otherwise act on a plan the first one is still changing.
_ACTION_LOCK = threading.Lock()
# A refused request's body is read and dropped up to this size; larger ones close the connection.
MAX_DISCARDED_BODY_BYTES = 8 * 1024 * 1024


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


# The dashboard refreshes every 30 seconds. Showing evidence up to a minute old keeps it
# from rescanning every library on each refresh. Plans that are written or executed
# always read fresh evidence (see run_dry_plan and run_execution).
DASHBOARD_EVIDENCE_CACHE_SECONDS = 60
# Checking an unrecorded folder against the libraries means hashing files. The dashboard
# spends at most this long per refresh and shows the rest as "not yet checked"; hashes are
# remembered, so folders finish over a few refreshes. Written plans have no limit.
DASHBOARD_HASH_BUDGET_SECONDS = 5

LANE_FOR_CATEGORY = {
    "safe_empty_folder": "ready_to_clean_later",
    "blocked_too_new": "too_new",
    "uncertain_leftover": "leftovers_need_review",
    "known_harmless_trash": "leftovers_need_review",
    "verified_duplicate": "duplicates",
    "unrecorded_leftover": "unrecorded",
    "quarantine_discard_approved": "quarantine_discards",
    "quarantine_hold": "quarantine_hold",
    "do_not_touch": "protected",
}


def build_dashboard_payload(config: CleanerConfig) -> dict[str, Any]:
    plan = build_plan(
        config,
        evidence_max_age_seconds=DASHBOARD_EVIDENCE_CACHE_SECONDS,
        hash_budget_seconds=DASHBOARD_HASH_BUDGET_SECONDS,
    )
    events = read_recent_jsonl(config.cleaner_log_path, 80)
    lanes: dict[str, list[dict[str, Any]]] = {
        "ready_to_clean_later": [],
        "too_new": [],
        "leftovers_need_review": [],
        "duplicates": [],
        "unrecorded": [],
        "quarantine_discards": [],
        "quarantine_hold": [],
        "blocked_by_safety": [],
        "protected": [],
    }
    for action in plan.actions:
        lanes[LANE_FOR_CATEGORY.get(action.category, "blocked_by_safety")].append(action.to_dict())

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
            "execution_enabled": execution_enabled(config),
            "trash_enabled": trash_enabled(config),
            "purge_enabled": purge_enabled(config),
            "trash_hold_days": config.trash_hold_days,
        },
        "trash": _trash_summary(config),
        "reviewed_plan": _reviewed_plan_summary(config),
        "counts": plan.counts,
        "items_scanned": plan.items_scanned,
        "evidence_records": plan.evidence_records,
        "lanes": lanes,
        "events": events,
    }


def _reviewed_plan_summary(config: CleanerConfig) -> dict[str, Any] | None:
    latest = read_json(config.cleaner_reports_dir / "latest-plan.json")
    if not isinstance(latest, dict) or not latest.get("run_id"):
        return None
    removable = [
        item.get("relative_path")
        for item in latest.get("actions", [])
        if isinstance(item, dict) and item.get("action") == "remove_empty_folder"
    ]
    trash_candidates = [
        {
            "relative_path": item.get("relative_path"),
            "category": item.get("category"),
            "needs_tick": item.get("category") == "unrecorded_leftover",
            "total_bytes": (item.get("signature") or {}).get("total_size_bytes"),
            "file_count": (item.get("signature") or {}).get("file_count"),
        }
        for item in latest.get("actions", [])
        if isinstance(item, dict) and item.get("action") == "move_to_trash"
    ]
    return {
        "run_id": latest.get("run_id"),
        "created_at": latest.get("created_at"),
        "remove_empty_folder_count": len(removable),
        "remove_empty_folder_paths": removable,
        "trash_candidates": trash_candidates,
    }


def _trash_summary(config: CleanerConfig) -> dict[str, Any]:
    holds = list_holds(config)
    entries = [entry for hold in holds for entry in hold.get("entries", []) if entry.get("status") == "in_trash"]
    return {
        "holds": holds,
        "items_held": len(entries),
        "bytes_held": sum(int(entry.get("total_bytes") or 0) for entry in entries),
        "expired_items": sum(1 for entry in entries if entry.get("expired")),
    }


def _busy() -> tuple[HTTPStatus, dict[str, Any]]:
    return HTTPStatus.CONFLICT, {"ok": False, "error": "Another cleanup action is already running. Wait for it to finish."}


def run_exclusive(action, *args: Any) -> tuple[HTTPStatus, dict[str, Any]]:
    if not _ACTION_LOCK.acquire(blocking=False):
        return _busy()
    try:
        return action(*args)
    finally:
        _ACTION_LOCK.release()


def run_trash_move(config: CleanerConfig, run_id: str, include_paths: list[str]) -> tuple[HTTPStatus, dict[str, Any]]:
    """Move the items of a reviewed plan into the trash hold. Nothing is deleted."""
    if not trash_enabled(config):
        return HTTPStatus.CONFLICT, {"ok": False, "error": "The trash hold is disabled by configuration; Cleaner is report-only."}
    try:
        reviewed = load_reviewed_plan(config, run_id)
        plan = build_plan(config)  # fresh evidence, and every duplicate re-verified by content
        trash_run, results = execute_trash_plan(config, plan, reviewed, set(include_paths))
    except (CleanerExecutionError, TrashError) as exc:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}
    report_path = write_trash_report(config, trash_run, run_id, results)
    moved = [item for item in results if item.get("status") == "moved_to_trash"]
    return HTTPStatus.OK, {
        "ok": True,
        "moved": len(moved),
        "trash_run": trash_run if moved else None,
        "results": results,
        "report_path": report_path,
    }


def run_trash_restore(config: CleanerConfig, trash_run: str, relative_path: str) -> tuple[HTTPStatus, dict[str, Any]]:
    try:
        entry = restore_from_trash(config, trash_run, relative_path)
    except (CleanerExecutionError, TrashError, OSError) as exc:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}
    return HTTPStatus.OK, {"ok": True, "restored": entry.get("relative_path")}


def run_trash_purge(config: CleanerConfig, entries: list[dict[str, Any]]) -> tuple[HTTPStatus, dict[str, Any]]:
    if not purge_enabled(config):
        return HTTPStatus.CONFLICT, {"ok": False, "error": "Purging is disabled by configuration; held items are kept."}
    try:
        purge_id, results = purge_trash(config, entries)
    except (CleanerExecutionError, TrashError) as exc:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}
    purged = [item for item in results if item.get("status") == "purged"]
    return HTTPStatus.OK, {"ok": True, "purged": len(purged), "purge_id": purge_id, "results": results}


def run_execution(config: CleanerConfig, run_id: str) -> tuple[HTTPStatus, dict[str, Any]]:
    if not execution_enabled(config):
        return HTTPStatus.CONFLICT, {"ok": False, "error": "Execution is disabled by configuration; Cleaner is report-only."}
    try:
        reviewed = load_reviewed_plan(config, run_id)
        plan = build_plan(config)
        results = execute_plan(config, plan, reviewed)
    except CleanerExecutionError as exc:
        return HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}
    report_path = write_execution_report(config, plan, run_id, results)
    removed = [item for item in results if item.get("status") == "removed_empty_folder"]
    return HTTPStatus.OK, {"ok": True, "removed": len(removed), "results": results, "report_path": report_path}


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
        if path == "/api/trash":
            self._send_json({
                "ok": True,
                "trash_enabled": trash_enabled(self.config),
                "purge_enabled": purge_enabled(self.config),
                "hold_days": self.config.trash_hold_days,
                **_trash_summary(self.config),
            })
            return
        if path == "/api/plan":
            self._send_json(build_plan(
                self.config,
                evidence_max_age_seconds=DASHBOARD_EVIDENCE_CACHE_SECONDS,
                hash_budget_seconds=DASHBOARD_HASH_BUDGET_SECONDS,
            ).to_dict())
            return
        if path == "/":
            self._send_file(WEB_DIR / "index.html")
            return
        static = path.lstrip("/")
        if static in {"app.js", "styles.css"}:
            self._send_file(WEB_DIR / static)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _discard_request_body(self) -> None:
        """Read and drop the body of a request we refuse.

        Closing the socket with unread request data can reset the connection, so the
        caller would see a network error instead of the 403.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        remaining = min(max(length, 0), MAX_DISCARDED_BODY_BYTES)
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        if length > MAX_DISCARDED_BODY_BYTES:
            self.close_connection = True

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > MAX_DISCARDED_BODY_BYTES:
            return {}
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_POST(self) -> None:  # noqa: N802
        allowed, reason = request_allowed(
            "POST",
            self.headers.get("Origin"),
            self.headers.get("Sec-Fetch-Site"),
            self.config.allowed_origins,
        )
        if not allowed:
            self._discard_request_body()
            self._send_json({"ok": False, "error": reason}, HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/run-dry-plan":
            self._send_json(run_dry_plan(self.config))
            return
        if parsed.path == "/api/execute":
            body = self._read_json_body()
            status, payload = run_exclusive(run_execution, self.config, str(body.get("run_id") or ""))
            self._send_json(payload, status)
            return
        if parsed.path == "/api/trash/move":
            body = self._read_json_body()
            include = [str(value) for value in body.get("include_paths") or [] if isinstance(value, str)]
            status, payload = run_exclusive(run_trash_move, self.config, str(body.get("run_id") or ""), include)
            self._send_json(payload, status)
            return
        if parsed.path == "/api/trash/restore":
            body = self._read_json_body()
            status, payload = run_exclusive(
                run_trash_restore, self.config, str(body.get("trash_run") or ""), str(body.get("relative_path") or "")
            )
            self._send_json(payload, status)
            return
        if parsed.path == "/api/trash/purge":
            body = self._read_json_body()
            entries = [item for item in body.get("entries") or [] if isinstance(item, dict)]
            status, payload = run_exclusive(run_trash_purge, self.config, entries)
            self._send_json(payload, status)
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
