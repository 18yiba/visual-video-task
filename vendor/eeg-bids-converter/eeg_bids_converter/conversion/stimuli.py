from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from ..errors import ConverterError
from ..models import RecordingRecord


IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
)
VIDEO_SUFFIXES = frozenset(
    {".264", ".h264", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg", ".m4v"}
)
SUPPORTED_STIMULUS_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES
STIMULUS_REFERENCE_COLUMNS = ("stim_file", "image_file", "video_file")
STIMULI_MANIFEST_COLUMNS = ("stim_file", "media_type", "size_bytes", "sha256")


@dataclass(frozen=True, slots=True)
class StimuliSyncSummary:
    files: int
    copied: int
    replaced: int
    pruned: int
    manifest_path: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stimulus_media_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    raise ConverterError(
        "UNSUPPORTED_STIMULUS_FORMAT",
        f"Unsupported stimulus extension {suffix or '<none>'!r} for {filename!r}",
    )


def stimulus_relative_path(library: str, filename: str) -> Path:
    """Return the path stored in BIDS ``stim_file``, relative to /stimuli."""
    return Path(stimulus_media_type(filename)) / library / Path(filename).name


def stimulus_reference(row: Mapping[str, object]) -> str:
    """Read one image/video reference from a source behavior row."""
    values: list[str] = []
    for column in STIMULUS_REFERENCE_COLUMNS:
        value = row.get(column)
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            values.append(Path(text).name)
    unique = list(dict.fromkeys(values))
    if len(unique) > 1:
        raise ConverterError("AMBIGUOUS_STIMULUS", f"Multiple stimulus references in one row: {unique}")
    return unique[0] if unique else ""


def _record_entries(record: RecordingRecord) -> list[tuple[Path, Path, str]]:
    if record.stimulus is None:
        return []
    entries: list[tuple[Path, Path, str]] = []
    for filename in record.stimulus.referenced_files:
        source = record.stimulus.source_root / Path(filename).name
        if not source.is_file():
            raise ConverterError("MISSING_STIMULUS", f"Stimulus disappeared: {source}", record.source_record_id)
        relative = stimulus_relative_path(record.stimulus.library, filename)
        entries.append((source, relative, sha256_file(source)))
    return entries


def _existing_media(stimuli_root: Path) -> set[Path]:
    files: set[Path] = set()
    for media_type in ("image", "video"):
        media_root = stimuli_root / media_type
        if media_root.is_dir():
            files.update(
                path
                for path in media_root.rglob("*")
                if path.is_file() and path.suffix.lower() in SUPPORTED_STIMULUS_SUFFIXES
            )
    return files


def _remove_empty_media_directories(stimuli_root: Path) -> None:
    for media_type in ("image", "video"):
        media_root = stimuli_root / media_type
        if not media_root.is_dir():
            continue
        directories = sorted(
            (path for path in media_root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            if not any(directory.iterdir()):
                directory.rmdir()
        if not any(media_root.iterdir()):
            media_root.rmdir()


def _write_stimuli_manifest(bids_root: Path, stimuli_root: Path) -> Path:
    rows = []
    for path in sorted(_existing_media(stimuli_root)):
        relative = path.relative_to(stimuli_root)
        rows.append(
            {
                "stim_file": relative.as_posix(),
                "media_type": relative.parts[0],
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest_path = bids_root / "code" / "stimuli_manifest.tsv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=STIMULI_MANIFEST_COLUMNS).to_csv(
        manifest_path,
        sep="\t",
        index=False,
        lineterminator="\n",
    )
    return manifest_path


def sync_stimuli(
    records: list[RecordingRecord],
    bids_root: Path,
    *,
    replace: bool = False,
    prune: bool = False,
) -> tuple[dict[str, tuple[int, str]], StimuliSyncSummary]:
    """Copy, verify and optionally reconcile the shared BIDS stimuli tree."""
    bids_root = bids_root.resolve()
    stimuli_root = bids_root / "stimuli"
    desired: dict[Path, tuple[Path, str, str]] = {}
    record_results: dict[str, tuple[int, str]] = {}

    for record in records:
        entries = _record_entries(record)
        hashes: list[str] = []
        for source, relative, source_hash in entries:
            previous = desired.get(relative)
            if previous is not None and previous[1] != source_hash:
                raise ConverterError(
                    "STIMULUS_COLLISION",
                    f"Different source files map to stimuli/{relative.as_posix()}",
                    record.source_record_id,
                )
            desired[relative] = (source, source_hash, record.source_record_id)
            # Keep the per-record aggregate compatible with manifests written
            # by releases that stored all stimuli under the image namespace.
            hashes.append(f"{source.name}:{source_hash}")
        aggregate = (
            hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()
            if hashes
            else ""
        )
        record_results[record.source_record_id] = (len(entries), aggregate)

    copied = 0
    replaced = 0
    for relative, (source, source_hash, source_record_id) in sorted(
        desired.items(), key=lambda item: item[0].as_posix()
    ):
        destination = stimuli_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if not destination.is_file():
                raise ConverterError(
                    "STIMULUS_COLLISION",
                    f"Stimulus target is not a file: {destination}",
                    source_record_id,
                )
            if sha256_file(destination) != source_hash:
                if not replace:
                    raise ConverterError(
                        "STIMULUS_COLLISION",
                        f"Different content at {destination}; use --replace-stimuli to replace it explicitly",
                        source_record_id,
                    )
                shutil.copy2(source, destination)
                replaced += 1
        else:
            shutil.copy2(source, destination)
            copied += 1
        if sha256_file(destination) != source_hash:
            raise ConverterError(
                "STIMULUS_VERIFY_FAILED",
                f"SHA256 verification failed: {destination}",
                source_record_id,
            )

    pruned = 0
    if prune and stimuli_root.is_dir():
        desired_paths = {(stimuli_root / relative).resolve() for relative in desired}
        for path in sorted(_existing_media(stimuli_root)):
            if path.resolve() not in desired_paths:
                path.unlink()
                pruned += 1
        _remove_empty_media_directories(stimuli_root)

    manifest_path = _write_stimuli_manifest(bids_root, stimuli_root)
    summary = StimuliSyncSummary(
        files=len(_existing_media(stimuli_root)),
        copied=copied,
        replaced=replaced,
        pruned=pruned,
        manifest_path=manifest_path,
    )
    return record_results, summary


def copy_record_stimuli(record: RecordingRecord, bids_root: Path) -> tuple[int, str]:
    """Compatibility wrapper for callers that synchronize one record at a time."""
    results, _ = sync_stimuli([record], bids_root)
    return results[record.source_record_id]
