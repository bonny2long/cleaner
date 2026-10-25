"""Decide whether a folder Archive Assistant has no record of is just a duplicate of library content.

A folder qualifies only when every media file in it is a byte-for-byte copy (SHA-256) of a file
that is already in a final library. Cover art, release notes, rip logs and known junk may sit
beside them. Anything else, such as a media file that is not in the library or a file type
Cleaner does not know, keeps the folder out. Nothing here changes anything on disk.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import CleanerConfig
from .scanner import _is_known_trash, _is_rip_sidecar

CONTENT_EXTENSIONS = frozenset({
    ".flac", ".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".wma", ".alac", ".aiff", ".aif", ".ape", ".wv",
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".webm", ".flv", ".mpg", ".mpeg", ".ts",
    ".epub", ".pdf", ".mobi", ".azw3", ".cbz", ".cbr",
})
ARTWORK_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"})
RELEASE_INFO_EXTENSIONS = frozenset({".nfo", ".sfv", ".md5", ".ffp", ".srt", ".sub", ".idx"})
LIBRARY_ROOT_NAMES = ("Music", "Movies", "TV", "Books", "Audiobooks")
SKIPPED_LIBRARY_FOLDERS = frozenset({"metadata", "move_manifests"})
LIBRARY_INDEX_TTL_SECONDS = 60
MAX_EXAMPLES = 10
_HASH_CACHE_LIMIT = 16384

_lock = threading.Lock()
_hash_cache: dict[tuple[str, int, int], str] = {}
_library_cache: dict[str, tuple[float, dict[int, list[str]]]] = {}


class BudgetExceeded(Exception):
    """The time allowed for hashing ran out; callers report the item as not yet checked."""


@dataclass
class DuplicateAssessment:
    verdict: str  # verified_duplicate | unmatched_content | other_files | no_content | pending | missing
    content_files: int = 0
    matched_files: int = 0
    total_bytes: int = 0
    unmatched: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)

    def details(self) -> dict:
        return {
            "duplicate_check": self.verdict,
            "content_files": self.content_files,
            "matched_files": self.matched_files,
            "total_bytes": self.total_bytes,
            "unmatched_examples": self.unmatched[:MAX_EXAMPLES],
            "other_file_examples": self.other[:MAX_EXAMPLES],
            "library_matches": self.examples,
        }


def clear_caches() -> None:
    with _lock:
        _hash_cache.clear()
        _library_cache.clear()


def _check_budget(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() > deadline:
        raise BudgetExceeded


def sha256_of(path: Path, deadline: float | None = None) -> str:
    """SHA-256, remembered while the file's path, size and modification time are unchanged."""
    import hashlib

    stat = path.stat()
    key = (os.path.normcase(str(path)), stat.st_size, stat.st_mtime_ns)
    with _lock:
        cached = _hash_cache.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            _check_budget(deadline)
            digest.update(chunk)
    value = digest.hexdigest()
    with _lock:
        if len(_hash_cache) >= _HASH_CACHE_LIMIT:
            _hash_cache.clear()
        _hash_cache[key] = value
    return value


def library_size_index(config: CleanerConfig) -> dict[int, list[str]]:
    """Every media file in the final libraries, grouped by size (cached briefly)."""
    key = str(config.data_root)
    now = time.monotonic()
    with _lock:
        cached = _library_cache.get(key)
    if cached is not None and now - cached[0] <= LIBRARY_INDEX_TTL_SECONDS:
        return cached[1]
    index: dict[int, list[str]] = {}
    for name in LIBRARY_ROOT_NAMES:
        stack = [config.data_root / name]
        while stack:
            folder = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.lower() not in SKIPPED_LIBRARY_FOLDERS:
                                    stack.append(Path(entry.path))
                            elif entry.is_file() and os.path.splitext(entry.name)[1].lower() in CONTENT_EXTENSIONS:
                                size = entry.stat().st_size
                                if size > 0:
                                    index.setdefault(size, []).append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue
    with _lock:
        _library_cache[key] = (now, index)
    return index


def _walk_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for folder, _dirs, names in os.walk(root):
        files.extend(Path(folder) / name for name in names)
    return files


def assess_item(config: CleanerConfig, item_path: Path, deadline: float | None = None) -> DuplicateAssessment:
    """Compare every media file under ``item_path`` with the final libraries."""
    if not item_path.exists():
        return DuplicateAssessment("missing")
    files = _walk_files(item_path)
    assessment = DuplicateAssessment("no_content")
    media: list[tuple[Path, int]] = []
    for file in files:
        try:
            size = file.stat().st_size
        except OSError:
            continue
        extension = file.suffix.lower()
        if extension in CONTENT_EXTENSIONS and size > 0:
            media.append((file, size))
            assessment.total_bytes += size
        elif (
            size == 0
            or extension in ARTWORK_EXTENSIONS
            or extension in RELEASE_INFO_EXTENSIONS
            or _is_known_trash(file, config)
            or _is_rip_sidecar(file, config)
        ):
            continue
        else:
            assessment.other.append(file.relative_to(item_path).as_posix() if item_path.is_dir() else file.name)
    assessment.content_files = len(media)
    if not media:
        assessment.verdict = "other_files" if assessment.other else "no_content"
        return assessment

    try:
        library = library_size_index(config)
        for file, size in media:
            label = file.relative_to(item_path).as_posix() if item_path.is_dir() else file.name
            match = None
            candidates = library.get(size, [])
            if candidates:
                source_hash = sha256_of(file, deadline)
                for candidate in candidates:
                    if not Path(candidate).is_file():
                        continue
                    if sha256_of(Path(candidate), deadline) == source_hash:
                        match = candidate
                        break
            if match:
                assessment.matched_files += 1
                if len(assessment.examples) < MAX_EXAMPLES:
                    assessment.examples.append({"file": label, "library_path": match})
            else:
                assessment.unmatched.append(label)
    except BudgetExceeded:
        assessment.verdict = "pending"
        return assessment

    if assessment.other:
        assessment.verdict = "other_files"
    elif assessment.unmatched:
        assessment.verdict = "unmatched_content"
    else:
        assessment.verdict = "verified_duplicate"
    return assessment
