from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest

from cleaner import duplicates, trash
from cleaner.executor import CleanerExecutionError, execute_trash_plan, load_reviewed_plan, purge_trash
from cleaner.planner import build_plan
from cleaner.reports import write_plan_report
from cleaner.server import (
    build_dashboard_payload,
    run_exclusive,
    run_trash_move,
    run_trash_purge,
    run_trash_restore,
)
from cleaner.trash import TrashError, move_to_trash

from .test_origin_guard import post, running_server
from .test_pick_up_leftovers import TRACKS, _disposition, _leftover, _library_album, _quarantined, _write
from .test_rip_sidecar_leftovers import RIP_FILES, _release

DUPLICATE = "_INGEST/ready/Album - Copy"
STRAY = "_INGEST/ready/Stray"
DISCARD = "_QUARANTINE/unknown-type/Weird Folder"
RUN = "trash-20260101-000000"


@pytest.fixture(autouse=True)
def fresh_caches():
    duplicates.clear_caches()
    yield
    duplicates.clear_caches()


def _live(config, **flags):
    settings = {"mode": "production", "dry_run": False, "destructive_actions_enabled": True, "allow_trash_hold": True}
    settings.update(flags)
    return replace(config, **settings)


def _review(live) -> str:
    plan = build_plan(live)
    write_plan_report(live.cleaner_reports_dir, live.cleaner_log_path, plan)
    return plan.run_id


def _duplicate(data_root: Path) -> Path:
    _library_album(data_root, TRACKS)
    return _leftover(data_root, "Album - Copy", {"01.flac": TRACKS["01 - One.flac"], "02.flac": TRACKS["02 - Two.flac"]})


def _stray(data_root: Path) -> Path:
    return _leftover(data_root, "Stray", {"new.flac": b"new music" * 300})


def _discard(data_root: Path, decided: str = "2026-01-02T00:00:00Z", stamp: str = "20260102T000000000000Z") -> Path:
    folder = _quarantined(data_root)
    _disposition(data_root, 7, "discard_approved", folder, stamp, decided=decided)
    return folder


def _statuses(payload: dict) -> dict[str, str]:
    return {item["relative_path"]: item["status"] for item in payload["results"]}


def _manifest(live, trash_run: str) -> dict:
    return json.loads((live.trash_dir / trash_run / "trash-manifest.json").read_text(encoding="utf-8"))


def _hold(live, folder: Path, category: str = "verified_duplicate", *, days_ago: int = 0) -> str:
    """Put a folder in the hold directly (optionally aged) and return its relative path."""
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    entry = move_to_trash(live, folder, trash_run=RUN, category=category, reason="test", now=now)
    return entry["relative_path"]


# ---- the gates ---------------------------------------------------------------------------------------------

def test_nothing_is_planned_for_the_trash_hold_while_the_gates_are_closed(config, data_root: Path) -> None:
    _duplicate(data_root)
    _stray(data_root)
    _discard(data_root)

    for settings in (
        {},                                              # development / dry run
        {"allow_trash_hold": False},                     # production gates open, trash hold off
    ):
        gated = _live(config, **settings) if settings else config
        assert not [a for a in build_plan(gated).actions if a.action == "move_to_trash"]


def test_the_endpoint_refuses_when_the_trash_hold_is_off(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config, allow_trash_hold=False)
    run_id = _review(live)

    status, payload = run_trash_move(live, run_id, [])

    assert status == HTTPStatus.CONFLICT and "disabled" in payload["error"]
    assert folder.exists() and not live.trash_dir.exists()


def test_the_trash_hold_days_must_be_at_least_one(config) -> None:
    with pytest.raises(ValueError, match="TRASH_HOLD_DAYS"):
        replace(config, trash_hold_days=0).validate()


def test_the_environment_sets_the_flags(monkeypatch, tmp_path: Path) -> None:
    from cleaner.config import CleanerConfig

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ALLOW_TRASH_HOLD", "true")
    monkeypatch.setenv("ALLOW_TRASH_PURGE", "true")
    monkeypatch.setenv("ALLOW_QUARANTINE_DISCARD", "true")
    monkeypatch.setenv("TRASH_HOLD_DAYS", "30")
    loaded = CleanerConfig.from_env()
    assert loaded.allow_trash_hold and loaded.allow_trash_purge and loaded.allow_quarantine_discard
    assert loaded.trash_hold_days == 30


