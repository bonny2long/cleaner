from __future__ import annotations

from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

import pytest

from cleaner.planner import build_plan
from cleaner.reports import write_plan_report
from cleaner.server import run_execution
from .conftest import make_old, write_manifest

RIP_FILES = (
    "auCDtect.txt",
    "DR8.txt",
    "Daft Punk - Random Access Memories (1).log",
    "Daft Punk - Random Access Memories (1).cue",
    "Daft Punk - Random Access Memories (1).accurip",
    "Daft Punk - Random Access Memories (1).m3u",
)


def _release(data_root: Path, name: str, files: tuple[str, ...], *, evidence: bool = True, old: bool = True) -> Path:
    source = data_root / "_INGEST" / "ready" / name
    disc = source / "CD 1"
    disc.mkdir(parents=True)
    for filename in files:
        (disc / filename).write_text("rip log", encoding="utf-8")
    if old:
        for path in (*disc.iterdir(), disc, source):
            make_old(path)
    if evidence:
        write_manifest(data_root, f"_INGEST/ready/{name}", destination_rel=f"Music/Library/FLAC/Artist/2023 - {name}/01.flac")
    return source


def _action(config, relative_path: str):
    matches = [action for action in build_plan(config).actions if action.relative_path == relative_path]
    assert matches
    return matches[0]


def test_rip_logs_left_after_a_verified_move_are_known_harmless_trash(config, data_root: Path) -> None:
    source = _release(data_root, "Random Access Memories", RIP_FILES)

    action = _action(config, "_INGEST/ready/Random Access Memories")

    assert action.category == "known_harmless_trash"
    assert action.action == "known_trash_report_only"
    assert "CD-rip logs" in action.reason
    assert action.evidence is not None
    assert all((source / "CD 1" / name).exists() for name in RIP_FILES)


@pytest.mark.parametrize("name", ["AUCDTECT.TXT", "dr13.TXT", "Some Album.LOG", "Some Album.Cue"])
def test_matching_ignores_case(config, data_root: Path, name: str) -> None:
    _release(data_root, "Case Test", (name,))

    assert _action(config, "_INGEST/ready/Case Test").category == "known_harmless_trash"


def test_unmoved_audio_next_to_rip_logs_stays_uncertain(config, data_root: Path) -> None:
    _release(data_root, "Half Moved", (*RIP_FILES, "02 Giorgio by Moroder.flac"))

    action = _action(config, "_INGEST/ready/Half Moved")

    assert action.category == "uncertain_leftover"
    assert action.action == "report_only"


@pytest.mark.parametrize("name", ["Dracula.txt", "DRAFT.txt", "DR.txt", "DR8x.txt", "notes.txt", "booklet.pdf"])
def test_lookalike_names_are_not_rip_sidecars(config, data_root: Path, name: str) -> None:
    _release(data_root, "Lookalike", (*RIP_FILES, name))

    assert _action(config, "_INGEST/ready/Lookalike").category == "uncertain_leftover"


def test_rip_logs_without_move_evidence_stay_blocked(config, data_root: Path) -> None:
    _release(data_root, "No Evidence", RIP_FILES, evidence=False)

    assert _action(config, "_INGEST/ready/No Evidence").category == "blocked_by_missing_evidence"


def test_young_rip_logs_wait_for_the_age_gate(config, data_root: Path) -> None:
    _release(data_root, "Too New", RIP_FILES, old=False)

    assert _action(config, "_INGEST/ready/Too New").category == "blocked_too_new"


def test_execution_never_touches_rip_log_folders(config, data_root: Path) -> None:
    source = _release(data_root, "Keep My Logs", RIP_FILES)
    live = replace(
        config,
        mode="production",
        dry_run=False,
        destructive_actions_enabled=True,
        allow_empty_folder_removal=True,
        allow_known_trash_delete=True,
    )
    plan = build_plan(live)
    write_plan_report(live.cleaner_reports_dir, live.cleaner_log_path, plan)

    status, payload = run_execution(live, plan.run_id)

    assert status == HTTPStatus.OK
    assert payload["removed"] == 0
    assert all((source / "CD 1" / name).exists() for name in RIP_FILES)
