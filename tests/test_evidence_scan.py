from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cleaner import evidence
from cleaner.evidence import MAX_EVIDENCE_DEPTH, _manifest_files, clear_evidence_cache, evidence_index
from cleaner.planner import build_plan
from cleaner.server import build_dashboard_payload, run_dry_plan
from .conftest import make_old, write_manifest


@pytest.fixture(autouse=True)
def fresh_cache():
    clear_evidence_cache()
    yield
    clear_evidence_cache()


def _touch_manifest(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source_path": "x"}), encoding="utf-8")
    return path


def _relative(data_root: Path, paths: list[Path]) -> list[str]:
    return sorted(path.relative_to(data_root).as_posix() for path in paths)


def test_finds_manifests_at_every_layout_archive_assistant_writes(data_root: Path) -> None:
    expected = [
        "Music/Library/FLAC/Daft Punk/2023 - Random Access Memories/metadata/move_manifest.json",
        "Movies/Library/2000 - Test/metadata/move_manifest.json",
        "TV/Library/Show/metadata/move_manifest.json",
        "Audiobooks/Library/Frank Herbert/Unknown Year - Dune/metadata/move_manifest.json",
        "Books/PDF/Author/2020 - Title/metadata/move_manifest.json",
        "Music/Discographies/Artist/metadata/move_manifest.json",
        "Music/Metadata/move_manifests/2026-01-01_7_artist-discography_move_manifest.json",
        "Books/Metadata/move_manifests/2026-01-01_8_collection_move_manifest.json",
        "_REPORTS/move_manifests/2026-01-01_9_move_manifest.json",
    ]
    for relative in expected:
        _touch_manifest(data_root / relative)

    assert _relative(data_root, _manifest_files(data_root)) == sorted(expected)


def test_ignores_manifests_outside_the_libraries(data_root: Path) -> None:
    for relative in (
        "Backups/old/Album/metadata/move_manifest.json",
        "Photos/2020/metadata/move_manifest.json",
        "_QUARANTINE/unknown-type/thing/move_manifest.json",
        "_INGEST/ready/Release/move_manifest.json",
        "_REPORTS/cleaner/2026-01-01_move_manifest.json",
        "_REPORTS/archive-assistant/dispositions/x_move_manifest.json",
    ):
        _touch_manifest(data_root / relative)

    assert _manifest_files(data_root) == []


def test_stops_at_the_depth_limit(data_root: Path) -> None:
    deep = data_root / "Music"
    for index in range(MAX_EVIDENCE_DEPTH):
        deep = deep / f"level{index}"
    _touch_manifest(deep / "move_manifest.json")

    assert _manifest_files(data_root) == []

    near = data_root.joinpath("Music", "Library", "FLAC", "Artist", "Album", "metadata", "move_manifest.json")
    _touch_manifest(near)
    assert _relative(data_root, _manifest_files(data_root)) == [near.relative_to(data_root).as_posix()]


def test_scan_lists_folders_only_and_never_walks_the_whole_tree(data_root: Path, monkeypatch) -> None:
    for album in range(30):
        release = data_root / "Music" / "Library" / "FLAC" / f"Artist {album}" / "2020 - Album"
        (release / "metadata").mkdir(parents=True)
        for track in range(25):
            (release / f"{track:02d} Track.flac").write_text("x", encoding="utf-8")
        _touch_manifest(release / "metadata" / "move_manifest.json")
    (data_root / "Photos" / "2020").mkdir(parents=True)
    (data_root / "Photos" / "2020" / "IMG.jpg").write_text("x", encoding="utf-8")

    folders_under_evidence_roots = sum(
        1
        for relative in evidence.EVIDENCE_ROOTS
        if (data_root / relative).is_dir()
        for _folder, _dirs, _files in os.walk(data_root / relative)
    )
    scanned: list[str] = []
    original = os.scandir

    def counting_scandir(path):
        scanned.append(str(path))
        return original(path)

    monkeypatch.setattr(evidence.os, "scandir", counting_scandir)

    assert len(_manifest_files(data_root)) == 30
    assert not any("Photos" in item for item in scanned)
    # Exactly one listing per folder under the evidence roots, however many files they hold
    # (750 audio files here are never opened), and nothing outside those roots.
    assert len(scanned) == folders_under_evidence_roots


def test_evidence_is_read_fresh_by_default(config, data_root: Path, monkeypatch) -> None:
    write_manifest(data_root, "_INGEST/ready/Done")
    reads: list[int] = []
    original = evidence.load_archive_evidence
    monkeypatch.setattr(evidence, "load_archive_evidence", lambda cfg: reads.append(1) or original(cfg))

    evidence_index(config)
    evidence_index(config)

    assert len(reads) == 2


def test_dashboard_cache_expires_and_can_be_bypassed(config, data_root: Path, monkeypatch) -> None:
    write_manifest(data_root, "_INGEST/ready/Done")
    reads: list[int] = []
    original = evidence.load_archive_evidence
    monkeypatch.setattr(evidence, "load_archive_evidence", lambda cfg: reads.append(1) or original(cfg))
    clock = {"now": 1000.0}
    monkeypatch.setattr(evidence, "_now", lambda: clock["now"])

    first = evidence_index(config, max_age_seconds=60)
    clock["now"] += 30
    assert evidence_index(config, max_age_seconds=60) is first
    assert len(reads) == 1

    clock["now"] += 31
    assert evidence_index(config, max_age_seconds=60) is not first
    assert len(reads) == 2

    evidence_index(config)  # max_age_seconds=0 never uses the cache
    assert len(reads) == 3


def test_dashboard_may_use_the_cache_but_written_plans_never_do(config, data_root: Path, monkeypatch) -> None:
    source = data_root / "_INGEST" / "ready" / "Done"
    source.mkdir(parents=True)
    make_old(source)
    write_manifest(data_root, "_INGEST/ready/Done")
    reads: list[int] = []
    original = evidence.load_archive_evidence
    monkeypatch.setattr(evidence, "load_archive_evidence", lambda cfg: reads.append(1) or original(cfg))

    build_dashboard_payload(config)
    build_dashboard_payload(config)
    assert len(reads) == 1

    run_dry_plan(config)
    assert len(reads) == 2
    build_plan(config)
    assert len(reads) == 3


def test_a_new_manifest_is_seen_by_the_next_written_plan_even_while_the_dashboard_is_cached(config, data_root: Path) -> None:
    source = data_root / "_INGEST" / "ready" / "Late Arrival"
    source.mkdir(parents=True)
    make_old(source)

    stale = build_dashboard_payload(config)
    assert stale["counts"].get("blocked_by_missing_evidence") == 1

    write_manifest(data_root, "_INGEST/ready/Late Arrival", destination_rel="Movies/Library/2000 - Late/Late.mkv")

    plan = build_plan(config)
    assert plan.counts.get("safe_empty_folder") == 1
