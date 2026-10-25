from __future__ import annotations

import json
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

import pytest

from cleaner import duplicates
from cleaner.planner import build_plan
from cleaner.reports import write_plan_report
from cleaner.server import build_dashboard_payload, run_execution
from .conftest import make_old


@pytest.fixture(autouse=True)
def fresh_caches():
    duplicates.clear_caches()
    yield
    duplicates.clear_caches()


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _library_album(data_root: Path, tracks: dict[str, bytes]) -> None:
    for name, content in tracks.items():
        _write(data_root / "Music" / "Library" / "FLAC" / "Artist" / "2020 - Album" / name, content)


def _leftover(data_root: Path, name: str, files: dict[str, bytes], area: str = "_INGEST/ready") -> Path:
    folder = data_root / area / name
    for relative, content in files.items():
        _write(folder / relative, content)
    for path in (*folder.rglob("*"), folder):
        make_old(path)
    return folder


def _action(config, relative_path: str):
    matches = [action for action in build_plan(config).actions if action.relative_path == relative_path]
    assert matches, relative_path
    return matches[0]


TRACKS = {"01 - One.flac": b"track-one-bytes" * 400, "02 - Two.flac": b"track-two-bytes" * 500}


# ---- unrecorded folders that are provable duplicates --------------------------------------------

def test_a_folder_that_is_a_copy_of_library_content_is_a_verified_duplicate(config, data_root: Path) -> None:
    _library_album(data_root, TRACKS)
    _leftover(data_root, "Album - Copy", {
        "01. One.flac": TRACKS["01 - One.flac"],      # renamed on the way in: names do not matter
        "02. Two.flac": TRACKS["02 - Two.flac"],
        "cover.jpg": b"art",
        "Album.nfo": b"info",
        "rip.log": b"log",
        "empty.flac": b"",
    })

    action = _action(config, "_INGEST/ready/Album - Copy")

    assert action.category == "verified_duplicate"
    assert action.action == "report_only" and action.safety_status == "awaiting_trash_hold"
    assert action.details["content_files"] == 2 and action.details["matched_files"] == 2
    assert action.details["library_matches"][0]["library_path"].endswith(".flac")


@pytest.mark.parametrize(
    "files, expected_reason_fragment",
    [
        # same size, different bytes
        ({"01.flac": b"x" * len(TRACKS["01 - One.flac"])}, "not in any library"),
        # one file matches, one is new
        ({"01.flac": TRACKS["01 - One.flac"], "99.flac": b"brand new music" * 300}, "not in any library"),
        # a matching file next to a file type Cleaner does not know
        ({"01.flac": TRACKS["01 - One.flac"], "mystery.xyz": b"?"}, "does not recognise"),
        # nothing but artwork: there is nothing to verify
        ({"cover.jpg": b"art"}, "no media files"),
    ],
)
def test_anything_that_is_not_proven_stays_an_unrecorded_leftover(config, data_root: Path, files, expected_reason_fragment) -> None:
    _library_album(data_root, TRACKS)
    _leftover(data_root, "Unknown Thing", files)

    action = _action(config, "_INGEST/ready/Unknown Thing")

    assert action.category == "unrecorded_leftover"
    assert action.action == "report_only" and action.safety_status == "needs_your_decision"
    assert expected_reason_fragment in action.reason


def test_the_age_gate_and_empty_folder_rules_still_apply(config, data_root: Path) -> None:
    _library_album(data_root, TRACKS)
    fresh = data_root / "_INGEST" / "ready" / "Fresh Copy"
    _write(fresh / "01.flac", TRACKS["01 - One.flac"])  # not aged
    empty = data_root / "_INGEST" / "ready" / "Empty Shell"
    empty.mkdir(parents=True)
    make_old(empty)

    assert _action(config, "_INGEST/ready/Fresh Copy").category == "blocked_too_new"
    assert _action(config, "_INGEST/ready/Empty Shell").category == "blocked_by_missing_evidence"


