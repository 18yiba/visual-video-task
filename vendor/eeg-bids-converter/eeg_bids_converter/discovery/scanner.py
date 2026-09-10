from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import ConverterConfig
from ..conversion.stimuli import SUPPORTED_STIMULUS_SUFFIXES, stimulus_reference
from ..errors import ConverterError
from ..models import RecordingRecord, ScanSummary, StimulusResolution


_FULL_STAMP = re.compile(r"(?P<date>\d{8})[_-]?(?P<time>\d{6})")
_DATE = re.compile(r"(?P<date>\d{8})")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConverterError("INVALID_JSON", f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConverterError("INVALID_JSON", f"Expected object in {path}")
    return value


def _candidate_score(path: Path) -> tuple[int, int, int]:
    important = (
        "trial_log.csv",
        "behavioral_ratings.csv",
        "events.json",
        "image_playlist.json",
        "continuous_eeg.npy",
    )
    present = sum((path / name).exists() for name in important)
    file_count = sum(1 for item in path.iterdir() if item.is_file())
    # Prefer the more complete bundle; if tied, prefer the shorter canonical path.
    return present, file_count, -len(path.parts)


def _logical_key(metadata: dict[str, Any]) -> tuple[str, str, str]:
    subject = str(metadata.get("subject_id", "")).upper()
    stamp = str(metadata.get("timestamp_label") or metadata.get("session_stamp") or "")
    session_id = str(metadata.get("session_id", ""))
    return subject, stamp, session_id


def _extract_timestamp_label(metadata: dict[str, Any], path: Path) -> str:
    values = [
        metadata.get("timestamp_label"),
        metadata.get("session_stamp"),
        path.parent.name,
        path.name,
    ]
    for value in values:
        if value:
            return str(value)
    return path.name


def _map_session(
    timestamp_label: str,
    source_session_id: int | str | None,
    timezone: str,
    source_record_id: str,
) -> tuple[str, datetime | None, list[str]]:
    match = _FULL_STAMP.search(timestamp_label)
    if match:
        stamp = f"{match.group('date')}{match.group('time')}"
        try:
            dt = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo(timezone))
        except (ValueError, KeyError) as exc:
            raise ConverterError("INVALID_TIMESTAMP", f"Invalid timestamp {timestamp_label!r}", source_record_id) from exc
        return f"{match.group('date')}T{match.group('time')}", dt, []
    date_match = _DATE.search(timestamp_label)
    if date_match and source_session_id not in (None, ""):
        try:
            suffix = f"S{int(source_session_id):02d}"
        except (TypeError, ValueError):
            suffix = "S" + "".join(ch for ch in str(source_session_id) if ch.isalnum())
        return f"{date_match.group('date')}{suffix}", None, ["MISSING_ACQUISITION_TIME"]
    raise ConverterError("INVALID_TIMESTAMP", f"Cannot derive session from {timestamp_label!r}", source_record_id)


def _sanitize_task(value: str) -> str:
    label = "".join(ch for ch in value if ch.isalnum() or ch == "+")
    if not label:
        raise ConverterError("INVALID_TASK", f"Task {value!r} has no valid BIDS label")
    return label


def _resolve_task(metadata: dict[str, Any], cfg: ConverterConfig, source_record_id: str) -> tuple[str, str]:
    task_name = str(metadata.get("task_mode") or metadata.get("task_name") or "")
    mapped = cfg.task_mappings.get(task_name)
    if mapped is None:
        mapped = cfg.default_task
    if mapped is None:
        raise ConverterError("MISSING_TASK", f"No task mapping for {task_name!r}", source_record_id)
    return _sanitize_task(str(mapped)), task_name or str(mapped)


def _ordered_eeg_files(path: Path) -> tuple[Path, ...]:
    segments_path = path / "eeg_segments.json"
    if segments_path.exists():
        try:
            segments = json.loads(segments_path.read_text(encoding="utf-8")).get("segments", [])
        except (OSError, json.JSONDecodeError, AttributeError):
            segments = []
        ordered: list[Path] = []
        for segment in sorted(segments, key=lambda item: int(item.get("part", 0))):
            filename = segment.get("eeg_file")
            if filename and (path / filename).exists():
                ordered.append(path / filename)
        if ordered:
            return tuple(ordered)

    def sort_key(item: Path) -> tuple[int, str]:
        match = re.search(r"_part_(\d+)", item.stem)
        return (int(match.group(1)) if match else 1, item.name)

    return tuple(sorted(path.glob("continuous_eeg*.npy"), key=sort_key))


def _ordered_event_files(path: Path) -> tuple[Path, ...]:
    def sort_key(item: Path) -> tuple[int, str]:
        match = re.search(r"_part_(\d+)", item.stem)
        return (int(match.group(1)) if match else 1, item.name)

    return tuple(sorted(path.glob("events*.json"), key=sort_key))


def _read_stimulus_references(trial_log: Path | None) -> tuple[str, ...]:
    if trial_log is None:
        return ()
    try:
        with trial_log.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            references = {stimulus_reference(row) for row in reader}
    except OSError as exc:
        raise ConverterError("INVALID_BEHAVIOR", f"Cannot read {trial_log}: {exc}") from exc
    references = {value for value in references if value}
    unsupported = sorted(
        value for value in references if Path(value).suffix.lower() not in SUPPORTED_STIMULUS_SUFFIXES
    )
    if unsupported:
        raise ConverterError(
            "UNSUPPORTED_STIMULUS_FORMAT",
            f"Unsupported stimulus files in {trial_log}: {unsupported}",
        )
    return tuple(sorted(references))


