from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import numpy as np
import pandas as pd

from ..errors import ConverterError
from ..config import ConverterConfig
from ..models import EEGProfile, RecordingRecord
from .stimuli import stimulus_reference, stimulus_relative_path


EVENT_COLUMN_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "onset": {"Description": "Image onset relative to the start of the concatenated EEG recording", "Units": "s"},
    "duration": {"Description": "Image presentation duration", "Units": "s"},
    "trial_type": {"Description": "Source trial type"},
    "stim_file": {"Description": "Path relative to the BIDS stimuli directory"},
    "stimulus_id": {"Description": "Source stimulus identifier"},
    "response_time": {"Description": "Reaction time", "Units": "s"},
    "response": {"Description": "Recorded attention-task response"},
    "valence": {"Description": "Participant valence rating"},
    "arousal": {"Description": "Participant arousal rating"},
    "interest": {"Description": "Participant interest rating"},
    "visual_preference": {"Description": "Participant visual-preference rating"},
    "source_eeg_part": {"Description": "One-based source EEG segment index"},
    "source_trial_index": {"Description": "Trial index in the source log"},
}


def _part_offsets(record: RecordingRecord, profile: EEGProfile) -> dict[int, float]:
    offsets: dict[int, float] = {}
    elapsed = 0.0
    for index, path in enumerate(record.eeg_files, start=1):
        offsets[index] = elapsed
        try:
            shape = np.load(path, mmap_mode="r").shape
        except Exception as exc:
            raise ConverterError("EEG_LOAD_FAILURE", f"Cannot inspect {path}: {exc}", record.source_record_id) from exc
        if len(shape) != 2:
            raise ConverterError("INVALID_EEG_SHAPE", f"Expected 2D NPY, got {shape}", record.source_record_id)
        elapsed += float(shape[1]) / profile.sampling_frequency
    return offsets


def _read_trial_log(record: RecordingRecord) -> pd.DataFrame:
    if record.trial_log is None:
        raise ConverterError("MISSING_BEHAVIOR", "trial_log.csv is missing", record.source_record_id)
    try:
        return pd.read_csv(record.trial_log)
    except Exception as exc:
        raise ConverterError("INVALID_BEHAVIOR", f"Cannot read {record.trial_log}: {exc}", record.source_record_id) from exc


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _stimulus_paths(source: pd.DataFrame, record: RecordingRecord) -> pd.Series | None:
    if record.stimulus is None:
        return None
    references = source.apply(lambda row: stimulus_reference(row), axis=1)
    if not references.astype(bool).any():
        return None
    return references.map(
        lambda name: stimulus_relative_path(record.stimulus.library, name).as_posix() if name else "n/a"
    )


def _read_marker_list(path: Path, record: RecordingRecord) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        if not record.is_incomplete:
            raise ConverterError("INVALID_EVENTS_FILE", f"Cannot read {path}: {exc}", record.source_record_id) from exc
        decoder = json.JSONDecoder()
        recovered: list[dict[str, Any]] = []
        position = 1 if text.lstrip().startswith("[") else 0
        while position < len(text):
            while position < len(text) and (text[position].isspace() or text[position] == ","):
                position += 1
            try:
                item, position = decoder.raw_decode(text, position)
            except json.JSONDecodeError:
                break
            if isinstance(item, dict):
                recovered.append(item)
        if not recovered:
            raise ConverterError("INVALID_EVENTS_FILE", f"Cannot recover {path}: {exc}", record.source_record_id) from exc
        warning = f"TRUNCATED_EVENTS_RECOVERED:{len(recovered)}"
        if warning not in record.warnings:
            record.warnings.append(warning)
        return recovered
    if not isinstance(payload, list):
        raise ConverterError("INVALID_EVENTS_FILE", f"Expected a JSON event list in {path}", record.source_record_id)
    return [item for item in payload if isinstance(item, dict)]


def _marker_timings(record: RecordingRecord, profile: EEGProfile) -> pd.DataFrame | None:
    """Return image timings derived from EEG sample indices when available."""
    rows: list[dict[str, float | int]] = []
    missing_offsets = 0
    part_offsets = _part_offsets(record, profile)
    for part, path in enumerate(record.events_files, start=1):
        try:
            payload = _read_marker_list(path, record)
        except OSError as exc:
            raise ConverterError("INVALID_EVENTS_FILE", f"Cannot read {path}: {exc}", record.source_record_id) from exc
        image_on: dict[int, float] = {}
        image_off: dict[int, float] = {}
        for event in payload:
            if not isinstance(event, dict) or event.get("name") not in {"image_on", "image_off"}:
                continue
            event_payload = event.get("payload")
            trial = event_payload.get("trial_idx") if isinstance(event_payload, dict) else None
            sample = event.get("sample_index")
            try:
                trial_number = int(trial)
                sample_number = float(sample)
            except (TypeError, ValueError):
                continue
            target = image_on if event["name"] == "image_on" else image_off
            target.setdefault(trial_number, sample_number)
        for trial, on_sample in image_on.items():
            off_sample = image_off.get(trial)
            if off_sample is None:
                missing_offsets += 1
                duration = 0.0
            else:
                duration = max(0.0, (off_sample - on_sample) / profile.sampling_frequency)
            rows.append(
                {
                    "__part": part,
                    "__trial": trial,
                    "__onset": part_offsets.get(part, 0.0) + on_sample / profile.sampling_frequency,
                    "__duration": duration,
                }
            )
    if not rows:
        return None
    if missing_offsets:
        warning = f"MISSING_IMAGE_OFF:{missing_offsets}"
        if warning not in record.warnings:
            record.warnings.append(warning)
    timing = pd.DataFrame(rows)
    if timing.duplicated(["__part", "__trial"]).any():
        raise ConverterError("DUPLICATE_EVENT_MARKER", "Duplicate image_on marker for a trial", record.source_record_id)
    return timing