def test_hashing_respects_a_time_budget_and_finishes_later(config, data_root: Path) -> None:
    _library_album(data_root, TRACKS)
    _leftover(data_root, "Album - Copy", {"01.flac": TRACKS["01 - One.flac"]})

    rushed = [a for a in build_plan(config, hash_budget_seconds=0).actions if a.relative_path.endswith("Album - Copy")][0]
    assert rushed.category == "unrecorded_leftover"
    assert rushed.details["duplicate_check"] == "pending"
    assert "run a dry plan" in rushed.reason

    unlimited = _action(config, "_INGEST/ready/Album - Copy")
    assert unlimited.category == "verified_duplicate"


# ---- quarantine discards ----------------------------------------------------------------------------

def _quarantined(data_root: Path, name: str = "Weird Folder") -> Path:
    folder = data_root / "_QUARANTINE" / "unknown-type" / name
    _write(folder / "a.bin", b"aaaa")
    _write(folder / "sub" / "b.bin", b"bbbbbb")
    for path in (*folder.rglob("*"), folder):
        make_old(path)
    return folder


def _inventory(folder: Path) -> dict:
    files = [{"relative_path": p.relative_to(folder).as_posix(), "size_bytes": p.stat().st_size, "modified_at": "x"} for p in sorted(folder.rglob("*")) if p.is_file()]
    return {"exists": True, "kind": "directory", "file_count": len(files), "folder_count": 1, "total_bytes": sum(f["size_bytes"] for f in files), "files": files, "files_truncated": False}


def _disposition(data_root: Path, batch_id: int, action: str, folder: Path, stamp: str, *, reason: str | None = "not needed", decided: str = "2026-01-01T00:00:00Z", current_path: str | None = None) -> None:
    directory = data_root / "_REPORTS" / "archive-assistant" / "dispositions"
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "record_type": "archive_assistant_disposition", "disposition_version": "v1", "created_at": decided,
        "action": action, "batch_id": batch_id, "reason": reason,
        "current_path": current_path or folder.relative_to(data_root).as_posix(),
        "inventory": _inventory(folder),
    }
    (directory / f"{stamp}_{batch_id}_{action}.json").write_text(json.dumps(record), encoding="utf-8")


def test_an_approved_discard_is_picked_up(config, data_root: Path) -> None:
    folder = _quarantined(data_root)
    _disposition(data_root, 7, "quarantined", folder, "20260101T000000000000Z")
    _disposition(data_root, 7, "discard_approved", folder, "20260102T000000000000Z", decided="2026-01-02T00:00:00Z")

    action = _action(config, "_QUARANTINE/unknown-type/Weird Folder")

    assert action.category == "quarantine_discard_approved"
    assert action.action == "report_only" and action.safety_status == "awaiting_trash_hold"
    assert action.details["batch_id"] == 7 and action.details["discard_reason"] == "not needed"
    assert action.details["eligible_now"] is True and action.details["file_count"] == 2
    assert "not needed" in action.reason


def test_an_undecided_quarantined_item_is_left_alone(config, data_root: Path) -> None:
    folder = _quarantined(data_root)
    _disposition(data_root, 7, "quarantined", folder, "20260101T000000000000Z")

    plan = build_plan(config)

    assert not [a for a in plan.actions if a.category == "quarantine_discard_approved"]
    # the quarantine folders themselves are still protected, as before
    assert any(a.category == "quarantine_hold" for a in plan.actions)


@pytest.mark.parametrize("later_action", ["discard_revoked", "restored"])
def test_a_later_decision_cancels_the_discard(config, data_root: Path, later_action: str) -> None:
    folder = _quarantined(data_root)
    _disposition(data_root, 7, "discard_approved", folder, "20260102T000000000000Z")
    _disposition(data_root, 7, later_action, folder, "20260103T000000000000Z")

    assert not [a for a in build_plan(config).actions if a.category == "quarantine_discard_approved"]


def test_a_discard_whose_files_changed_is_not_picked_up(config, data_root: Path) -> None:
    folder = _quarantined(data_root)
    _disposition(data_root, 7, "discard_approved", folder, "20260102T000000000000Z")
    _write(folder / "added-later.bin", b"new")

    action = _action(config, "_QUARANTINE/unknown-type/Weird Folder")

    assert action.category == "quarantine_hold"
    assert "differ from the decision" in action.reason and "1 added" in action.reason