def _index_stimulus_libraries(source_root: Path, cfg: ConverterConfig) -> dict[str, tuple[Path, set[str]]]:
    index: dict[str, tuple[Path, set[str]]] = {}
    for name in (*cfg.stimulus_libraries, *cfg.stimulus_aliases):
        library = source_root / name
        if not library.is_dir():
            continue
        names = {
            path.name
            for path in library.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_STIMULUS_SUFFIXES
        }
        if names:
            index[name] = (library, names)
    return index


def _resolve_stimuli(
    references: tuple[str, ...],
    library_index: dict[str, tuple[Path, set[str]]],
    cfg: ConverterConfig,
    source_record_id: str,
) -> StimulusResolution | None:
    if not references:
        return None
    reference_set = set(references)
    matches = [name for name, (_, names) in library_index.items() if reference_set <= names]
    preferred = [name for name in cfg.stimulus_libraries if name in matches]
    if preferred:
        selected = preferred[0]
    elif matches:
        selected = matches[0]
    else:
        coverage = {
            name: len(reference_set & names)
            for name, (_, names) in library_index.items()
        }
        raise ConverterError(
            "MISSING_STIMULUS",
            f"No stimulus library fully covers {len(references)} references; coverage={coverage}",
            source_record_id,
        )
    root, _ = library_index[selected]
    return StimulusResolution(selected, root, references)


def discover_records(source_root: Path, cfg: ConverterConfig) -> ScanSummary:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ConverterError("SOURCE_NOT_FOUND", f"Source root is not a directory: {source_root}")
    subject_re = re.compile(cfg.subject_pattern)
    subject_dirs = [path for path in source_root.iterdir() if path.is_dir() and subject_re.match(path.name)]
    ignored = [path for path in source_root.iterdir() if path not in subject_dirs]
    library_index = _index_stimulus_libraries(source_root, cfg)
    grouped: dict[tuple[str, str, str], list[Path]] = defaultdict(list)
    metadata_by_path: dict[Path, dict[str, Any]] = {}
    errors: list[ConverterError] = []
    for subject_dir in sorted(subject_dirs):
        for metadata_path in sorted(subject_dir.rglob("metadata.json")):
            try:
                metadata = _load_json(metadata_path)
                if str(metadata.get("device_type", "")).casefold() in cfg.excluded_device_types:
                    continue
                grouped[_logical_key(metadata)].append(metadata_path.parent)
                metadata_by_path[metadata_path.parent] = metadata
            except ConverterError as exc:
                errors.append(exc)

    records: list[RecordingRecord] = []
    for paths in grouped.values():
        selected = max(paths, key=_candidate_score)
        metadata = metadata_by_path[selected]
        source_subject = str(metadata.get("subject_id") or selected.parts[-1]).upper()
        subject_digits = "".join(ch for ch in source_subject if ch.isdigit())
        if not subject_digits:
            errors.append(ConverterError("INVALID_SUBJECT", f"Cannot parse subject {source_subject!r}"))
            continue
        subject = subject_digits.zfill(3)
        timestamp_label = _extract_timestamp_label(metadata, selected)
        source_session_id = metadata.get("session_id")
        source_record_id = f"{source_subject}:{timestamp_label}:session-{source_session_id}"
        try:
            session, acq_time, warnings = _map_session(
                timestamp_label, source_session_id, cfg.timezone, source_record_id
            )
            task, task_name = _resolve_task(metadata, cfg, source_record_id)
            trial_log = selected / "trial_log.csv"
            trial_log = trial_log if trial_log.exists() else None
            ratings = selected / "behavioral_ratings.csv"
            ratings = ratings if ratings.exists() else None
            references = _read_stimulus_references(trial_log)
            stimulus = _resolve_stimuli(references, library_index, cfg, source_record_id)
            eeg_files = _ordered_eeg_files(selected)
            if not eeg_files and bool(metadata.get("local_eeg_recorded")):
                warnings.append("MISSING_EEG_FILE")
            duplicates = tuple(path for path in sorted(paths) if path != selected)
            if duplicates:
                warnings.append(f"DUPLICATE_SOURCE:{len(duplicates)}")
            if metadata.get("completed") is False:
                warnings.append("INCOMPLETE_RECORDING")
            records.append(
                RecordingRecord(
                    source_record_id=source_record_id,
                    source_path=selected,
                    duplicate_paths=duplicates,
                    subject=subject,
                    source_subject=source_subject,
                    task=task,
                    task_name=task_name,
                    session=session,
                    source_session_id=source_session_id,
                    timestamp_label=timestamp_label,
                    acq_time=acq_time,
                    metadata=metadata,
                    device_type=str(metadata.get("device_type") or "unknown").lower(),
                    eeg_files=eeg_files,
                    events_files=_ordered_event_files(selected),
                    trial_log=trial_log,
                    behavioral_ratings=ratings,
                    stimulus=stimulus,
                    completed=metadata.get("completed"),
                    termination_reason=metadata.get("termination_reason"),
                    warnings=warnings,
                )
            )
        except ConverterError as exc:
            errors.append(exc)
    records.sort(key=lambda item: (item.subject, item.session, item.task, item.source_record_id))
    return ScanSummary(records=records, ignored_root_items=sorted(ignored), errors=errors)