# ---- moving a reviewed plan into the hold ---------------------------------------------------------------

def test_a_verified_duplicate_moves_into_the_trash_hold_and_is_recorded(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    run_id = _review(live)

    status, payload = run_trash_move(live, run_id, [])

    assert status == HTTPStatus.OK and payload["moved"] == 1
    held = live.trash_dir / payload["trash_run"] / DUPLICATE
    assert not folder.exists() and (held / "01.flac").exists() and (held / "02.flac").exists()
    assert (data_root / "_INGEST" / "ready").is_dir()
    assert len(list((data_root / "Music" / "Library").rglob("*.flac"))) == 2   # the library copy is untouched

    entry = _manifest(live, payload["trash_run"])["entries"][0]
    assert entry["status"] == "in_trash" and entry["category"] == "verified_duplicate"
    assert entry["inventory"]["file_count"] == 2
    moved_at = datetime.fromisoformat(entry["moved_at"].replace("Z", "+00:00"))
    purge_after = datetime.fromisoformat(entry["purge_after"].replace("Z", "+00:00"))
    assert purge_after - moved_at == timedelta(days=14)
    report = json.loads(Path(payload["report_path"]).read_text(encoding="utf-8"))
    assert [item["relative_path"] for item in report["moved"]] == [DUPLICATE]


def test_a_stale_reviewed_plan_is_refused(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    run_id = _review(live)
    report = live.cleaner_reports_dir / f"{run_id}.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    data["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    report.write_text(json.dumps(data), encoding="utf-8")

    status, payload = run_trash_move(live, run_id, [])

    assert status == HTTPStatus.BAD_REQUEST and "24 hours" in payload["error"]
    assert folder.exists()


def test_an_item_that_arrived_after_the_review_is_not_moved(config, data_root: Path) -> None:
    _library_album(data_root, TRACKS)
    live = _live(config)
    run_id = _review(live)
    late = _leftover(data_root, "Album - Copy", {"01.flac": TRACKS["01 - One.flac"], "02.flac": TRACKS["02 - Two.flac"]})

    _status, payload = run_trash_move(live, run_id, [])

    assert payload["moved"] == 0 and late.exists()
    assert _statuses(payload) == {DUPLICATE: "skipped_not_in_reviewed_plan"}


def test_a_folder_that_changed_after_the_plan_was_built_is_skipped(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    plan = build_plan(live)
    write_plan_report(live.cleaner_reports_dir, live.cleaner_log_path, plan)
    _write(folder / "cover.jpg", b"artwork")          # artwork does not change the category, only the folder

    _run, results = execute_trash_plan(live, plan, load_reviewed_plan(live, plan.run_id), set())

    assert [r["status"] for r in results] == ["skipped_changed_since_plan"]
    assert folder.exists() and not live.trash_dir.exists()


def test_a_duplicate_whose_library_copy_vanished_is_not_moved(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    run_id = _review(live)
    for track in (data_root / "Music" / "Library").rglob("*.flac"):
        track.unlink()

    _status, payload = run_trash_move(live, run_id, [])

    # Re-verified against the library: it is now only an unrecorded stray, which was never in the plan.
    assert payload["moved"] == 0 and _statuses(payload) == {DUPLICATE: "skipped_not_in_reviewed_plan"}
    assert len(list(folder.glob("*.flac"))) == 2


def test_strays_move_only_when_ticked(config, data_root: Path) -> None:
    stray = _stray(data_root)
    live = _live(config)
    run_id = _review(live)
    action = next(a for a in build_plan(live).actions if a.relative_path == STRAY)
    assert action.action == "move_to_trash" and action.safety_status == "requires_your_tick"

    _status, untouched = run_trash_move(live, run_id, [])
    assert untouched["moved"] == 0 and stray.exists()
    assert _statuses(untouched) == {STRAY: "skipped_needs_your_tick"}

    _status, other = run_trash_move(live, run_id, ["_INGEST/ready/Something Else"])
    assert other["moved"] == 0 and stray.exists()

    _status, ticked = run_trash_move(live, run_id, [STRAY])
    assert ticked["moved"] == 1 and not stray.exists()
    assert (live.trash_dir / ticked["trash_run"] / STRAY / "new.flac").exists()


def test_a_tick_for_something_not_in_the_reviewed_plan_does_nothing(config, data_root: Path) -> None:
    live = _live(config)
    run_id = _review(live)
    late = _stray(data_root)

    _status, payload = run_trash_move(live, run_id, [STRAY])

    assert payload["moved"] == 0 and late.exists()
    assert _statuses(payload) == {STRAY: "skipped_not_in_reviewed_plan"}


def test_quarantine_discards_need_their_own_flag(config, data_root: Path) -> None:
    folder = _discard(data_root)

    off = _live(config)
    assert next(a for a in build_plan(off).actions if a.relative_path == DISCARD).action == "report_only"
    _status, refused = run_trash_move(off, _review(off), [])
    assert refused["moved"] == 0 and folder.exists()

    on = _live(config, allow_quarantine_discard=True)
    _status, moved = run_trash_move(on, _review(on), [])
    assert moved["moved"] == 1 and not folder.exists()
    assert (on.trash_dir / moved["trash_run"] / DISCARD / "a.bin").exists()
    assert (data_root / "_QUARANTINE" / "unknown-type").is_dir()      # the container is left in place


def test_a_discard_still_in_its_waiting_period_is_not_moved(config, data_root: Path) -> None:
    folder = _discard(data_root, decided="2999-01-01T00:00:00Z", stamp="29990101T000000000000Z")
    live = _live(config, allow_quarantine_discard=True)

    _status, payload = run_trash_move(live, _review(live), [])

    assert payload["moved"] == 0 and folder.exists()
    assert _statuses(payload) == {DISCARD: "skipped_not_yet_eligible"}


def test_an_undecided_quarantine_item_is_never_offered(config, data_root: Path) -> None:
    folder = _quarantined(data_root)
    live = _live(config, allow_quarantine_discard=True)

    plan = build_plan(live)

    assert not [a for a in plan.actions if a.action == "move_to_trash"]
    _status, payload = run_trash_move(live, _review(live), [])
    assert payload["moved"] == 0 and folder.exists()


def test_known_junk_needs_its_own_flag(config, data_root: Path) -> None:
    source = _release(data_root, "Random Access Memories", RIP_FILES)
    junk = "_INGEST/ready/Random Access Memories"

    off = _live(config)
    assert next(a for a in build_plan(off).actions if a.relative_path == junk).action == "blocked_no_action"
    _status, refused = run_trash_move(off, _review(off), [])
    assert refused["moved"] == 0 and source.exists()

    on = _live(config, allow_known_trash_delete=True)
    _status, moved = run_trash_move(on, _review(on), [])
    assert moved["moved"] == 1 and not source.exists()
    assert (on.trash_dir / moved["trash_run"] / junk / "CD 1" / "DR8.txt").exists()


def test_the_hold_directory_is_never_scanned(config, data_root: Path) -> None:
    _duplicate(data_root)
    live = _live(config)
    _status, moved = run_trash_move(live, _review(live), [])
    assert moved["moved"] == 1

    plan = build_plan(live)

    assert not [a for a in plan.actions if "_TRASH" in a.relative_path or "Album - Copy" in a.relative_path]


def test_only_one_cleanup_action_runs_at_a_time(config, data_root: Path) -> None:
    from cleaner import server

    server._ACTION_LOCK.acquire()
    try:
        outcome: list = []
        worker = threading.Thread(target=lambda: outcome.append(run_exclusive(lambda: (HTTPStatus.OK, {"ok": True}))))
        worker.start()
        worker.join(timeout=5)
        assert outcome[0][0] == HTTPStatus.CONFLICT
    finally:
        server._ACTION_LOCK.release()
    assert run_exclusive(lambda: (HTTPStatus.OK, {"ok": True}))[0] == HTTPStatus.OK


# ---- the safety checks in the trash module ---------------------------------------------------------------

@pytest.mark.parametrize(
    "relative, category, fragment",
    [
        ("_INGEST/ready", "verified_duplicate", "lane root"),
        ("_INGEST/incoming/Fresh Download", "verified_duplicate", "Not inside a lane"),
        ("Music/Library/FLAC/Artist/2020 - Album", "verified_duplicate", "Not inside a lane"),
        ("_QUARANTINE/unknown-type/Weird Folder", "verified_duplicate", "Not inside a lane"),
        ("_INGEST/ready/Album - Copy", "quarantine_discard_approved", "Not inside a lane"),
        ("_QUARANTINE/unknown-type", "quarantine_discard_approved", "container"),
        ("_QUARANTINE", "quarantine_discard_approved", "lane root"),
    ],
)
def test_paths_outside_the_lanes_are_refused(config, data_root: Path, relative: str, category: str, fragment: str) -> None:
    target = data_root / relative
    target.mkdir(parents=True, exist_ok=True)
    _write(target / "keep.bin", b"keep")
    live = _live(config)

    with pytest.raises(TrashError, match=fragment):
        move_to_trash(live, target, trash_run=RUN, category=category, reason="test")

    assert (target / "keep.bin").exists()


def test_a_missing_path_is_refused(config, data_root: Path) -> None:
    with pytest.raises(TrashError, match="Not found"):
        move_to_trash(_live(config), data_root / "_INGEST" / "ready" / "Nope", trash_run=RUN, category="verified_duplicate", reason="t")


def test_links_are_never_followed(config, data_root: Path, monkeypatch) -> None:
    folder = _duplicate(data_root)
    inner = folder / "02.flac"
    monkeypatch.setattr(trash, "is_link", lambda path: Path(path) == inner)

    with pytest.raises(TrashError, match="link"):
        move_to_trash(_live(config), folder, trash_run=RUN, category="verified_duplicate", reason="test")

    assert folder.exists()


def test_a_different_disk_is_refused_rather_than_copied(config, data_root: Path, monkeypatch) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    real_stat = os.stat

    def other_disk(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if Path(path) == live.trash_dir:
            fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
            return SimpleNamespace(**{**fields, "st_dev": result.st_dev + 1})
        return result

    class OsProxy:
        stat = staticmethod(other_disk)

        def __getattr__(self, name):
            return getattr(os, name)

    monkeypatch.setattr(trash, "os", OsProxy())

    with pytest.raises(TrashError, match="different disk"):
        move_to_trash(live, folder, trash_run=RUN, category="verified_duplicate", reason="test")

    assert folder.exists()


def test_a_failed_rename_leaves_the_source_and_says_so(config, data_root: Path, monkeypatch) -> None:
    folder = _duplicate(data_root)
    live = _live(config)

    class OsProxy:
        @staticmethod
        def rename(source, destination):
            raise OSError("in use")

        def __getattr__(self, name):
            return getattr(os, name)

    monkeypatch.setattr(trash, "os", OsProxy())

    with pytest.raises(TrashError, match="in use"):
        move_to_trash(live, folder, trash_run=RUN, category="verified_duplicate", reason="test")

    assert (folder / "01.flac").exists()
    assert _manifest(live, RUN)["entries"][0]["status"] == "failed"


def test_nothing_is_ever_overwritten_in_the_hold(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    _hold(live, folder)
    _leftover(data_root, "Album - Copy", {"01.flac": b"another file"})

    with pytest.raises(TrashError, match="Already in the trash hold"):
        move_to_trash(live, data_root / "_INGEST" / "ready" / "Album - Copy", trash_run=RUN, category="verified_duplicate", reason="t")


# ---- restore --------------------------------------------------------------------------------------------------

def test_restore_puts_the_item_back_and_needs_no_gates(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    relative = _hold(live, folder)
    assert not folder.exists()

    # The default, report-only config can still restore: restoring deletes nothing.
    status, payload = run_trash_restore(config, RUN, relative)

    assert status == HTTPStatus.OK and payload["restored"] == DUPLICATE
    assert len(list(folder.glob("*.flac"))) == 2
    assert _manifest(live, RUN)["entries"][0]["status"] == "restored"

    status, again = run_trash_restore(config, RUN, relative)
    assert status == HTTPStatus.BAD_REQUEST and "Not in the trash hold" in again["error"]


def test_restore_never_overwrites(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    relative = _hold(live, folder)
    folder.mkdir()
    (folder / "new.txt").write_text("someone put this here", encoding="utf-8")

    status, payload = run_trash_restore(live, RUN, relative)

    assert status == HTTPStatus.BAD_REQUEST and "already exists" in payload["error"]
    assert (folder / "new.txt").exists() and (live.trash_dir / RUN / relative / "01.flac").exists()
    assert _manifest(live, RUN)["entries"][0]["status"] == "in_trash"


@pytest.mark.parametrize("trash_run, relative", [("not-a-run", DUPLICATE), (RUN, "_INGEST/ready/Unknown"), (RUN, "../outside")])
def test_restore_rejects_unknown_entries(config, data_root: Path, trash_run: str, relative: str) -> None:
    live = _live(config)
    _hold(live, _duplicate(data_root))

    status, payload = run_trash_restore(live, trash_run, relative)

    assert status == HTTPStatus.BAD_REQUEST and payload["ok"] is False


# ---- purge ----------------------------------------------------------------------------------------------------

def _purge_request(relative: str = DUPLICATE) -> list[dict]:
    return [{"trash_run": RUN, "relative_path": relative}]


def test_purge_deletes_an_expired_item_and_records_it(config, data_root: Path) -> None:
    live = _live(config, allow_trash_purge=True)
    relative = _hold(live, _duplicate(data_root), days_ago=20)

    status, payload = run_trash_purge(live, _purge_request(relative))

    assert status == HTTPStatus.OK and payload["purged"] == 1
    assert not (live.trash_dir / RUN / relative).exists()
    entry = _manifest(live, RUN)["entries"][0]
    assert entry["status"] == "purged" and entry["purged_file_count"] == 2
    assert (live.cleaner_reports_dir / f"{payload['purge_id']}.json").is_file()
    assert len(list((data_root / "Music" / "Library").rglob("*.flac"))) == 2


def test_purge_refuses_an_item_whose_hold_has_not_expired(config, data_root: Path) -> None:
    live = _live(config, allow_trash_purge=True)
    relative = _hold(live, _duplicate(data_root), days_ago=3)

    _status, payload = run_trash_purge(live, _purge_request(relative))

    assert payload["purged"] == 0 and "has not expired" in payload["results"][0]["error"]
    assert (live.trash_dir / RUN / relative / "01.flac").exists()


def test_purge_needs_its_own_flag(config, data_root: Path) -> None:
    live = _live(config)
    relative = _hold(live, _duplicate(data_root), days_ago=20)

    status, payload = run_trash_purge(live, _purge_request(relative))

    assert status == HTTPStatus.CONFLICT and "disabled" in payload["error"]
    with pytest.raises(CleanerExecutionError):
        purge_trash(live, _purge_request(relative))
    assert (live.trash_dir / RUN / relative / "01.flac").exists()


def test_purge_leaves_an_item_that_no_longer_matches_what_was_taken(config, data_root: Path) -> None:
    live = _live(config, allow_trash_purge=True)
    relative = _hold(live, _duplicate(data_root), days_ago=20)
    _write(live.trash_dir / RUN / relative / "surprise.bin", b"added while on hold")

    _status, payload = run_trash_purge(live, _purge_request(relative))

    assert payload["purged"] == 0 and "no longer matches" in payload["results"][0]["error"]
    assert (live.trash_dir / RUN / relative / "surprise.bin").exists()


def test_purge_refuses_restored_and_unknown_entries(config, data_root: Path) -> None:
    live = _live(config, allow_trash_purge=True)
    relative = _hold(live, _duplicate(data_root), days_ago=20)
    run_trash_restore(live, RUN, relative)
    outside = data_root / "Music" / "Library" / "FLAC" / "Artist" / "2020 - Album"

    _status, payload = run_trash_purge(
        live,
        [*_purge_request(relative), *_purge_request("../../Music"), {"trash_run": "..", "relative_path": "Music"}],
    )

    assert payload["purged"] == 0
    assert [item["status"] for item in payload["results"]] == ["refused"] * 3
    assert len(list(outside.glob("*.flac"))) == 2 and (data_root / DUPLICATE).exists()


# ---- the dashboard and the HTTP surface ------------------------------------------------------------------------

def test_the_dashboard_shows_what_is_held_and_which_gates_are_open(config, data_root: Path) -> None:
    _duplicate(data_root)
    live = _live(config)
    run_id = _review(live)
    plan_view = build_dashboard_payload(live)["reviewed_plan"]
    assert [c["relative_path"] for c in plan_view["trash_candidates"]] == [DUPLICATE]
    assert plan_view["trash_candidates"][0]["needs_tick"] is False

    run_trash_move(live, run_id, [])
    payload = build_dashboard_payload(live)

    assert payload["config"]["trash_enabled"] is True and payload["config"]["purge_enabled"] is False
    assert payload["config"]["trash_hold_days"] == 14
    assert payload["trash"]["items_held"] == 1 and payload["trash"]["expired_items"] == 0
    assert payload["trash"]["bytes_held"] == sum(len(TRACKS[name]) for name in TRACKS)
    assert not payload["lanes"]["duplicates"]


def test_strays_are_marked_as_needing_a_tick_in_the_dashboard(config, data_root: Path) -> None:
    _stray(data_root)
    live = _live(config)
    _review(live)

    candidates = build_dashboard_payload(live)["reviewed_plan"]["trash_candidates"]

    assert [(c["relative_path"], c["needs_tick"]) for c in candidates] == [(STRAY, True)]


def test_the_dashboard_with_the_hold_off_offers_nothing(config, data_root: Path) -> None:
    _duplicate(data_root)

    payload = build_dashboard_payload(config)

    assert payload["config"]["trash_enabled"] is False
    assert payload["trash"] == {"holds": [], "items_held": 0, "bytes_held": 0, "expired_items": 0}


def test_expired_holds_are_flagged_and_listed_over_http(config, data_root: Path) -> None:
    live = _live(config)
    _hold(live, _duplicate(data_root), days_ago=20)

    import http.client

    with running_server(live) as port:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("GET", "/api/trash")
        data = json.loads(connection.getresponse().read())
        connection.close()

    assert data["ok"] is True and data["items_held"] == 1 and data["expired_items"] == 1
    assert data["holds"][0]["entries"][0]["expired"] is True


@pytest.mark.parametrize("path", ["/api/trash/move", "/api/trash/restore", "/api/trash/purge"])
def test_a_foreign_page_cannot_use_the_trash_endpoints(config, data_root: Path, path: str) -> None:
    folder = _duplicate(data_root)
    live = _live(config, allow_trash_purge=True)
    relative = _hold(live, folder, days_ago=20)
    body = json.dumps({"run_id": "cleaner-20260101-000000", "trash_run": RUN, "relative_path": relative, "entries": _purge_request(relative)}).encode()

    with running_server(live) as port:
        status, payload = post(port, path, {"Origin": "https://evil.example", "Content-Type": "application/json"}, body)
        assert status == 403 and payload["ok"] is False

    assert (live.trash_dir / RUN / relative / "01.flac").exists()
    assert _manifest(live, RUN)["entries"][0]["status"] == "in_trash"


def test_the_trash_endpoints_work_from_the_dashboard_origin(config, data_root: Path) -> None:
    folder = _duplicate(data_root)
    live = _live(config)
    run_id = _review(live)

    with running_server(live) as port:
        headers = {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"}
        status, moved = post(port, "/api/trash/move", headers, json.dumps({"run_id": run_id, "include_paths": []}).encode())
        assert status == 200 and moved["moved"] == 1 and not folder.exists()
        status, restored = post(
            port, "/api/trash/restore", headers, json.dumps({"trash_run": moved["trash_run"], "relative_path": DUPLICATE}).encode()
        )
        assert status == 200 and restored["restored"] == DUPLICATE and folder.exists()
        status, refused = post(port, "/api/trash/purge", headers, json.dumps({"entries": []}).encode())
        assert status == 409
