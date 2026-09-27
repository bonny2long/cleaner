from __future__ import annotations

import json
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

import pytest

from cleaner.config import CleanerConfig
from cleaner.executor import CleanerExecutionError, _check_empty_folder_target, load_reviewed_plan
from cleaner.planner import build_plan
from cleaner.reports import write_plan_report
from cleaner.server import run_execution
from .conftest import make_old, write_manifest


@pytest.fixture
def live_config(config: CleanerConfig) -> CleanerConfig:
    return replace(
        config,
        mode="production",
        dry_run=False,
        destructive_actions_enabled=True,
        allow_empty_folder_removal=True,
    )


def _empty_source(data_root: Path, name: str) -> Path:
    source = data_root / "_INGEST" / "ready" / name
    source.mkdir(parents=True)
    make_old(source)
    write_manifest(data_root, f"_INGEST/ready/{name}", destination_rel=f"Movies/Library/2000 - {name}/{name}.mkv")
    return source


def _review(config: CleanerConfig) -> str:
    plan = build_plan(config)
    write_plan_report(config.cleaner_reports_dir, config.cleaner_log_path, plan)
    return plan.run_id


def test_reviewed_empty_folder_is_removed_and_reported(live_config, data_root: Path) -> None:
    empty = _empty_source(data_root, "Done Movie")
    leftover = data_root / "_INGEST" / "ready" / "Has Leftovers"
    leftover.mkdir()
    (leftover / "notes.txt").write_text("keep", encoding="utf-8")
    make_old(leftover / "notes.txt")
    make_old(leftover)
    write_manifest(data_root, "_INGEST/ready/Has Leftovers", destination_rel="Movies/Library/2001 - Other/Other.mkv")

    status, payload = run_execution(live_config, _review(live_config))

    assert status == HTTPStatus.OK
    assert payload["removed"] == 1
    assert not empty.exists()
    assert (leftover / "notes.txt").exists()
    report = json.loads(Path(payload["report_path"]).read_text(encoding="utf-8"))
    assert [item["relative_path"] for item in report["removed"]] == ["_INGEST/ready/Done Movie"]


def test_folder_not_in_reviewed_plan_is_skipped(live_config, data_root: Path) -> None:
    run_id = _review(live_config)
    late = _empty_source(data_root, "Arrived After Review")

    _status, payload = run_execution(live_config, run_id)

    assert late.exists()
    assert any(item["status"] == "skipped_not_in_reviewed_plan" for item in payload["results"])


def test_folder_that_gained_a_file_after_review_is_kept(live_config, data_root: Path) -> None:
    source = _empty_source(data_root, "Refilled")
    run_id = _review(live_config)
    (source / "new-download.flac").write_bytes(b"audio")

    run_execution(live_config, run_id)

    assert (source / "new-download.flac").exists()


def test_protected_paths_are_refused_even_if_empty(live_config, data_root: Path) -> None:
    quarantine_folder = data_root / "_QUARANTINE" / "unknown-type" / "Empty Hold"
    quarantine_folder.mkdir(parents=True)
    library_folder = data_root / "Music" / "Library" / "FLAC" / "Empty Artist"
    library_folder.mkdir(parents=True)
    for target in (quarantine_folder, library_folder, data_root / "_INGEST" / "ready"):
        with pytest.raises(CleanerExecutionError):
            _check_empty_folder_target(live_config, target)
        assert target.exists()


def test_stale_or_invalid_reviewed_plan_is_refused(live_config, data_root: Path) -> None:
    source = _empty_source(data_root, "Old Review")
    run_id = _review(live_config)
    report = live_config.cleaner_reports_dir / f"{run_id}.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    data["created_at"] = "2020-01-01T00:00:00Z"
    report.write_text(json.dumps(data), encoding="utf-8")

    status, payload = run_execution(live_config, run_id)
    assert status == HTTPStatus.BAD_REQUEST
    assert "older than 24 hours" in payload["error"]
    assert source.exists()

    with pytest.raises(CleanerExecutionError):
        load_reviewed_plan(live_config, "../../_INGEST/ready/x")


def test_execution_is_refused_while_report_only(config, data_root: Path) -> None:
    source = _empty_source(data_root, "Report Only")
    status, payload = run_execution(config, _review(config))
    assert status == HTTPStatus.CONFLICT
    assert payload["ok"] is False
    assert source.exists()


def test_empty_disc_subfolders_count_as_empty_and_are_removed(live_config, data_root: Path) -> None:
    source = _empty_source(data_root, "Two Disc Album")
    for disc in ("CD 1", "CD 2"):
        (source / disc).mkdir()
        make_old(source / disc)
    make_old(source)

    status, payload = run_execution(live_config, _review(live_config))

    assert status == HTTPStatus.OK
    assert payload["removed"] == 1
    assert not source.exists()
    removed = [item for item in payload["results"] if item["status"] == "removed_empty_folder"]
    assert removed[0]["folders_removed"] == 3


def test_tree_with_a_file_deep_inside_is_never_removed(live_config, data_root: Path) -> None:
    source = _empty_source(data_root, "Hidden Leftover")
    (source / "CD 1").mkdir()
    (source / "CD 2").mkdir()
    (source / "CD 2" / "track.log").write_text("rip log", encoding="utf-8")
    make_old(source / "CD 2" / "track.log")
    make_old(source)

    run_execution(live_config, _review(live_config))

    assert (source / "CD 2" / "track.log").exists()
    with pytest.raises(CleanerExecutionError):
        _check_empty_folder_target(live_config, source)