def build_events(
    record: RecordingRecord,
    profile: EEGProfile,
    cfg: ConverterConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = _read_trial_log(record)
    required = {"image_onset", "image_offset"}
    missing = required - set(source.columns)
    if missing:
        raise ConverterError("MISSING_EVENT_TIMING", f"trial_log missing columns {sorted(missing)}", record.source_record_id)
    onset = _numeric(source["image_onset"])
    offset = _numeric(source["image_offset"])
    if onset.isna().any() or offset.isna().any():
        raise ConverterError("INVALID_EVENT_TIMING", "Non-numeric image onset/offset found", record.source_record_id)
    parts = _numeric(source["eeg_part"]).fillna(1).astype(int) if "eeg_part" in source else pd.Series(1, index=source.index)
    source = source.copy()
    source["__part"] = parts
    source["__trial"] = (
        _numeric(source["trial_idx"]).astype("Int64")
        if "trial_idx" in source
        else pd.Series(np.arange(1, len(source) + 1), index=source.index, dtype="Int64")
    )
    timing = _marker_timings(record, profile)
    if timing is not None:
        source = source.merge(timing, on=["__part", "__trial"], how="inner", validate="one_to_one")
        if source.empty:
            raise ConverterError("UNALIGNED_BEHAVIOR", "No trial rows match EEG event markers", record.source_record_id)
        onset = source["__onset"]
        duration = source["__duration"]
        parts = source["__part"].astype(int)
    else:
        offsets = _part_offsets(record, profile)
        unknown_parts = sorted(set(parts) - set(offsets))
        if unknown_parts:
            raise ConverterError("MISSING_EEG_PART", f"trial_log references missing parts {unknown_parts}", record.source_record_id)
        onset = onset + parts.map(offsets).astype(float)
        duration = (offset - _numeric(source["image_onset"])).clip(lower=0)
    events = pd.DataFrame({
        "onset": onset,
        "duration": duration,
        "trial_type": source["trial_type"].fillna("n/a") if "trial_type" in source else "n/a",
    })
    stimulus_paths = _stimulus_paths(source, record)
    if stimulus_paths is not None:
        events["stim_file"] = stimulus_paths
    if "image_id" in source:
        events["stimulus_id"] = source["image_id"].fillna("n/a")
    if "reaction_time_ms" in source:
        events["response_time"] = _numeric(source["reaction_time_ms"]) / 1000.0
    if "attention_response" in source:
        events["response"] = source["attention_response"].fillna("n/a")
    for column in ("valence", "arousal", "interest", "visual_preference"):
        if column in source:
            events[column] = source[column]
    events["source_eeg_part"] = parts
    events["source_trial_index"] = source["__trial"]
    events = events.sort_values(["onset", "source_eeg_part", "source_trial_index"], kind="stable").reset_index(drop=True)
    events["onset"] = pd.to_numeric(events["onset"]).round(9)
    events["duration"] = pd.to_numeric(events["duration"]).round(9)
    events = events.replace({np.nan: "n/a"})
    descriptions = {
        column: EVENT_COLUMN_DESCRIPTIONS[column]
        for column in events.columns
        if column in EVENT_COLUMN_DESCRIPTIONS
    }
    if cfg is not None:
        for column, metadata in cfg.task_event_columns.get(record.task, {}).items():
            if column in events.columns:
                descriptions[column] = metadata
    default_presentation = {
        "OperatingSystem": "n/a",
        "SoftwareName": "PsychoPy",
        "SoftwareRRID": "RRID:SCR_006571",
        "SoftwareVersion": "n/a",
        "Code": "n/a",
    }
    descriptions["StimulusPresentation"] = (
        cfg.task_stimulus_presentation.get(record.task, default_presentation)
        if cfg is not None
        else default_presentation
    )
    return events, descriptions


def build_behavior_table(record: RecordingRecord) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = _read_trial_log(record).copy()
    stimulus_paths = _stimulus_paths(source, record)
    if stimulus_paths is not None:
        source["stim_file"] = stimulus_paths
    descriptions = {
        column: {"Description": f"Source behavior column: {column}"}
        for column in source.columns
    }
    if "stim_file" in descriptions:
        descriptions["stim_file"] = {"Description": "Path relative to the BIDS stimuli directory"}
    return source.replace({np.nan: "n/a"}), descriptions