def test_a_discard_still_inside_its_waiting_period_says_when_it_becomes_eligible(config, data_root: Path) -> None:
    folder = _quarantined(data_root)
    soon = "2999-01-01T00:00:00Z"
    _disposition(data_root, 7, "discard_approved", folder, "29990101T000000000000Z", decided=soon)

    action = _action(config, "_QUARANTINE/unknown-type/Weird Folder")

    assert action.category == "quarantine_discard_approved"
    assert action.details["eligible_now"] is False
    assert "eligible after 2999-01-" in action.reason


def test_a_record_pointing_outside_quarantine_is_ignored(config, data_root: Path) -> None:
    library_folder = data_root / "Music" / "Library" / "FLAC" / "Artist" / "2020 - Album"
    _write(library_folder / "01.flac", b"precious" * 100)
    _disposition(data_root, 9, "discard_approved", library_folder, "20260102T000000000000Z")
    _disposition(data_root, 10, "discard_approved", library_folder, "20260102T000001000000Z", current_path="_QUARANTINE/../Music/Library/FLAC/Artist/2020 - Album")
    _disposition(data_root, 11, "discard_approved", library_folder, "20260102T000002000000Z", current_path="_QUARANTINE")

    plan = build_plan(config)

    assert not [a for a in plan.actions if a.category == "quarantine_discard_approved"]
    assert not [a for a in plan.actions if "Library" in a.relative_path and a.category != "do_not_touch"]


# ---- nothing is removed, and the dashboard shows the new lanes -------------------------------------------

def test_even_with_every_production_gate_open_nothing_picked_up_is_touched(config, data_root: Path) -> None:
    _library_album(data_root, TRACKS)
    duplicate = _leftover(data_root, "Album - Copy", {"01.flac": TRACKS["01 - One.flac"], "02.flac": TRACKS["02 - Two.flac"]})
    stray = _leftover(data_root, "Stray", {"new.flac": b"new music" * 300})
    discard = _quarantined(data_root)
    _disposition(data_root, 7, "discard_approved", discard, "20260102T000000000000Z")
    live = replace(config, mode="production", dry_run=False, destructive_actions_enabled=True,
                   allow_empty_folder_removal=True, allow_known_trash_delete=True)
    plan = build_plan(live)
    write_plan_report(live.cleaner_reports_dir, live.cleaner_log_path, plan)

    status, payload = run_execution(live, plan.run_id)

    assert status == HTTPStatus.OK and payload["removed"] == 0
    assert all(p.exists() for p in (duplicate, stray, discard))
    assert len(list(duplicate.rglob("*.flac"))) == 2 and len(list(discard.rglob("*.bin"))) == 2


def test_dashboard_lanes_and_counts(config, data_root: Path) -> None:
    _library_album(data_root, TRACKS)
    _leftover(data_root, "Album - Copy", {"01.flac": TRACKS["01 - One.flac"]})
    _leftover(data_root, "Stray", {"new.flac": b"new music" * 300})
    discard = _quarantined(data_root)
    _disposition(data_root, 7, "discard_approved", discard, "20260102T000000000000Z")

    payload = build_dashboard_payload(config)

    assert [i["relative_path"] for i in payload["lanes"]["duplicates"]] == ["_INGEST/ready/Album - Copy"]
    assert [i["relative_path"] for i in payload["lanes"]["unrecorded"]] == ["_INGEST/ready/Stray"]
    assert [i["relative_path"] for i in payload["lanes"]["quarantine_discards"]] == ["_QUARANTINE/unknown-type/Weird Folder"]
    assert not any(i["category"] in {"verified_duplicate", "unrecorded_leftover", "quarantine_discard_approved"} for i in payload["lanes"]["blocked_by_safety"])
    assert payload["counts"]["verified_duplicate"] == 1 and payload["counts"]["quarantine_discard_approved"] == 1
